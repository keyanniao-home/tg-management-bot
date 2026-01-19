"""
号商识别服务

基于用户的详细信息和频道内容识别号商（广告账号）
使用 TOON 格式编码数据以节省 token，使用简单文本格式返回结果
"""

from typing import Optional
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from loguru import logger
from toon_format import encode

from app.database.connection import engine
from app.models import UserProfile, UserChannel, ChannelMessage
from app.services.ai.service import ai_service


class ScammerDetectionResult(BaseModel):
    """号商识别结果"""

    is_scammer: bool = Field(
        description="是否为号商（卖号、代充、广告账号等）"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="置信度，范围 0-1"
    )
    evidence: str = Field(
        description="判断依据和证据说明"
    )


class ScammerDetector:
    """号商检测器"""

    async def get_user_data(self, user_id: int) -> Optional[dict]:
        """
        获取用户的完整数据

        Args:
            user_id: 用户ID

        Returns:
            用户数据字典，如果用户不存在则返回 None
        """
        with Session(engine) as session:
            # 获取用户资料
            profile_statement = select(UserProfile).where(UserProfile.user_id == user_id)
            profile = session.exec(profile_statement).first()

            if not profile:
                logger.warning(f"用户 {user_id} 没有资料记录")
                return None

            data = {
                "user_id": profile.user_id,
                "username": profile.username,
                "full_name": f"{profile.first_name or ''} {profile.last_name or ''}".strip(),
                "bio": profile.bio,
                "channels": []
            }

            # 获取关联频道
            channels_statement = select(UserChannel).where(
                UserChannel.user_profile_id == profile.id
            )
            channels = session.exec(channels_statement).all()

            for channel in channels:
                channel_data = {
                    "channel_title": channel.channel_title,
                    "channel_about": channel.channel_about,
                    "is_personal": channel.is_personal_channel,
                    "messages": []
                }

                # 获取频道消息
                messages_statement = (
                    select(ChannelMessage)
                    .where(ChannelMessage.channel_id == channel.id)
                    .order_by(ChannelMessage.posted_at.desc())
                    .limit(50)  # 最多50条消息
                )
                messages = session.exec(messages_statement).all()

                for msg in messages:
                    if msg.text:
                        channel_data["messages"].append({
                            "text": msg.text,
                            "is_pinned": msg.is_pinned,
                            "views": msg.views
                        })

                data["channels"].append(channel_data)

            return data

    def format_user_data_for_ai(self, user_data: dict) -> str:
        """
        将用户数据格式化为AI输入（使用 TOON 格式）

        Args:
            user_data: 用户数据字典

        Returns:
            TOON 格式的紧凑文本
        """
        # 使用 toon 格式编码，节省 token
        return encode(user_data)

    async def detect_scammer(self, user_id: int) -> Optional[ScammerDetectionResult]:
        """
        检测用户是否为号商

        Args:
            user_id: 用户ID

        Returns:
            检测结果，如果用户数据不足则返回 None
        """
        if not ai_service.is_configured():
            raise RuntimeError("AI 服务未配置")

        # 获取用户数据
        logger.info(f"获取用户 {user_id} 的数据...")
        user_data = await self.get_user_data(user_id)

        if not user_data:
            logger.warning(f"用户 {user_id} 数据不足，无法进行检测")
            return None

        # 格式化数据
        formatted_data = self.format_user_data_for_ai(user_data)

        # 构建提示词
        system_prompt = """你是一个专业的号商（广告账号）识别专家。

号商的特征包括但不限于：
1. 卖号、代充、游戏币交易等业务
2. 频繁发布广告信息
3. 个人简介或频道包含联系方式（如 Telegram、微信等）
4. 频道内容主要是商品宣传或服务推广
5. 使用诱导性语言吸引用户购买

注意事项:
如果内容明显是偏向搞笑娱乐，不要将其识别为号商，例子:
我是秦始皇，v我50封你为大将军
我是美国皇帝，给我买美国国债 @ErCiYua


注意：用户信息使用 TOON 格式编码（类似 YAML 风格的紧凑格式）。
请根据用户的详细信息，判断该用户是否为号商。

你必须按照以下格式返回结果：
第一行：是 或 否
第二行：置信度（0-100）
第三行开始：判断依据和证据说明"""

        user_prompt = f"""以下是用户的详细信息：

{formatted_data}

请分析该用户是否为号商（卖号、代充、广告账号等），并按要求格式返回结果。"""

        logger.info(f"开始号商检测...")

        # 调用AI进行分析
        response = await ai_service.generate_text(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.3,  # 使用较低温度以获得更确定的结果
            max_tokens=1000
        )

        logger.debug(f"AI 原始响应:\n{response}")

        # 解析文本响应
        try:
            lines = response.strip().split('\n')

            if len(lines) < 3:
                raise ValueError(f"响应行数不足，需要至少3行，实际: {len(lines)}")

            # 第一行：是/否
            first_line = lines[0].strip()
            is_scammer = first_line in ['是', 'yes', 'Yes', 'YES', 'true', 'True']

            # 第二行：置信度
            second_line = lines[1].strip()
            try:
                # 尝试提取数字
                confidence_str = ''.join(c for c in second_line if c.isdigit() or c == '.')
                confidence = float(confidence_str) / 100.0  # 转换为0-1范围
                confidence = max(0.0, min(1.0, confidence))  # 限制在0-1之间
            except:
                confidence = 0.5  # 默认值

            # 第三行开始：依据
            evidence = '\n'.join(lines[2:]).strip()

            # 构建结果对象
            result = ScammerDetectionResult(
                is_scammer=is_scammer,
                confidence=confidence,
                evidence=evidence
            )

            logger.info(f"号商检测完成: is_scammer={result.is_scammer}, confidence={result.confidence}")
            return result

        except Exception as e:
            logger.error(f"解析 AI 响应失败: {e}")
            logger.error(f"原始响应: {response}")
            # 返回默认结果
            return ScammerDetectionResult(
                is_scammer=False,
                confidence=0.0,
                evidence=f"解析失败: {str(e)}\n\n原始响应:\n{response}"
            )


# 全局实例
scammer_detector = ScammerDetector()
