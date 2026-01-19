"""
用户画像分析服务

基于用户的历史消息生成用户画像
使用 TOON 格式编码数据以节省 token
相同风格的画像缓存1小时
"""

from typing import Optional, List
from datetime import datetime, UTC, timedelta
from sqlmodel import Session, select
from loguru import logger
from toon_format import encode
import hashlib

from app.database.connection import engine
from app.models import Message, GroupMember, GroupConfig
from app.services.ai.service import ai_service


class ProfileStyleCache:
    """用户画像风格缓存（内存缓存，TTL 1小时）"""

    def __init__(self, ttl_minutes: int = 60):
        """
        初始化缓存

        Args:
            ttl_minutes: 缓存过期时间（分钟），默认60分钟
        """
        self.ttl_minutes = ttl_minutes
        self._cache = {}  # {cache_key: (result, expire_at)}

    def _make_cache_key(self, group_db_id: int, user_id: int, style: str, messages_hash: str) -> str:
        """
        生成缓存键

        Args:
            group_db_id: 群组数据库ID
            user_id: 用户ID
            style: 风格
            messages_hash: 消息内容的哈希值

        Returns:
            缓存键
        """
        return f"{group_db_id}:{user_id}:{style}:{messages_hash}"

    def _hash_messages(self, messages: List[Message]) -> str:
        """
        计算消息列表的哈希值

        Args:
            messages: 消息列表

        Returns:
            MD5哈希值
        """
        # 使用消息ID和文本内容生成哈希
        content = ''.join(f"{msg.id}:{msg.text}" for msg in messages)
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def get(self, group_db_id: int, user_id: int, style: str, messages: List[Message]) -> Optional[str]:
        """
        获取缓存的画像结果

        Args:
            group_db_id: 群组数据库ID
            user_id: 用户ID
            style: 风格
            messages: 消息列表

        Returns:
            缓存的结果，如果没有或已过期则返回 None
        """
        messages_hash = self._hash_messages(messages)
        cache_key = self._make_cache_key(group_db_id, user_id, style, messages_hash)

        if cache_key in self._cache:
            result, expire_at = self._cache[cache_key]
            if datetime.now(UTC) < expire_at:
                logger.info(f"使用缓存的画像结果: user_id={user_id}, style={style}")
                return result
            else:
                # 过期，删除缓存
                del self._cache[cache_key]
                logger.debug(f"缓存已过期: {cache_key}")

        return None

    def set(self, group_db_id: int, user_id: int, style: str, messages: List[Message], result: str) -> None:
        """
        设置缓存

        Args:
            group_db_id: 群组数据库ID
            user_id: 用户ID
            style: 风格
            messages: 消息列表
            result: 画像结果
        """
        messages_hash = self._hash_messages(messages)
        cache_key = self._make_cache_key(group_db_id, user_id, style, messages_hash)
        expire_at = datetime.now(UTC) + timedelta(minutes=self.ttl_minutes)

        self._cache[cache_key] = (result, expire_at)
        logger.debug(f"缓存画像结果: {cache_key}, 过期时间: {expire_at}")

    def cleanup_expired(self) -> None:
        """清理过期的缓存项"""
        now = datetime.now(UTC)
        expired_keys = [
            key for key, (_, expire_at) in self._cache.items()
            if now >= expire_at
        ]

        for key in expired_keys:
            del self._cache[key]

        if expired_keys:
            logger.debug(f"清理了 {len(expired_keys)} 个过期缓存项")


# 全局缓存实例
_profile_style_cache = ProfileStyleCache(ttl_minutes=60)


class UserProfileAnalyzer:
    """用户画像分析器"""

    def __init__(self, max_messages: int = 1000, default_char_limit: int = 10000):
        """
        初始化分析器

        Args:
            max_messages: 最多获取的消息数
            default_char_limit: 默认字符数限制
        """
        self.max_messages = max_messages
        self.default_char_limit = default_char_limit

    async def get_user_messages(
        self,
        group_db_id: int,
        user_id: int,
        limit: int = 1000
    ) -> List[Message]:
        """
        获取用户在群组的历史消息

        Args:
            group_db_id: 群组数据库ID
            user_id: 用户ID
            limit: 获取数量限制

        Returns:
            消息列表（按时间升序）
        """
        with Session(engine) as session:
            # 获取群组成员记录
            member_statement = select(GroupMember).where(
                GroupMember.group_id == group_db_id,
                GroupMember.user_id == user_id
            )
            member = session.exec(member_statement).first()

            if not member:
                logger.warning(f"用户 {user_id} 不在群组 {group_db_id} 中")
                return []

            # 获取消息（只要文本消息）
            statement = (
                select(Message)
                .where(
                    Message.member_id == member.id,
                    Message.text.isnot(None),
                    Message.text != ""
                )
                .order_by(Message.created_at.desc())
                .limit(limit)
            )

            messages = session.exec(statement).all()

            # 按时间升序排列（最新的在下面）
            return list(reversed(messages))

    def trim_messages_by_char_limit(
        self,
        messages: List[Message],
        char_limit: int
    ) -> List[Message]:
        """
        根据字符限制裁剪消息列表

        如果超过字符限制，从列表中pop出最长的消息，直到符合要求

        Args:
            messages: 消息列表
            char_limit: 字符限制

        Returns:
            裁剪后的消息列表
        """
        # 创建副本避免修改原列表
        result = messages.copy()

        while result:
            total_chars = sum(len(msg.text or "") for msg in result)
            if total_chars <= char_limit:
                break

            # 找到最长的消息并移除
            longest_msg = max(result, key=lambda m: len(m.text or ""))
            result.remove(longest_msg)
            logger.debug(f"移除最长消息（{len(longest_msg.text)} 字符），剩余 {len(result)} 条消息")

        logger.info(f"裁剪后消息数: {len(result)}, 总字符数: {sum(len(msg.text or '') for msg in result)}")
        return result

    def format_messages_for_ai(self, messages: List[Message]) -> str:
        """
        将消息列表格式化为AI输入（使用 TOON 格式）

        Args:
            messages: 消息列表

        Returns:
            TOON 格式的紧凑文本
        """
        # 将消息转为简洁的字典列表
        message_data = [
            {
                "time": msg.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "text": msg.text
            }
            for msg in messages
        ]

        # 使用 toon 格式编码，节省 token
        return encode(message_data)

    async def analyze_user_profile(
        self,
        group_db_id: int,
        user_id: int,
        char_limit: Optional[int] = None,
        style: str = "客观风"
    ) -> str:
        """
        分析用户画像（使用缓存）

        Args:
            group_db_id: 群组数据库ID
            user_id: 用户ID
            char_limit: 字符限制（可选，默认使用群组配置或默认值）
            style: 描述风格（限制10个字符，如：中二风、文艺风、冷幽默等）

        Returns:
            用户画像分析结果
        """
        # 限制风格长度为10个字符
        if len(style) > 10:
            style = style[:10]
        if not ai_service.is_configured():
            raise RuntimeError("AI 服务未配置")

        # 获取字符限制
        if char_limit is None:
            with Session(engine) as session:
                group = session.get(GroupConfig, group_db_id)
                if group and group.config.get("user_profile_char_limit"):
                    char_limit = group.config["user_profile_char_limit"]
                else:
                    char_limit = self.default_char_limit

        # 获取用户消息
        logger.info(f"获取用户 {user_id} 在群组 {group_db_id} 的消息...")
        messages = await self.get_user_messages(group_db_id, user_id, self.max_messages)

        if not messages:
            return "该用户暂无消息记录，无法生成画像。"

        # 根据字符限制裁剪
        messages = self.trim_messages_by_char_limit(messages, char_limit)

        if not messages:
            return "消息内容过长且无法裁剪，无法生成画像。"

        # 检查缓存（针对相同风格和消息内容）
        cached_result = _profile_style_cache.get(group_db_id, user_id, style, messages)
        if cached_result:
            return '(CACHE HIT) \n' + cached_result

        # 格式化消息
        formatted_messages = self.format_messages_for_ai(messages)

        # 构建提示词
        system_prompt = """扮演一名聊天风格鉴定师，你能根据要求切换描述风格。我会给出某个群成员的聊天记录片段和一个指定风格关键词，请根据聊天内容，以该风格描述这位成员的'虚拟人设'或'精神状态画像'。要求幽默有趣，不要涉及隐私。

注意：聊天记录使用 TOON 格式编码（类似 YAML 风格的紧凑格式）。

风格示例：中二风 / 文艺风 / 冷幽默 / 客观风（你也可尝试其他风格）"""

        user_prompt = f"""现在风格：{style}

聊天记录：
{formatted_messages}

请生成分析结果。"""

        logger.info(f"开始生成用户画像，消息数: {len(messages)}, 风格: {style}")

        # 调用AI生成画像
        profile_text = await ai_service.generate_text(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.7,
            max_tokens=1500
        )

        logger.info("用户画像生成完成")

        # 缓存结果
        _profile_style_cache.set(group_db_id, user_id, style, messages, profile_text)

        # 定期清理过期缓存
        _profile_style_cache.cleanup_expired()

        return profile_text


# 全局实例
user_profile_analyzer = UserProfileAnalyzer()
