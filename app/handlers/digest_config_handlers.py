"""
每日推送配置面板

提供可视化界面配置每日推送：
- 推送时间选择
- 推送内容配置
- 启用/禁用推送
"""

from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlmodel import Session, select
from app.database.connection import engine
from app.models import DigestConfig
from app.utils.auto_delete import auto_delete_message
from loguru import logger


@auto_delete_message(delay=120)
async def digest_config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /digest_config - 每日推送配置

    显示可视化配置界面（仅管理员）
    """
    # 验证管理员权限
    from app.handlers.commands import is_admin

    if not await is_admin(update):
        return await update.message.reply_text("❌ 此命令仅限管理员使用")

    if not update.message:
        return

    with Session(engine) as session:
        config = get_or_create_digest_config(session, update.effective_chat.id)

        status = "✅ 已启用" if config.is_enabled else "❌ 已禁用"
        time_str = f"{config.push_hour:02d}:{config.push_minute:02d}"

        content_items = []
        if config.include_summary:
            content_items.append("消息总结")
        if config.include_stats:
            content_items.append("活跃统计")
        if config.include_hot_topics:
            content_items.append("热门话题")
        content_text = "、".join(content_items) if content_items else "无"

        text = f"""📅 每日推送配置

当前状态: {status}

📊 推送设置
• 推送时间: 每天 {time_str}
• 推送内容: {content_text}

💡 调整配置后将在下次定时任务时生效"""

        keyboard = [
            [InlineKeyboardButton("⏰ 修改推送时间", callback_data="digest_time")],
            [InlineKeyboardButton("📝 修改推送内容", callback_data="digest_content")],
            [
                InlineKeyboardButton(
                    "❌ 禁用推送" if config.is_enabled else "✅ 启用推送",
                    callback_data="digest_toggle",
                )
            ],
            [InlineKeyboardButton("🔄 刷新配置", callback_data="digest_refresh")],
        ]

        return await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def digest_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理每日推送配置的回调"""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "digest_time":
        # 显示时间选择
        await show_time_selection(query)

    elif data == "digest_content":
        # 显示内容选择
        await show_content_selection(query, update.effective_chat.id)

    elif data == "digest_toggle":
        # 切换启用状态
        await toggle_digest_status(query, update.effective_chat.id)

    elif data == "digest_refresh":
        # 刷新显示
        await refresh_digest_config(query, update.effective_chat.id)

    elif data.startswith("digest_t_"):
        # 设置推送时间
        parts = data.split("_")
        hour = int(parts[2])
        minute = int(parts[3])
        await set_push_time(query, update.effective_chat.id, hour, minute)

    elif data.startswith("digest_c_"):
        # 切换内容选项
        content_type = data.split("_")[2]
        await toggle_content_option(query, update.effective_chat.id, content_type)

    elif data == "digest_back":
        # 返回主面板
        await refresh_digest_config(query, update.effective_chat.id)


async def show_time_selection(query):
    """显示时间选择面板"""
    keyboard = [
        [
            InlineKeyboardButton("06:00", callback_data="digest_t_6_0"),
            InlineKeyboardButton("07:00", callback_data="digest_t_7_0"),
            InlineKeyboardButton("08:00", callback_data="digest_t_8_0"),
        ],
        [
            InlineKeyboardButton("09:00", callback_data="digest_t_9_0"),
            InlineKeyboardButton("10:00", callback_data="digest_t_10_0"),
            InlineKeyboardButton("12:00", callback_data="digest_t_12_0"),
        ],
        [
            InlineKeyboardButton("18:00", callback_data="digest_t_18_0"),
            InlineKeyboardButton("20:00", callback_data="digest_t_20_0"),
            InlineKeyboardButton("21:00", callback_data="digest_t_21_0"),
        ],
        [InlineKeyboardButton("🔙 返回", callback_data="digest_back")],
    ]

    await query.edit_message_text(
        "⏰ 选择推送时间：", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_content_selection(query, group_id):
    """显示内容选择面板"""
    with Session(engine) as session:
        config = get_or_create_digest_config(session, group_id)

        keyboard = [
            [
                InlineKeyboardButton(
                    ("✅" if config.include_summary else "☐") + " 消息总结",
                    callback_data="digest_c_summary",
                )
            ],
            [
                InlineKeyboardButton(
                    ("✅" if config.include_stats else "☐") + " 活跃统计",
                    callback_data="digest_c_stats",
                )
            ],
            [
                InlineKeyboardButton(
                    ("✅" if config.include_hot_topics else "☐") + " 热门话题",
                    callback_data="digest_c_topics",
                )
            ],
            [InlineKeyboardButton("🔙 返回", callback_data="digest_back")],
        ]

        await query.edit_message_text(
            "📝 选择推送内容（可多选）：", reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def toggle_digest_status(query, group_id):
    """切换推送启用状态"""
    with Session(engine) as session:
        config = get_or_create_digest_config(session, group_id)
        config.is_enabled = not config.is_enabled
        session.add(config)
        session.commit()

        status = "启用" if config.is_enabled else "禁用"
        await query.answer(f"✅ 已{status}每日推送")

        await refresh_digest_config(query, group_id)


async def set_push_time(query, group_id, hour, minute):
    """设置推送时间"""
    with Session(engine) as session:
        config = get_or_create_digest_config(session, group_id)
        config.push_hour = hour
        config.push_minute = minute
        session.add(config)
        session.commit()

        await query.answer(f"✅ 推送时间已更新为 {hour:02d}:{minute:02d}")

        await refresh_digest_config(query, group_id)


async def toggle_content_option(query, group_id, content_type):
    """切换内容选项"""
    with Session(engine) as session:
        config = get_or_create_digest_config(session, group_id)

        if content_type == "summary":
            config.include_summary = not config.include_summary
        elif content_type == "stats":
            config.include_stats = not config.include_stats
        elif content_type == "topics":
            config.include_hot_topics = not config.include_hot_topics

        session.add(config)
        session.commit()

        await query.answer("✅ 已更新")

        # 刷新内容选择面板
        await show_content_selection(query, group_id)


async def refresh_digest_config(query, group_id):
    """刷新配置显示"""
    with Session(engine) as session:
        config = get_or_create_digest_config(session, group_id)

        status = "✅ 已启用" if config.is_enabled else "❌ 已禁用"
        time_str = f"{config.push_hour:02d}:{config.push_minute:02d}"

        content_items = []
        if config.include_summary:
            content_items.append("消息总结")
        if config.include_stats:
            content_items.append("活跃统计")
        if config.include_hot_topics:
            content_items.append("热门话题")
        content_text = "、".join(content_items) if content_items else "无"

        text = f"""📅 每日推送配置

当前状态: {status}

📊 推送设置
• 推送时间: 每天 {time_str}
• 推送内容: {content_text}

💡 调整配置后将在下次定时任务时生效"""

        keyboard = [
            [InlineKeyboardButton("⏰ 修改推送时间", callback_data="digest_time")],
            [InlineKeyboardButton("📝 修改推送内容", callback_data="digest_content")],
            [
                InlineKeyboardButton(
                    "❌ 禁用推送" if config.is_enabled else "✅ 启用推送",
                    callback_data="digest_toggle",
                )
            ],
            [InlineKeyboardButton("🔄 刷新配置", callback_data="digest_refresh")],
        ]

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


def get_or_create_digest_config(session: Session, group_id: int) -> DigestConfig:
    """获取或创建推送配置"""
    statement = select(DigestConfig).where(DigestConfig.group_id == group_id)
    config = session.exec(statement).first()

    if not config:
        config = DigestConfig(
            group_id=group_id,
            is_enabled=True,
            push_hour=9,
            push_minute=0,
            include_summary=True,
            include_stats=True,
            include_hot_topics=False,
        )
        session.add(config)
        session.commit()
        session.refresh(config)

    return config
