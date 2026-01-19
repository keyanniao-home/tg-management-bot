"""
消息自毁装饰器

对所有管理命令添加自毁功能：
- 在指定时间后自动删除用户的命令消息和bot的回复消息
- 可为不同命令设置不同的删除时间
"""
import asyncio
from functools import wraps
from telegram import Update, Message
from telegram.ext import ContextTypes
from loguru import logger


def auto_delete_message(delay: int = 30, custom_delays: dict = None):
    """
    消息自毁装饰器

    Args:
        delay: 默认延迟删除的秒数（默认30秒）
        custom_delays: 特定命令的自定义延迟时间，例如 {'stats': 120, 'inactive': 240}
    """
    if custom_delays is None:
        custom_delays = {}

    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            # 获取命令名称
            command_name = func.__name__.replace('_command', '').replace('_callback', '')

            # 获取该命令的延迟时间
            delete_delay = custom_delays.get(command_name, delay)

            # 保存用户的命令消息
            user_message = update.message if update.message else None

            # 执行原函数并获取bot的回复消息
            result = await func(update, context)

            # 获取bot发送的回复消息
            bot_message = None
            if isinstance(result, Message):
                bot_message = result

            # 安排删除任务
            if user_message or bot_message:
                asyncio.create_task(
                    _delete_messages_after_delay(
                        user_message,
                        bot_message,
                        delete_delay,
                        update.effective_chat.id
                    )
                )

            return result
        return wrapper
    return decorator


async def _delete_messages_after_delay(user_message: Message | None, bot_message: Message | None, delay: int, chat_id: int):
    """
    延迟删除消息

    Args:
        user_message: 用户的命令消息
        bot_message: bot的回复消息
        delay: 延迟秒数
        chat_id: 聊天ID（用于日志）
    """
    await asyncio.sleep(delay)

    deleted_count = 0

    # 删除用户消息
    if user_message:
        try:
            await user_message.delete()
            deleted_count += 1
        except Exception as e:
            logger.warning(f"Failed to delete user message in chat {chat_id}: {e}")

    # 删除bot消息
    if bot_message:
        try:
            await bot_message.delete()
            deleted_count += 1
        except Exception as e:
            logger.warning(f"Failed to delete bot message in chat {chat_id}: {e}")

    if deleted_count > 0:
        logger.debug(f"Auto-deleted {deleted_count} messages in chat {chat_id} after {delay}s")


def track_bot_message(func):
    """
    装饰器：追踪bot发送的消息并返回消息对象

    这个装饰器需要包裹命令处理函数，确保返回bot发送的消息对象
    用于配合auto_delete_message使用
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        result = await func(update, context)
        return result
    return wrapper
