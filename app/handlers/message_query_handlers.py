"""
消息查询可视化面板

提供交互式界面进行消息查询：
- 时间范围选择（1/6/12/24小时或自定义）
- 查询类型选择（所有消息/特定用户）
- 结果格式选择（简要/详细）
"""

from datetime import datetime, timedelta, UTC, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from sqlmodel import Session, select, and_
from app.database.connection import engine
from app.models import GroupConfig, Message, GroupMember
from app.utils.auto_delete import auto_delete_message
from app.utils.reply_handler_manager import reply_handler_manager
from loguru import logger


QUERY_STATE_KEY = "message_query_state"


@auto_delete_message(delay=120)
async def query_messages_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /query_messages - 消息查询面板

    显示可视化查询界面，支持时间范围和查询类型选择
    """
    if not update.message:
        return

    # 初始化查询状态
    context.user_data[QUERY_STATE_KEY] = {
        "hours": 24,
        "type": "all",
        "format": "summary",
    }

    keyboard = [
        [
            InlineKeyboardButton("1小时", callback_data="qmsg_h_1"),
            InlineKeyboardButton("6小时", callback_data="qmsg_h_6"),
            InlineKeyboardButton("12小时", callback_data="qmsg_h_12"),
            InlineKeyboardButton("24小时✓", callback_data="qmsg_h_24"),
        ],
        [
            InlineKeyboardButton("📊 所有消息✓", callback_data="qmsg_type_all"),
            InlineKeyboardButton("👤 特定用户", callback_data="qmsg_type_user"),
        ],
        [
            InlineKeyboardButton("📝 简要统计✓", callback_data="qmsg_fmt_summary"),
            InlineKeyboardButton("📄 详细内容", callback_data="qmsg_fmt_detail"),
        ],
        [InlineKeyboardButton("🔍 开始查询", callback_data="qmsg_exec")],
    ]

    text = """🔍 消息查询

📅 时间范围: 24小时
🎯 查询类型: 所有消息
📊 显示方式: 简要统计

请选择查询条件后点击"开始查询"："""

    return await update.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def query_messages_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理消息查询面板的回调"""
    query = update.callback_query
    await query.answer()

    data = query.data
    state = context.user_data.get(QUERY_STATE_KEY, {})

    if data.startswith("qmsg_h_"):
        # 时间范围选择
        hours = int(data.split("_")[2])
        state["hours"] = hours
        context.user_data[QUERY_STATE_KEY] = state

        # 更新界面
        await update_query_panel(query, state)

    elif data.startswith("qmsg_type_"):
        # 查询类型选择
        query_type = data.split("_")[2]

        if query_type == "user":
            # 需要用户输入user_id，编辑消息并注册回复处理器
            bot_msg = await query.edit_message_text(
                "👤 请回复此消息输入要查询的用户ID（数字ID）："
            )
            # 注册回复处理器
            reply_handler_manager.register(
                bot_message_id=bot_msg.message_id,
                chat_id=update.effective_chat.id,
                handler=handle_user_id_input,
                handler_name="query_user_id_input"
            )
            return

        state["type"] = query_type
        context.user_data[QUERY_STATE_KEY] = state

        await update_query_panel(query, state)

    elif data.startswith("qmsg_fmt_"):
        # 显示格式选择
        fmt = data.split("_")[2]
        state["format"] = fmt
        context.user_data[QUERY_STATE_KEY] = state

        await update_query_panel(query, state)

    elif data == "qmsg_exec":
        # 执行查询
        await execute_message_query(query, state, update.effective_chat.id)

    elif data == "qmsg_back":
        # 返回查询面板
        await update_query_panel(query, state)


async def update_query_panel(query, state):
    """更新查询面板显示"""
    hours = state.get("hours", 24)
    query_type = state.get("type", "all")
    fmt = state.get("format", "summary")

    # 构建按钮
    keyboard = []

    # 时间范围按钮
    time_row = []
    for h in [1, 6, 12, 24]:
        label = f"{h}小时" + ("✓" if h == hours else "")
        time_row.append(InlineKeyboardButton(label, callback_data=f"qmsg_h_{h}"))
    keyboard.append(time_row)

    # 查询类型按钮
    type_row = [
        InlineKeyboardButton(
            "📊 所有消息" + ("✓" if query_type == "all" else ""),
            callback_data="qmsg_type_all",
        ),
        InlineKeyboardButton(
            "👤 特定用户" + ("✓" if query_type == "user" else ""),
            callback_data="qmsg_type_user",
        ),
    ]
    keyboard.append(type_row)

    # 显示格式按钮
    fmt_row = [
        InlineKeyboardButton(
            "📝 简要统计" + ("✓" if fmt == "summary" else ""),
            callback_data="qmsg_fmt_summary",
        ),
        InlineKeyboardButton(
            "📄 详细内容" + ("✓" if fmt == "detail" else ""),
            callback_data="qmsg_fmt_detail",
        ),
    ]
    keyboard.append(fmt_row)

    # 执行按钮
    keyboard.append([InlineKeyboardButton("🔍 开始查询", callback_data="qmsg_exec")])

    # 文本说明
    type_text = (
        "所有消息" if query_type == "all" else f"用户 {state.get('user_id', '未指定')}"
    )
    fmt_text = "简要统计" if fmt == "summary" else "详细内容"

    text = f"""🔍 消息查询

📅 时间范围: {hours}小时
🎯 查询类型: {type_text}
📊 显示方式: {fmt_text}

请选择查询条件后点击"开始查询"："""

    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        # 忽略 "Message is not modified" 错误
        if "message is not modified" not in str(e).lower():
            raise


async def execute_message_query(query, state, group_id):
    """执行消息查询"""
    hours = state.get("hours", 24)
    query_type = state.get("type", "all")
    fmt = state.get("format", "summary")

    # 显示处理中
    await query.edit_message_text("🔍 正在查询...")

    with Session(engine) as session:
        # 获取群组配置
        group_statement = select(GroupConfig).where(GroupConfig.group_id == group_id)
        group = session.exec(group_statement).first()

        if not group or not group.is_initialized:
            await query.edit_message_text("❌ 群组未初始化")
            return

        # 计算时间范围
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(hours=hours)

        # 构建查询
        statement = (
            select(Message, GroupMember)
            .join(GroupMember, Message.member_id == GroupMember.id)
            .where(
                and_(
                    Message.group_id == group.id,
                    Message.created_at >= start_time,
                    Message.message_type == "text",
                )
            )
            .order_by(Message.created_at.desc())
        )

        # 如果是特定用户查询
        if query_type == "user" and state.get("user_id"):
            statement = statement.where(GroupMember.user_id == state["user_id"])

        results = session.exec(statement).all()

        if not results:
            await query.edit_message_text(f"未找到最近{hours}小时的消息")
            return

        # 统计数据
        total_messages = len(results)
        participants = set(member.user_id for _, member in results)

        if fmt == "summary":
            # 简要统计
            # 转换为北京时间 (UTC+8)
            start_time_local = start_time.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=8)))
            end_time_local = end_time.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=8)))
            text = f"""📊 查询结果（最近{hours}小时）

⏰ 时间范围: {start_time_local.strftime("%m-%d %H:%M")} - {end_time_local.strftime("%m-%d %H:%M")}
📝 总消息数: {total_messages}
👥 参与人数: {len(participants)}

💡 切换到"详细内容"可查看消息列表"""

        else:
            # 详细内容
            # 转换为北京时间 (UTC+8)
            start_time_local = start_time.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=8)))
            end_time_local = end_time.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=8)))
            text = f"""📄 查询结果（最近{hours}小时）

⏰ {start_time_local.strftime("%m-%d %H:%M")} - {end_time_local.strftime("%m-%d %H:%M")}
📝 总计 {total_messages} 条消息

━━━━━━━━━━━━━━━
最近消息:\n\n"""

            # 显示最近20条
            for msg, member in results[:20]:
                # 转换为北京时间 (UTC+8)
                time_local = msg.created_at.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=8)))
                time_str = time_local.strftime("%m-%d %H:%M")
                sender = member.full_name or member.username or "未知"
                text_preview = msg.text[:50] if msg.text else ""
                if len(msg.text or "") > 50:
                    text_preview += "..."
                text += f"[{time_str}] {sender}:\n{text_preview}\n\n"

            if total_messages > 20:
                text += f"... 还有 {total_messages - 20} 条消息未显示"

        # 添加返回按钮
        keyboard = [
            [InlineKeyboardButton("🔙 返回查询面板", callback_data="qmsg_back")]
        ]

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


@auto_delete_message(delay=120)
async def handle_user_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户ID输入（通过回复消息触发）"""
    user_id_str = update.message.text.strip()

    # 验证是否是数字
    if not user_id_str.isdigit():
        return await update.message.reply_text("❌ 请输入有效的数字ID")

    user_id = int(user_id_str)

    # 注销回复处理器（输入成功）
    if update.message.reply_to_message:
        reply_handler_manager.unregister(update.message.reply_to_message.message_id)

    # 更新查询状态
    state = context.user_data.get(QUERY_STATE_KEY, {})
    state["type"] = "user"
    state["user_id"] = user_id
    context.user_data[QUERY_STATE_KEY] = state

    # 显示查询面板
    keyboard = []
    hours = state.get("hours", 24)
    fmt = state.get("format", "summary")

    # 时间范围按钮
    time_row = []
    for h in [1, 6, 12, 24]:
        label = f"{h}小时" + ("✓" if h == hours else "")
        time_row.append(InlineKeyboardButton(label, callback_data=f"qmsg_h_{h}"))
    keyboard.append(time_row)

    # 查询类型按钮
    keyboard.append(
        [
            InlineKeyboardButton("📊 所有消息", callback_data="qmsg_type_all"),
            InlineKeyboardButton("👤 特定用户✓", callback_data="qmsg_type_user"),
        ]
    )

    # 显示格式按钮
    keyboard.append(
        [
            InlineKeyboardButton(
                "📝 简要统计" + ("✓" if fmt == "summary" else ""),
                callback_data="qmsg_fmt_summary",
            ),
            InlineKeyboardButton(
                "📄 详细内容" + ("✓" if fmt == "detail" else ""),
                callback_data="qmsg_fmt_detail",
            ),
        ]
    )

    # 执行按钮
    keyboard.append([InlineKeyboardButton("🔍 开始查询", callback_data="qmsg_exec")])

    text = f"""🔍 消息查询

📅 时间范围: {hours}小时
🎯 查询类型: 用户 {user_id}
📊 显示方式: {"简要统计" if fmt == "summary" else "详细内容"}

✅ 已设置用户ID，点击"开始查询"："""

    return await update.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard)
    )
