"""
私信转达命令处理器
支持成员间通过Bot转发私信，并提供阅读回执功能
"""

from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode
from telegram.error import Forbidden
from sqlmodel import Session, select
from app.database.connection import engine
from app.models.dm_relay import DMRelay, DMReadReceipt
from app.utils.message_utils import is_real_reply
from loguru import logger


async def dm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /dm <user_id/@username> <消息内容> - 发送私信
    通过Bot转发消息给其他成员
    支持：用户ID、@用户名、回复消息
    """
    if not update.message:
        return

    # 如果没有参数，或者只有一个参数且不是回复消息
    has_reply = is_real_reply(update.message)

    if not context.args and not has_reply:
        await update.message.reply_text(
            "用法: /dm <用户ID/@用户名> <消息内容>\n"
            "例如:\n"
            "• /dm 123456789 你好，请问有空吗？\n"
            "• /dm @username 你好，请问有空吗？\n"
            "• 回复消息后发送 /dm 你好\n\n"
            "注意：接收者必须先私聊Bot发送 /start"
        )
        return

    # 使用 UserResolver 解析用户
    from app.utils.user_resolver import UserResolver
    from app.models.group import GroupConfig

    with Session(engine) as session:
        # 获取群组配置
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()
        group_id = group.id if group else None

        # 解析用户
        user_info = UserResolver.resolve(update, context.args, session, group_id)

        if not user_info:
            await update.message.reply_text(
                "❌ 无法识别目标用户\n\n"
                "支持的格式:\n"
                "• 用户ID: /dm 123456789 消息\n"
                "• 用户名: /dm @username 消息\n"
                "• 回复消息后发送 /dm 消息"
            )
            return

        target_user_id, target_username, target_full_name = user_info

    # 解析消息内容
    if has_reply and (
        not context.args or (len(context.args) == 1 and context.args[0].startswith("@"))
    ):
        # 回复消息 + 可能有@username但没消息内容
        if context.args and not context.args[0].startswith("@"):
            message_content = " ".join(context.args)
        elif len(context.args) > 1:
            message_content = " ".join(context.args[1:])
        else:
            await update.message.reply_text("❌ 请提供消息内容")
            return
    elif context.args:
        # 第一个参数是用户标识，后面是消息
        if context.args[0].startswith("@") or context.args[0].isdigit():
            if len(context.args) < 2:
                await update.message.reply_text("❌ 请提供消息内容")
                return
            message_content = " ".join(context.args[1:])
        else:
            # 回复消息时，所有参数都是消息内容
            message_content = " ".join(context.args)
    else:
        await update.message.reply_text("❌ 请提供消息内容")
        return

    # 检查是否自己给自己发消息
    if target_user_id == update.effective_user.id:
        await update.message.reply_text("❌ 不能给自己发送私信")
        return

    with Session(engine) as session:
        # 创建DM记录
        dm_relay = DMRelay(
            group_id=update.effective_chat.id,
            from_user_id=update.effective_user.id,
            from_username=update.effective_user.username,
            to_user_id=target_user_id,
            to_username=None,  # 我们可能不知道对方用户名
            message=message_content,
        )
        session.add(dm_relay)
        session.commit()
        session.refresh(dm_relay)

        # 尝试发送私信
        try:
            # 创建已读回执按钮
            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ 标记为已读", callback_data=f"dm_read_{dm_relay.id}"
                    )
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            dm_text = (
                f"📨 <b>来自 {update.effective_chat.title} 的私信</b>\n\n"
                f"发送者: {update.effective_user.mention_html()}\n"
                f"消息: {message_content}\n\n"
                f"<i>点击下方按钮确认已读</i>"
            )

            # 发送私信
            sent_message = await context.bot.send_message(
                chat_id=target_user_id,
                text=dm_text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )

            # 更新记录：已送达
            dm_relay.delivered = True
            dm_relay.delivered_at = datetime.utcnow()
            dm_relay.bot_message_id = sent_message.message_id
            session.add(dm_relay)
            session.commit()

            # 在群组中通知
            # 使用已解析的用户信息显示
            display_name = f"@{target_username}" if target_username else (f"{target_full_name}" if target_full_name else f"用户 {target_user_id}")
            
            notification_text = (
                f"✅ 私信已发送给 {display_name}\n等待对方确认阅读..."
            )

            notification_msg = await update.message.reply_text(
                notification_text, message_thread_id=update.message.message_thread_id
            )

            # 同时在主群艾特接收者
            mention_text = (
                f"💬 {display_name} "
                f"你有一条来自 {update.effective_user.mention_html()} 的私信，请查看Bot私聊"
            )
            await update.effective_chat.send_message(
                mention_text,
                parse_mode=ParseMode.HTML,
                message_thread_id=update.message.message_thread_id,
            )

            dm_relay.notification_message_id = notification_msg.message_id
            session.add(dm_relay)
            session.commit()

            logger.info(f"私信已发送: {update.effective_user.id} -> {target_user_id}")

        except Forbidden:
            # 用户未启动Bot
            display_name = f"@{target_username}" if target_username else (f"{target_full_name}" if target_full_name else f"用户 {target_user_id}")
            await update.message.reply_text(
                f"❌ 无法发送私信给 {display_name}\n"
                f"原因: 对方未启动Bot或已屏蔽Bot\n"
                f"请提醒对方先私聊Bot发送 /start"
            )

            # 标记为未送达
            dm_relay.delivered = False
            session.add(dm_relay)
            session.commit()

        except Exception as e:
            logger.error(f"发送私信失败: {e}")
            await update.message.reply_text(f"❌ 发送私信失败: {str(e)}")


async def dm_read_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理已读回执"""
    query = update.callback_query
    await query.answer("已标记为已读")

    # 解析DM ID
    dm_id = int(query.data.split("_")[2])

    with Session(engine) as session:
        dm_relay = session.get(DMRelay, dm_id)

        if not dm_relay:
            await query.edit_message_text("❌ 消息记录不存在")
            return

        # 检查是否是接收者本人
        if dm_relay.to_user_id != update.effective_user.id:
            await query.answer("❌ 只有接收者可以确认已读", show_alert=True)
            return

        # 更新已读状态
        dm_relay.read = True
        dm_relay.read_at = datetime.utcnow()
        session.add(dm_relay)

        # 创建已读回执记录
        receipt = DMReadReceipt(
            dm_relay_id=dm_relay.id, read_by=update.effective_user.id
        )
        session.add(receipt)
        session.commit()

        # 更新原消息显示已读
        await query.edit_message_text(
            f"{query.message.text_html}\n\n"
            f"✅ <b>已于 {dm_relay.read_at.strftime('%Y-%m-%d %H:%M')} 标记为已读</b>",
            parse_mode=ParseMode.HTML,
        )

        # 尝试通知发送者
        try:
            to_display = f"@{dm_relay.to_username}" if dm_relay.to_username else f"用户 {dm_relay.to_user_id}"
            await context.bot.send_message(
                chat_id=dm_relay.from_user_id,
                text=(
                    f"✅ 你发送给 {to_display} 的私信已被阅读\n"
                    f"已读时间: {dm_relay.read_at.strftime('%Y-%m-%d %H:%M:%S')}"
                ),
            )
        except:
            pass

        # 在群组更新通知消息
        try:
            if dm_relay.notification_message_id:
                to_display = f"@{dm_relay.to_username}" if dm_relay.to_username else f"用户 {dm_relay.to_user_id}"
                await context.bot.edit_message_text(
                    chat_id=dm_relay.group_id,
                    message_id=dm_relay.notification_message_id,
                    text=(
                        f"✅ 私信已送达并已读\n"
                        f"接收者: {to_display}\n"
                        f"已读时间: {dm_relay.read_at.strftime('%Y-%m-%d %H:%M')}"
                    ),
                )
        except:
            pass

        logger.info(f"私信已读: DM ID={dm_id}, 接收者={update.effective_user.id}")


async def my_dms_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /kobe_my_dms - 查看我的私信记录（发送和接收）
    """
    user_id = update.effective_user.id

    with Session(engine) as session:
        # 获取发送的私信
        sent_dms = session.exec(
            select(DMRelay)
            .where(DMRelay.from_user_id == user_id)
            .order_by(DMRelay.created_at.desc())
            .limit(10)
        ).all()

        # 获取接收的私信
        received_dms = session.exec(
            select(DMRelay)
            .where(DMRelay.to_user_id == user_id)
            .order_by(DMRelay.created_at.desc())
            .limit(10)
        ).all()

        text = "📬 <b>我的私信记录</b>\n\n"

        if sent_dms:
            text += "<b>📤 已发送:</b>\n"
            for dm in sent_dms:
                status = (
                    "✅已读"
                    if dm.read
                    else ("📨已送达" if dm.delivered else "❌未送达")
                )
                to_display = f"@{dm.to_username}" if dm.to_username else f"用户 {dm.to_user_id}"
                text += f"→ {to_display}: {dm.message[:30]}... [{status}]\n"
            text += "\n"

        if received_dms:
            text += "<b>📥 已接收:</b>\n"
            for dm in received_dms:
                status = "✅已读" if dm.read else "📬未读"
                from_display = f"@{dm.from_username}" if dm.from_username else f"用户 {dm.from_user_id}"
                text += f"← {from_display}: {dm.message[:30]}... [{status}]\n"

        if not sent_dms and not received_dms:
            text += "暂无私信记录"

        await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# 导出handlers列表供main.py使用
dm_handlers = [CallbackQueryHandler(dm_read_callback, pattern="^dm_read_")]
