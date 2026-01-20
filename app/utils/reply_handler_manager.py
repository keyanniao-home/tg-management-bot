"""
回复处理器管理模块

管理需要用户回复bot消息的处理器：
- 注册bot消息ID和对应的回复处理器
- 在用户回复时路由到正确的处理器
- 自动清理过期的处理器
"""

from typing import Dict, Callable, Any, Optional
from dataclasses import dataclass
from loguru import logger
import asyncio


@dataclass
class ReplyHandlerInfo:
    """回复处理器信息"""
    handler: Callable  # 处理器函数
    handler_name: str  # 处理器名称（用于日志）
    bot_message_id: int  # bot发送的消息ID
    chat_id: int  # 聊天ID


class ReplyHandlerManager:
    """回复处理器管理器"""

    def __init__(self):
        # {bot_message_id: ReplyHandlerInfo}
        self._handlers: Dict[int, ReplyHandlerInfo] = {}

    def register(
        self,
        bot_message_id: int,
        chat_id: int,
        handler: Callable,
        handler_name: str
    ) -> None:
        """
        注册一个回复处理器

        Args:
            bot_message_id: bot发送的消息ID
            chat_id: 聊天ID
            handler: 处理器函数
            handler_name: 处理器名称
        """
        self._handlers[bot_message_id] = ReplyHandlerInfo(
            handler=handler,
            handler_name=handler_name,
            bot_message_id=bot_message_id,
            chat_id=chat_id
        )
        logger.debug(
            f"注册回复处理器: {handler_name} (bot_msg_id={bot_message_id}, chat_id={chat_id})"
        )

    def get_handler(self, bot_message_id: int) -> Optional[ReplyHandlerInfo]:
        """
        获取回复处理器

        Args:
            bot_message_id: bot发送的消息ID

        Returns:
            ReplyHandlerInfo 或 None
        """
        return self._handlers.get(bot_message_id)

    def unregister(self, bot_message_id: int) -> bool:
        """
        注销一个回复处理器（处理成功后调用）

        Args:
            bot_message_id: bot发送的消息ID

        Returns:
            是否成功注销
        """
        if bot_message_id in self._handlers:
            handler_info = self._handlers[bot_message_id]
            del self._handlers[bot_message_id]
            logger.debug(
                f"注销回复处理器: {handler_info.handler_name} (bot_msg_id={bot_message_id})"
            )
            return True
        return False

    def has_handler(self, bot_message_id: int) -> bool:
        """
        检查是否有注册的处理器

        Args:
            bot_message_id: bot发送的消息ID

        Returns:
            是否存在处理器
        """
        return bot_message_id in self._handlers


# 全局实例
reply_handler_manager = ReplyHandlerManager()
