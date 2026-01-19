"""
User Bot 客户端管理模块

提供基于 Telethon 的 User Bot 客户端单例，用于补充 Telegram Bot API 无法实现的功能
例如：拉取群组成员列表、获取完整用户信息等
"""

from typing import Optional
from telethon import TelegramClient
from loguru import logger


class UserBotClient:
    """User Bot 客户端单例管理器，作为 Bot API 的补充"""

    _instance: Optional['UserBotClient'] = None
    _client: Optional[TelegramClient] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化单例"""
        pass

    async def start(self, api_id: int, api_hash: str, session_path: str = "sessions/userbot") -> bool:
        """
        启动 User Bot 客户端

        Args:
            api_id: Telegram API ID
            api_hash: Telegram API Hash
            session_path: Session 文件路径（不含 .session 后缀）

        Returns:
            bool: 是否启动成功
        """
        if self._client is not None:
            logger.warning("User Bot 客户端已启动")
            return True

        try:
            logger.info("正在启动 User Bot 客户端...")

            # 确保 sessions 目录存在
            from pathlib import Path
            session_dir = Path(session_path).parent
            session_dir.mkdir(parents=True, exist_ok=True)

            self._client = TelegramClient(session_path, api_id, api_hash)

            # 使用已有 session，无需手机号
            await self._client.start()

            if self._client.is_connected():
                me = await self._client.get_me()
                logger.info(f"✅ User Bot 客户端已启动 - {me.first_name} (@{me.username or '无'})")
                return True
            else:
                logger.error("❌ User Bot 客户端连接失败")
                self._client = None
                return False

        except Exception as e:
            logger.error(f"❌ User Bot 客户端启动失败: {e}")
            self._client = None
            return False

    async def stop(self) -> None:
        """停止 User Bot 客户端"""
        if self._client is None:
            return

        try:
            logger.info("正在停止 User Bot 客户端...")
            await self._client.disconnect()
            self._client = None
            logger.info("✅ User Bot 客户端已停止")
        except Exception as e:
            logger.error(f"停止 User Bot 客户端时出错: {e}")

    def is_connected(self) -> bool:
        """检查客户端是否已连接"""
        return self._client is not None and self._client.is_connected()

    @property
    def client(self) -> Optional[TelegramClient]:
        """获取客户端实例"""
        return self._client

    async def get_entity(self, entity_id):
        """
        获取实体信息（群组、用户等）

        Args:
            entity_id: 实体ID（可以是数字ID或 @username）

        Returns:
            实体对象
        """
        if not self.is_connected():
            raise RuntimeError("User Bot 客户端未连接")

        return await self._client.get_entity(entity_id)

    @staticmethod
    def convert_to_bot_api_id(telethon_id: int) -> int:
        """
        将 Telethon (MTProto) 格式的 ID 转换为 Bot API 格式

        Args:
            telethon_id: Telethon 格式的 ID

        Returns:
            Bot API 格式的 ID

        Example:
            Telethon: 3588609693
            Bot API: -1003588609693
        """
        if telethon_id < 0:
            return telethon_id
        return int(f"-100{telethon_id}")


# 全局单例实例
userbot_client = UserBotClient()

