from datetime import timedelta, UTC, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown
from sqlmodel import Session, select
from sqlalchemy import text
from app.database.connection import engine
from app.models import GroupConfig, GroupAdmin, ChannelBinding
from app.database.views import QUERY_MESSAGE_STATS_BY_DAYS, QUERY_INACTIVE_USERS, QUERY_CHANNEL_ACTIVE
from app.handlers.commands import is_admin
from app.utils.auto_delete import auto_delete_message
from collections import OrderedDict
from typing import List, Tuple
from datetime import datetime
import uuid


def escape_text(text: str) -> str:
    """转义 MarkdownV2 中的所有特殊字符"""
    return escape_markdown(str(text), version=2)


class LRUCache:
    """LRU缓存，用于缓存stats查询结果"""
    def __init__(self, capacity: int = 100):
        self.cache = OrderedDict()
        self.capacity = capacity

    def get(self, key: str) -> List[Tuple] | None:
        """获取缓存，如果存在则移到最后（最近使用）"""
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key: str, value: List[Tuple]):
        """设置缓存，如果超出容量则移除最旧的"""
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)


# 全局缓存实例
stats_cache = LRUCache(capacity=100)


@auto_delete_message(delay=30, custom_delays={'stats': 120, 'inactive': 240})
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /stats [天数]
    查询指定天数内的发言统计，按发言数排序
    """
    args = context.args
    days = 7  # 默认7天
    page = 1  # 默认第1页

    if args and args[0].isdigit():
        days = int(args[0])

    return await _show_stats_page(update.message, update.effective_chat.id, days, page)


async def _show_stats_page(message, chat_id: int, days: int, page: int):
    """显示统计页面（真分页查询）"""
    page_size = 10

    with Session(engine) as session:
        # 获取群组配置
        statement = select(GroupConfig).where(GroupConfig.group_id == chat_id)
        group = session.exec(statement).first()

        if not group:
            return await message.reply_text("群组未初始化")

        # 获取显示模式配置
        display_mode = group.config.get('stats_display_mode', 'mention')

        # 先查询总数
        count_query = """
        SELECT COUNT(*)
        FROM group_members gm
        LEFT JOIN messages m
            ON gm.id = m.member_id
            AND m.is_deleted = false
            AND m.created_at >= NOW() - :days * INTERVAL '1 day'
        WHERE gm.group_id = :group_id
            AND gm.is_active = true
        GROUP BY gm.user_id, gm.username, gm.full_name
        """
        count_result = session.execute(text(count_query), {"group_id": group.id, "days": days})
        total_count = len(count_result.all())

        if total_count == 0:
            return await message.reply_text(f"近{days}天内无发言记录")

        # 计算总页数
        total_pages = (total_count + page_size - 1) // page_size
        page = min(max(page, 1), total_pages)  # 限制页码范围

        # 真分页查询当前页数据
        offset = (page - 1) * page_size
        result = session.execute(
            text(QUERY_MESSAGE_STATS_BY_DAYS),
            {
                "group_id": group.id,
                "days": days,
                "limit": page_size,
                "offset": offset
            }
        )
        stats = result.all()

        # 格式化输出
        text_message = f"📊 近{days}天发言统计（第{page}/{total_pages}页，共{total_count}人）\n\n"
        for i, (user_id, username, full_name, msg_count, last_msg_at) in enumerate(stats, start=offset + 1):
            # 根据配置选择显示模式
            if display_mode == 'name_id':
                # 名字+ID模式 - 需要转义
                escaped_name = escape_text(full_name)
                escaped_id = escape_text(user_id)
                user_display = f"{escaped_name} \\(ID: {escaped_id}\\)"
            elif display_mode == 'name':
                # 只显示名字模式 - 需要转义
                user_display = escape_text(full_name)
            else:
                # mention模式（默认）
                if user_id < 0:  # 频道ID是负数
                    if username:
                        user_display = f"@{escape_text(username)}"
                    else:
                        user_display = escape_text(full_name)
                else:
                    escaped_name = escape_text(full_name)
                    user_display = f"[{escaped_name}](tg://user?id={user_id})"

            text_message += f"{i}\\. {user_display}\n"
            # 转换为东八区时间
            if last_msg_at:
                last_msg_at_local = last_msg_at.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=8)))
                last_msg_str = escape_text(last_msg_at_local.strftime('%Y-%m-%d %H:%M'))
            else:
                last_msg_str = '无'
            escaped_count = escape_text(msg_count)
            text_message += f"   发言: {escaped_count}次 \\| 最后: {last_msg_str}\n\n"

        # 创建分页按钮 - 使用 days 参数保持查询条件
        keyboard = []
        buttons = []
        if page > 1:
            buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"stats:{days}:{page-1}"))
        if page < total_pages:
            buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"stats:{days}:{page+1}"))

        if buttons:
            keyboard.append(buttons)

        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        return await message.reply_text(text_message, reply_markup=reply_markup, parse_mode="MarkdownV2")


async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理统计分页回调"""
    query = update.callback_query
    await query.answer()

    # 解析回调数据: stats:days:page
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.edit_message_text("数据格式错误")
        return

    _, days_str, page_str = parts
    days = int(days_str)
    page = int(page_str)

    # 重新查询数据（真分页）
    await _show_stats_page_edit(query, update.effective_chat.id, days, page)


async def _show_stats_page_edit(query, chat_id: int, days: int, page: int):
    """显示统计页面（编辑消息版本）"""
    page_size = 10

    with Session(engine) as session:
        # 获取群组配置
        statement = select(GroupConfig).where(GroupConfig.group_id == chat_id)
        group = session.exec(statement).first()

        if not group:
            await query.edit_message_text("群组未初始化")
            return

        # 获取显示模式配置
        display_mode = group.config.get('stats_display_mode', 'mention')

        # 先查询总数
        count_query = """
        SELECT COUNT(*)
        FROM group_members gm
        LEFT JOIN messages m
            ON gm.id = m.member_id
            AND m.is_deleted = false
            AND m.created_at >= NOW() - :days * INTERVAL '1 day'
        WHERE gm.group_id = :group_id
            AND gm.is_active = true
        GROUP BY gm.user_id, gm.username, gm.full_name
        """
        count_result = session.execute(text(count_query), {"group_id": group.id, "days": days})
        total_count = len(count_result.all())

        if total_count == 0:
            await query.edit_message_text(f"近{days}天内无发言记录")
            return

        # 计算总页数
        total_pages = (total_count + page_size - 1) // page_size
        page = min(max(page, 1), total_pages)

        # 真分页查询当前页数据
        offset = (page - 1) * page_size
        result = session.execute(
            text(QUERY_MESSAGE_STATS_BY_DAYS),
            {
                "group_id": group.id,
                "days": days,
                "limit": page_size,
                "offset": offset
            }
        )
        stats = result.all()

        # 格式化输出
        text_message = f"📊 近{days}天发言统计（第{page}/{total_pages}页，共{total_count}人）\n\n"
        for i, (user_id, username, full_name, msg_count, last_msg_at) in enumerate(stats, start=offset + 1):
            # 根据配置选择显示模式
            if display_mode == 'name_id':
                # 名字+ID模式 - 需要转义
                escaped_name = escape_text(full_name)
                escaped_id = escape_text(user_id)
                user_display = f"{escaped_name} \\(ID: {escaped_id}\\)"
            elif display_mode == 'name':
                # 只显示名字模式 - 需要转义
                user_display = escape_text(full_name)
            else:
                # mention模式（默认）
                if user_id < 0:  # 频道ID是负数
                    if username:
                        user_display = f"@{escape_text(username)}"
                    else:
                        user_display = escape_text(full_name)
                else:
                    escaped_name = escape_text(full_name)
                    user_display = f"[{escaped_name}](tg://user?id={user_id})"

            text_message += f"{i}\\. {user_display}\n"
            # 转换为东八区时间
            if last_msg_at:
                last_msg_at_local = last_msg_at.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=8)))
                last_msg_str = escape_text(last_msg_at_local.strftime('%Y-%m-%d %H:%M'))
            else:
                last_msg_str = '无'
            escaped_count = escape_text(msg_count)
            text_message += f"   发言: {escaped_count}次 \\| 最后: {last_msg_str}\n\n"

        # 创建分页按钮
        keyboard = []
        buttons = []
        if page > 1:
            buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"stats:{days}:{page-1}"))
        if page < total_pages:
            buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"stats:{days}:{page+1}"))

        if buttons:
            keyboard.append(buttons)

        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        await query.edit_message_text(text_message, reply_markup=reply_markup, parse_mode="MarkdownV2")


@auto_delete_message(delay=30, custom_delays={'stats': 120, 'inactive': 240})
async def inactive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /inactive [天数]
    查询指定天数内未发言的用户，分页显示
    """
    if not await is_admin(update):
        return None

    args = context.args
    days = 30  # 默认30天
    page = 1  # 默认第1页

    if args and args[0].isdigit():
        days = int(args[0])

    return await _show_inactive_page(update.message, update.effective_chat.id, days, page, context)


async def _show_inactive_page(message, chat_id: int, days: int, page: int, context):
    """显示未发言用户分页"""
    page_size = 10

    with Session(engine) as session:
        # 获取群组配置
        statement = select(GroupConfig).where(GroupConfig.group_id == chat_id)
        group = session.exec(statement).first()

        if not group:
            return await message.reply_text("群组未初始化")

        # 获取显示模式配置
        display_mode = group.config.get('inactive_display_mode', 'mention')


        # 查询未发言用户
        from app.config.settings import settings

        # 获取需要排除的ID：管理员 + 群组白名单 + 全局白名单
        statement = select(GroupAdmin).where(
            GroupAdmin.group_id == group.id,
            GroupAdmin.is_active == True
        )
        admin_ids = [admin.user_id for admin in session.exec(statement).all()]

        excluded_ids = set(admin_ids + group.whitelist + settings.global_whitelist_ids)

        result = session.execute(
            text(QUERY_INACTIVE_USERS),
            {"group_id": group.id, "days": days}
        )
        all_inactive = result.all()

        # 过滤掉白名单和管理员，并检查频道活跃状态
        inactive_users = []
        for uid, uname, fname, last_msg in all_inactive:
            if uid in excluded_ids:
                continue

            # 查询该用户绑定的频道（全局共享）
            statement = select(ChannelBinding).where(
                ChannelBinding.user_id == uid
            )
            bindings = session.exec(statement).all()

            # 检查绑定的频道是否活跃
            has_active_channel = False
            for binding in bindings:
                channel_result = session.execute(
                    text(QUERY_CHANNEL_ACTIVE),
                    {"group_id": group.id, "channel_id": binding.channel_id, "days": days}
                ).first()

                if channel_result and channel_result[2]:  # is_active
                    has_active_channel = True
                    break

            # 如果用户不活跃但有活跃频道，则豁免
            if not has_active_channel:
                inactive_users.append((uid, uname, fname, last_msg))

        if not inactive_users:
            return await message.reply_text(f"近{days}天内所有用户都有发言（含频道豁免）")


        # 生成UUID作为缓存key
        cache_key = str(uuid.uuid4())
        # 存入缓存
        stats_cache.put(cache_key, inactive_users)

        # 计算分页
        total_count = len(inactive_users)
        total_pages = (total_count + page_size - 1) // page_size
        page = min(page, total_pages)

        offset = (page - 1) * page_size
        page_users = inactive_users[offset:offset + page_size]

        # 格式化输出
        text_message = f"😴 近{days}天内未发言用户（共{total_count}人，第{page}/{total_pages}页）\n\n"
        for i, (user_id, username, full_name, last_msg_at) in enumerate(page_users, start=offset + 1):
            # 根据配置选择显示模式
            if display_mode == 'name_id':
                # 名字+ID模式 - 需要转义
                escaped_name = escape_text(full_name)
                escaped_id = escape_text(user_id)
                user_display = f"{escaped_name} \\(ID: {escaped_id}\\)"
            elif display_mode == 'name':
                # 只显示名字模式 - 需要转义
                user_display = escape_text(full_name)
            else:
                # mention模式（默认）
                if user_id < 0:
                    if username:
                        user_display = f"@{escape_text(username)}"
                    else:
                        user_display = escape_text(full_name)
                else:
                    escaped_name = escape_text(full_name)
                    user_display = f"[{escaped_name}](tg://user?id={user_id})"

            text_message += f"{i}\\. {user_display}\n"
            # 转换为东八区时间
            if last_msg_at:
                last_msg_at_local = last_msg_at.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=8)))
                last_msg_str = escape_text(last_msg_at_local.strftime('%Y-%m-%d'))
            else:
                last_msg_str = "从未发言"
            text_message += f"   最后发言: {last_msg_str}\n\n"

        # 在第一页添加确认提示
        if page == 1:
            text_message += "\n⚠️ 如需批量踢出这些用户，请回复此消息并输入「确认」"

        # 创建分页按钮
        keyboard = []
        buttons = []
        if page > 1:
            buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"inactive:{cache_key}:{page-1}"))
        if page < total_pages:
            buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"inactive:{cache_key}:{page+1}"))

        if buttons:
            keyboard.append(buttons)

        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        sent_message = await message.reply_text(text_message, reply_markup=reply_markup, parse_mode="MarkdownV2")

        # 在第一页时，存储待踢出用户信息到 bot_data（用于确认回复）
        if page == 1:
            if 'pending_kick' not in context.bot_data:
                context.bot_data['pending_kick'] = {}

            context.bot_data['pending_kick'][sent_message.message_id] = {
                'group_id': chat_id,
                'users': [(uid, uname, fname) for uid, uname, fname, _ in inactive_users]
            }

        return sent_message


async def inactive_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理未发言用户分页回调"""
    query = update.callback_query
    await query.answer()

    # 解析回调数据: inactive:cache_key:page
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.edit_message_text("数据格式错误")
        return

    _, cache_key, page_str = parts
    page = int(page_str)

    page_size = 10

    # 从缓存获取数据
    inactive_users = stats_cache.get(cache_key)

    if inactive_users is None:
        # 缓存未命中，提示用户重新查询
        await query.edit_message_text("⚠️ 数据已过期，请重新执行 /inactive 命令")
        return

    # 获取显示模式配置
    with Session(engine) as session:
        statement = select(GroupConfig).where(GroupConfig.group_id == update.effective_chat.id)
        group = session.exec(statement).first()

        if not group:
            await query.edit_message_text("群组未初始化")
            return

        display_mode = group.config.get('inactive_display_mode', 'mention')

    # 计算分页
    total_count = len(inactive_users)
    total_pages = (total_count + page_size - 1) // page_size
    page = min(page, total_pages)

    offset = (page - 1) * page_size
    page_users = inactive_users[offset:offset + page_size]

    # 格式化输出
    text_message = f"😴 未发言用户（共{total_count}人，第{page}/{total_pages}页）\n\n"
    for i, (user_id, username, full_name, last_msg_at) in enumerate(page_users, start=offset + 1):
        # 根据配置选择显示模式
        if display_mode == 'name_id':
            # 名字+ID模式 - 需要转义
            escaped_name = escape_markdown(full_name, version=2)
            user_display = f"{escaped_name} \\(ID: {user_id}\\)"
        elif display_mode == 'name':
            # 只显示名字模式 - 需要转义
            user_display = escape_markdown(full_name, version=2)
        else:
            # mention模式（默认）
            if user_id < 0:
                if username:
                    user_display = f"@{escape_markdown(username, version=2)}"
                else:
                    user_display = escape_markdown(full_name, version=2)
            else:
                escaped_name = escape_markdown(full_name, version=2)
                user_display = f"[{escaped_name}](tg://user?id={user_id})"

        text_message += f"{i}\\. {user_display}\n"
        # 转换为东八区时间
        if last_msg_at:
            last_msg_at_local = last_msg_at.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=8)))
            last_msg_str = escape_markdown(last_msg_at_local.strftime('%Y-%m-%d'), version=2)
        else:
            last_msg_str = "从未发言"
        text_message += f"   最后发言: {last_msg_str}\n\n"

    # 创建分页按钮
    keyboard = []
    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"inactive:{cache_key}:{page-1}"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"inactive:{cache_key}:{page+1}"))

    if buttons:
        keyboard.append(buttons)

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await query.edit_message_text(text_message, reply_markup=reply_markup, parse_mode="MarkdownV2")
