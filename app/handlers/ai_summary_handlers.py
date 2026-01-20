"""
AI总结可视化面板

提供交互式界面进行消息总结：
- 时间范围选择（1/6/12/24小时）
- 用户筛选（所有用户/特定用户）
- 一键执行总结
"""

from datetime import datetime, timedelta, UTC
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from sqlmodel import Session, select, and_
from app.database.connection import engine
from app.models import GroupConfig, Message, GroupMember
from app.services.llm_service import llm_service
from app.utils.auto_delete import auto_delete_message
from loguru import logger


SUMMARY_STATE_KEY = "ai_summary_state"


@auto_delete_message(delay=120)
async def ai_summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /ai_summary - AI消息总结面板

    显示可视化总结界面，支持时间范围和用户选择
    """
    if not update.message:
        return

    # 初始化总结状态
    context.user_data[SUMMARY_STATE_KEY] = {"hours": 24, "user_filter": "all"}

    keyboard = [
        [
            InlineKeyboardButton("1小时", callback_data="aisum_h_1"),
            InlineKeyboardButton("6小时", callback_data="aisum_h_6"),
            InlineKeyboardButton("12小时", callback_data="aisum_h_12"),
            InlineKeyboardButton("24小时✓", callback_data="aisum_h_24"),
        ],
        [
            InlineKeyboardButton("📊 所有成员✓", callback_data="aisum_user_all"),
            InlineKeyboardButton("👤 特定成员", callback_data="aisum_user_specific"),
        ],
        [InlineKeyboardButton("🤖 开始AI总结", callback_data="aisum_exec")],
    ]

    text = """🤖 AI消息总结

📅 时间范围: 24小时
👥 用户筛选: 所有成员

请选择条件后点击\"开始AI总结\"："""

    return await update.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def ai_summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理AI总结面板的回调"""
    query = update.callback_query
    await query.answer()

    data = query.data
    state = context.user_data.get(SUMMARY_STATE_KEY, {})

    if data.startswith("aisum_h_"):
        # 时间范围选择
        hours = int(data.split("_")[2])
        state["hours"] = hours
        context.user_data[SUMMARY_STATE_KEY] = state

        await update_summary_panel(query, state)

    elif data.startswith("aisum_user_"):
        # 用户筛选选择
        user_filter = data.split("_")[2]

        if user_filter == "specific":
            # 需要用户输入user_id
            await query.edit_message_text(
                "👤 请输入要总结的用户ID：\n\n(发送数字ID后会自动返回面板)"
            )
            context.user_data["waiting_summary_user_id"] = True
            return

        state["user_filter"] = user_filter
        if "user_id" in state:
            del state["user_id"]
        context.user_data[SUMMARY_STATE_KEY] = state

        await update_summary_panel(query, state)

    elif data == "aisum_exec":
        # 执行AI总结
        await execute_ai_summary(query, state, update.effective_chat.id)

    elif data == "aisum_back":
        # 返回总结面板
        await update_summary_panel(query, state)


async def update_summary_panel(query, state):
    """更新AI总结面板显示"""
    hours = state.get("hours", 24)
    user_filter = state.get("user_filter", "all")
    user_id = state.get("user_id")

    # 构建按钮
    keyboard = []

    # 时间范围按钮
    time_row = []
    for h in [1, 6, 12, 24]:
        label = f"{h}小时" + ("✓" if h == hours else "")
        time_row.append(InlineKeyboardButton(label, callback_data=f"aisum_h_{h}"))
    keyboard.append(time_row)

    # 用户筛选按钮
    user_row = [
        InlineKeyboardButton(
            "📊 所有成员" + ("✓" if user_filter == "all" else ""),
            callback_data="aisum_user_all",
        ),
        InlineKeyboardButton(
            "👤 特定成员" + ("✓" if user_filter == "specific" else ""),
            callback_data="aisum_user_specific",
        ),
    ]
    keyboard.append(user_row)

    # 执行按钮
    keyboard.append([InlineKeyboardButton("🤖 开始AI总结", callback_data="aisum_exec")])

    # 文本说明
    if user_filter == "specific" and user_id:
        user_text = f"用户 {user_id}"
    else:
        user_text = "所有成员"

    text = f"""🤖 AI消息总结

📅 时间范围: {hours}小时
👥 用户筛选: {user_text}

请选择条件后点击\"开始AI总结\"："""

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def execute_ai_summary(query, state, group_id):
    """执行AI总结"""
    hours = state.get("hours", 24)
    user_filter = state.get("user_filter", "all")
    user_id = state.get("user_id")

    # 检查LLM是否配置
    if not llm_service.is_enabled:
        keyboard = [[InlineKeyboardButton("🔙 返回面板", callback_data="aisum_back")]]
        await query.edit_message_text(
            "❌ LLM功能未配置\n请联系管理员配置LLM_API_KEY",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # 显示处理中
    await query.edit_message_text("🤖 AI正在分析消息，请稍候...")

    with Session(engine) as session:
        # 获取群组配置
        group_statement = select(GroupConfig).where(GroupConfig.group_id == group_id)
        group = session.exec(group_statement).first()

        if not group or not group.is_initialized:
            keyboard = [
                [InlineKeyboardButton("🔙 返回面板", callback_data="aisum_back")]
            ]
            await query.edit_message_text(
                "❌ 群组未初始化", reply_markup=InlineKeyboardMarkup(keyboard)
            )
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
            .order_by(Message.created_at)
        )

        # 如果是特定用户筛选
        if user_filter == "specific" and user_id:
            statement = statement.where(GroupMember.user_id == user_id)

        results = session.exec(statement).all()

        if not results:
            keyboard = [
                [InlineKeyboardButton("🔙 返回面板", callback_data="aisum_back")]
            ]
            await query.edit_message_text(
                f"未找到最近{hours}小时的消息",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        # 格式化消息
        formatted_messages = []
        for msg, member in results:
            formatted_messages.append(
                {
                    "sender": member.full_name or member.username or "未知用户",
                    "text": msg.text or "",
                    "time": msg.created_at.strftime("%H:%M"),
                }
            )

        # 调用LLM生成总结
        context_info = f"最近{hours}小时的群聊消息"
        if user_filter == "specific" and user_id:
            context_info += f"，仅统计用户{user_id}的发言"

        result = await llm_service.summarize_messages(
            messages=formatted_messages, context=context_info, max_tokens=1000
        )

        if not result:
            keyboard = [
                [InlineKeyboardButton("🔙 返回面板", callback_data="aisum_back")]
            ]
            await query.edit_message_text(
                "❌ AI总结生成失败\n请检查API配置或稍后重试",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        # 显示总结结果
        total_messages = len(results)
        participants = len(set(member.user_id for _, member in results))

        summary_text = f"""🤖 AI消息总结

⏰ 时间范围: {start_time.strftime("%m-%d %H:%M")} - {end_time.strftime("%m-%d %H:%M")}
📝 消息数量: {total_messages}
👥 参与人数: {participants}

━━━━━━━━━━━━━━━

{result["summary"]}

━━━━━━━━━━━━━━━

💡 使用了 {result.get("tokens_used", 0)} tokens
🤖 模型: {result.get("model", "unknown")}"""

        keyboard = [[InlineKeyboardButton("🔙 返回面板", callback_data="aisum_back")]]

        await query.edit_message_text(
            summary_text, reply_markup=InlineKeyboardMarkup(keyboard)
        )


@auto_delete_message(delay=120)
async def handle_summary_user_id_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """处理AI总结的用户ID输入"""
    if not context.user_data.get("waiting_summary_user_id"):
        return

    user_id_str = update.message.text.strip()

    # 验证是否是数字
    if not user_id_str.isdigit():
        return await update.message.reply_text("❌ 请输入有效的数字ID")

    user_id = int(user_id_str)

    # 清除等待状态
    context.user_data["waiting_summary_user_id"] = False

    # 更新总结状态
    state = context.user_data.get(SUMMARY_STATE_KEY, {})
    state["user_filter"] = "specific"
    state["user_id"] = user_id
    context.user_data[SUMMARY_STATE_KEY] = state

    # 显示面板
    hours = state.get("hours", 24)

    keyboard = []

    # 时间范围按钮
    time_row = []
    for h in [1, 6, 12, 24]:
        label = f"{h}小时" + ("✓" if h == hours else "")
        time_row.append(InlineKeyboardButton(label, callback_data=f"aisum_h_{h}"))
    keyboard.append(time_row)

    # 用户筛选按钮
    keyboard.append(
        [
            InlineKeyboardButton("📊 所有成员", callback_data="aisum_user_all"),
            InlineKeyboardButton("👤 特定成员✓", callback_data="aisum_user_specific"),
        ]
    )

    # 执行按钮
    keyboard.append([InlineKeyboardButton("🤖 开始AI总结", callback_data="aisum_exec")])

    text = f"""🤖 AI消息总结

📅 时间范围: {hours}小时
👥 用户筛选: 用户 {user_id}

✅ 已设置用户ID，点击\"开始AI总结\"："""

    return await update.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard)
    )
