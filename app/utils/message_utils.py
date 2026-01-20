"""
消息工具函数
提供消息处理相关的辅助功能
"""
from telegram import Message
from typing import Optional


def is_real_reply(message: Message) -> bool:
    """
    判断消息是否是真实的回复（而不是话题内的发言）

    在 Telegram 的话题（Topic）功能中：
    - message.reply_to_message.message_thread_id == message.reply_to_message.id
      表示用户只是在话题内发言，不是真正回复某条消息（假回复）
    - 如果不相等，则是真正在回复某条消息（真回复）

    参数:
        message: Telegram Message 对象

    返回:
        bool: True 表示真实回复，False 表示假回复或没有回复
    """
    if not message or not message.reply_to_message:
        return False

    reply_to = message.reply_to_message

    # 如果没有 message_thread_id，说明不在话题中，是真实回复
    if not reply_to.message_thread_id:
        return True

    # 在话题中，需要判断是否是假回复
    # 假回复: reply_to_message.message_thread_id == reply_to_message.id
    # 真回复: reply_to_message.message_thread_id != reply_to_message.id
    return reply_to.message_thread_id != reply_to.id


def get_real_reply_message(message: Message) -> Optional[Message]:
    """
    获取真实的回复消息（过滤掉假回复）

    参数:
        message: Telegram Message 对象

    返回:
        Message: 如果是真实回复，返回被回复的消息；否则返回 None
    """
    if is_real_reply(message):
        return message.reply_to_message
    return None
