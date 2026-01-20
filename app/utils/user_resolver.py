from typing import Optional, Tuple
from telegram import Update, User
from sqlmodel import Session, select
from app.utils.message_utils import is_real_reply


class UserResolver:
    """
    用户解析工具
    支持三种方式解析用户:
    1. 用户ID: /ban 93705507
    2. 用户名: /ban @tabeinana
    3. 回复消息: /ban (回复某条消息)
    """

    @staticmethod
    def resolve(update: Update, args: list[str], session: Optional[Session] = None, group_id: Optional[int] = None) -> Optional[Tuple[int, Optional[str], str]]:
        """
        解析用户信息
        返回: (user_id, username, full_name) 或 None

        参数:
        - update: Telegram Update对象
        - args: 命令参数列表
        - session: 数据库会话（用于@username查询）
        - group_id: 群组数据库ID（用于@username查询）
        """
        # 情况1: 回复消息
        if is_real_reply(update.message):
            # 判断是频道消息还是用户消息
            if update.message.reply_to_message.sender_chat:
                # 频道消息
                sender_chat = update.message.reply_to_message.sender_chat
                return (sender_chat.id, sender_chat.username, sender_chat.title or "Unknown Channel")
            else:
                # 用户消息
                target_user = update.message.reply_to_message.from_user
                if target_user:
                    return UserResolver._extract_user_info(target_user)

        # 情况2和3: 需要参数
        if not args:
            return None

        target = args[0]

        # 情况2: @username
        if target.startswith("@"):
            username = target[1:]  # 移除@符号

            # 如果提供了数据库会话和群组ID，从数据库查询（包括用户和频道）
            if session and group_id:
                from app.models import GroupMember

                statement = select(GroupMember).where(
                    GroupMember.group_id == group_id,
                    GroupMember.username == username
                )
                member = session.exec(statement).first()

                if member:
                    return (member.user_id, member.username, member.full_name)

            # 如果没有数据库会话或查询不到，返回None
            return None

        # 情况3: user_id (纯数字)
        if target.isdigit():
            user_id = int(target)
            # 只有user_id，需要从数据库获取其他信息
            return (user_id, None, "")

        return None

    @staticmethod
    def resolve_with_db(update: Update, args: list[str], session: Session, group_id: int) -> Optional[Tuple[int, Optional[str], str]]:
        """
        带数据库查询的用户解析（推荐使用）
        自动处理@username查询和ID补全

        返回: (user_id, username, full_name) 或 None
        """
        user_info = UserResolver.resolve(update, args, session, group_id)

        if not user_info:
            return None

        user_id, username, full_name = user_info

        # 如果只有ID没有名字，从数据库补全
        if not full_name:
            from app.models import GroupMember
            statement = select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.user_id == user_id
            )
            member = session.exec(statement).first()
            if member:
                return (member.user_id, member.username, member.full_name)

        return user_info

    @staticmethod
    def _extract_user_info(user: User) -> Tuple[int, Optional[str], str]:
        """提取用户信息"""
        user_id = user.id
        username = user.username
        full_name = user.full_name or user.first_name or ""
        return (user_id, username, full_name)
