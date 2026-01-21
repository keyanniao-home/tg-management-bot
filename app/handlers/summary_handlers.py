"""
消息总结命令处理器
"""

from datetime import datetime, timedelta, UTC, timezone
from typing import Optional
from telegram import Update
from telegram.ext import ContextTypes
from loguru import logger
from sqlmodel import Session, select, and_
from app.database.connection import engine
from app.models import GroupConfig, Message, MessageSummary, GroupMember
from app.services.llm_service import llm_service
from app.utils.message_utils import is_real_reply


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    消息总结命令: /kobe_summary [小时数]
    总结最近N小时的消息，默认从用户上次发言到现在
    """
    if not update.effective_user or not update.effective_chat or not update.message:
        return

    if not llm_service.is_enabled:
        await update.message.reply_text(
            "❌ LLM服务未配置，无法生成总结\n\n请联系管理员配置LLM_API_KEY"
        )
        return

    # 解析时间范围
    hours = None
    if context.args:
        try:
            hours = int(context.args[0])
            if hours <= 0 or hours > 168:  # 最多7天
                await update.message.reply_text("❌ 时间范围应在1-168小时之间")
                return
        except ValueError:
            await update.message.reply_text("❌ 无效的小时数")
            return

    status_msg = await update.message.reply_text("⏳ 正在生成总结，请稍候...")

    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()

        if not group or not group.is_initialized:
            await status_msg.edit_text("❌ 群组未初始化")
            return

        # 确定时间范围
        end_time = datetime.now(UTC)

        if hours:
            start_time = end_time - timedelta(hours=hours)
        else:
            # 从用户上次发言到现在
            statement = (
                select(GroupMember.last_message_at)
                .join(Message, Message.member_id == GroupMember.id)
                .where(
                    and_(
                        GroupMember.group_id == group.id,
                        GroupMember.user_id == update.effective_user.id,
                    )
                )
                .order_by(GroupMember.last_message_at.desc())
                .limit(1)
            )
            last_msg_time = session.exec(statement).first()

            if last_msg_time:
                start_time = last_msg_time
            else:
                # 默认24小时
                start_time = end_time - timedelta(hours=24)

        # 获取消息
        statement = (
            select(Message, GroupMember)
            .join(GroupMember, Message.member_id == GroupMember.id)
            .where(
                and_(
                    Message.group_id == group.id,
                    Message.created_at >= start_time,
                    Message.created_at <= end_time,
                    Message.message_type == "text",
                )
            )
            .order_by(Message.created_at)
        )

        results = session.exec(statement).all()

        if not results:
            await status_msg.edit_text("没有找到消息记录")
            return

        # 格式化消息
        messages_for_llm = []
        for msg, member in results:
            if msg.text:
                # 转换为北京时间 (UTC+8)
                msg_time_local = msg.created_at.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=8)))
                messages_for_llm.append(
                    {
                        "sender": member.full_name or member.username or "未知",
                        "text": msg.text[:500],  # 限制长度
                        "time": msg_time_local.strftime("%H:%M"),
                    }
                )

        # 生成总结
        # 转换为北京时间 (UTC+8)
        start_time_local = start_time.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=8)))
        end_time_local = end_time.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=8)))
        result = await llm_service.summarize_messages(
            messages_for_llm,
            context=f"时间范围: {start_time_local.strftime('%Y-%m-%d %H:%M')} 到 {end_time_local.strftime('%Y-%m-%d %H:%M')}",
        )

        if not result:
            await status_msg.edit_text("❌ 生成总结失败，请稍后重试")
            return

        # 保存总结
        summary_record = MessageSummary(
            group_id=group.id,
            summary_text=result["summary"],
            summary_type="manual",
            time_range_start=start_time,
            time_range_end=end_time,
            message_count=len(messages_for_llm),
            participant_count=len(set(m["sender"] for m in messages_for_llm)),
            generated_by_user_id=update.effective_user.id,
            llm_model=result.get("model"),
            tokens_used=result.get("tokens_used"),
        )
        session.add(summary_record)
        session.commit()

        # 发送总结
        summary_text = f"📊 消息总结\n\n"
        summary_text += f"⏰ 时间范围: {start_time_local.strftime('%m-%d %H:%M')} - {end_time_local.strftime('%m-%d %H:%M')}\n"
        summary_text += f"📝 消息数: {len(messages_for_llm)}\n"
        summary_text += (
            f"👥 参与者: {len(set(m['sender'] for m in messages_for_llm))} 人\n\n"
        )
        summary_text += result["summary"]

        await status_msg.edit_text(summary_text)


async def search_user_messages_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    搜索用户消息: /search_user <user_id/@username> [hours]
    搜索指定用户最近的消息
    支持：用户ID、@用户名、回复消息
    """
    if not update.effective_chat or not update.message:
        return

    # 如果没有参数且没有回复消息，显示帮助
    if not context.args and not is_real_reply(update.message):
        await update.message.reply_text(
            "📝 使用方法: /search_user <用户ID/@用户名> [小时数]\n\n"
            "示例:\n"
            "• /search_user 123456789 24\n"
            "• /search_user @username 48\n"
            "• 回复消息后发送 /search_user"
        )
        return

    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()

        if not group or not group.is_initialized:
            await update.message.reply_text("❌ 群组未初始化")
            return

        # 使用 UserResolver 解析用户（支持 ID、@username、回复消息）
        from app.utils.user_resolver import UserResolver

        user_info = UserResolver.resolve(update, context.args, session, group.id)

        if not user_info:
            await update.message.reply_text(
                "❌ 无法识别目标用户\n\n"
                "支持的格式:\n"
                "• 用户ID: /search_user 123456789\n"
                "• 用户名: /search_user @username\n"
                "• 回复消息后发送 /search_user"
            )
            return

        target_user_id, target_username, target_full_name = user_info

        # 解析小时数（第二个参数，如果第一个是@username则是第二个，否则也可能是第二个）
        hours = 24
        hours_arg = None
        if context.args:
            # 如果第一个参数是@username或纯数字用户ID，小时数在第二个参数
            if len(context.args) > 1:
                hours_arg = context.args[1]
            # 如果是回复消息，第一个参数可能是小时数
            elif (
                is_real_reply(update.message)
                and context.args[0].isdigit()
                and int(context.args[0]) <= 168
            ):
                hours_arg = context.args[0]

        if hours_arg:
            try:
                hours = int(hours_arg)
                if hours <= 0 or hours > 168:
                    await update.message.reply_text("❌ 时间范围应在1-168小时之间")
                    return
            except ValueError:
                pass

        # 查询消息
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(hours=hours)

        statement = (
            select(Message)
            .where(
                and_(
                    Message.group_id == group.id,
                    Message.user_id == target_user_id,
                    Message.created_at >= start_time,
                    Message.message_type == "text",
                )
            )
            .order_by(Message.created_at.desc())
            .limit(50)
        )

        messages = session.exec(statement).all()

        if not messages:
            await update.message.reply_text(
                f"未找到用户 {target_user_id} 在最近{hours}小时的消息"
            )
            return

        # 构建消息列表
        result_text = f"📝 用户 {target_user_id} 最近{hours}小时的消息 (最多50条):\n\n"

        for msg in messages[:20]:  # 限制显示数量
            # 转换为北京时间 (UTC+8)
            time_local = msg.created_at.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=8)))
            time_str = time_local.strftime("%m-%d %H:%M")
            text_preview = msg.text[:100] if msg.text else ""
            result_text += f"[{time_str}] {text_preview}\n\n"

        if len(messages) > 20:
            result_text += f"\n... 还有 {len(messages) - 20} 条消息未显示"

        await update.message.reply_text(result_text)


async def search_messages_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /search_messages [hours] - 查询时间段内的所有消息

    显示指定时间段内所有成员的消息统计和内容预览
    """
    if not update.effective_chat or not update.message:
        return

    hours = 24
    if context.args:
        try:
            hours = int(context.args[0])
            if hours <= 0 or hours > 168:
                await update.message.reply_text("❌ 时间范围应在1-168小时之间")
                return
        except ValueError:
            await update.message.reply_text(
                "❌ 无效的小时数\n\n"
                "用法: /search_messages [小时数]\n"
                "例如: /search_messages 24"
            )
            return

    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()

        if not group or not group.is_initialized:
            await update.message.reply_text("❌ 群组未初始化")
            return

        # 查询消息
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(hours=hours)

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
            .limit(100)
        )

        results = session.exec(statement).all()

        if not results:
            await update.message.reply_text(f"未找到最近{hours}小时的消息")
            return

        # 统计
        total_messages = len(results)
        participants = set(member.user_id for _, member in results)

        # 构建消息
        # 转换为北京时间 (UTC+8)
        start_time_local = start_time.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=8)))
        end_time_local = end_time.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=8)))
        text = f"📊 最近{hours}小时消息统计\n\n"
        text += f"⏰ 时间范围: {start_time_local.strftime('%m-%d %H:%M')} - {end_time_local.strftime('%m-%d %H:%M')}\n"
        text += f"📝 总消息数: {total_messages}\n"
        text += f"👥 参与人数: {len(participants)}\n\n"
        text += "━━━━━━━━━━━━━━━\n"
        text += "最近消息:\n\n"

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

        await update.message.reply_text(text)
