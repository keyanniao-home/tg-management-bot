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
from telegram.error import BadRequest, Forbidden
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
            command_name = func.__name__.replace("_command", "").replace(
                "_callback", ""
            )

            # 获取该命令的延迟时间
            delete_delay = custom_delays.get(command_name, delay)

            # 保存用户的命令消息ID和聊天ID（而不是消息对象）
            user_message_id = None
            user_chat_id = None
            if update.message:
                user_message_id = update.message.message_id
                user_chat_id = update.message.chat_id

            # 执行原函数并获取bot的回复消息
            result = await func(update, context)

            # 获取bot发送的回复消息ID
            bot_message_id = None
            bot_chat_id = None
            if isinstance(result, Message):
                bot_message_id = result.message_id
                bot_chat_id = result.chat_id

            # 安排删除任务（使用context.bot来删除消息）
            if user_message_id or bot_message_id:
                asyncio.create_task(
                    _delete_messages_after_delay(
                        context.bot,
                        user_message_id,
                        user_chat_id,
                        bot_message_id,
                        bot_chat_id,
                        delete_delay,
                    )
                )

            return result

        return wrapper

    return decorator


async def _delete_messages_after_delay(
    bot,
    user_message_id: int | None,
    user_chat_id: int | None,
    bot_message_id: int | None,
    bot_chat_id: int | None,
    delay: int,
):
    """
    延迟删除消息

    Args:
        bot: Telegram Bot 实例
        user_message_id: 用户消息ID
        user_chat_id: 用户消息所在的聊天ID
        bot_message_id: bot消息ID
        bot_chat_id: bot消息所在的聊天ID
        delay: 延迟秒数
    """
    await asyncio.sleep(delay)

    deleted_count = 0
    chat_id_for_log = user_chat_id or bot_chat_id

    # 删除用户消息
    if user_message_id and user_chat_id:
        try:
            await bot.delete_message(chat_id=user_chat_id, message_id=user_message_id)
            deleted_count += 1
        except BadRequest as e:
            # 消息已被删除或不存在，静默忽略
            if "Message to delete not found" in str(e):
                logger.trace(
                    f"User message {user_message_id} already deleted in chat {user_chat_id}"
                )
            else:
                logger.debug(f"Cannot delete user message in chat {user_chat_id}: {e}")
        except Forbidden:
            # Bot 没有删除消息的权限，静默忽略
            logger.trace(f"No permission to delete user message in chat {user_chat_id}")
        except Exception as e:
            logger.debug(f"Failed to delete user message in chat {user_chat_id}: {e}")

    # 删除bot消息
    if bot_message_id and bot_chat_id:
        try:
            await bot.delete_message(chat_id=bot_chat_id, message_id=bot_message_id)
            deleted_count += 1
        except BadRequest as e:
            if "Message to delete not found" in str(e):
                logger.trace(
                    f"Bot message {bot_message_id} already deleted in chat {bot_chat_id}"
                )
            else:
                logger.debug(f"Cannot delete bot message in chat {bot_chat_id}: {e}")
        except Forbidden:
            logger.trace(f"No permission to delete bot message in chat {bot_chat_id}")
        except Exception as e:
            logger.debug(f"Failed to delete bot message in chat {bot_chat_id}: {e}")

    if deleted_count > 0:
        logger.debug(
            f"Auto-deleted {deleted_count} messages in chat {chat_id_for_log} after {delay}s"
        )


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
