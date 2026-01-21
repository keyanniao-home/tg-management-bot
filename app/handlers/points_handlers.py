"""
积分与签到命令处理器
"""
from telegram import Update
from telegram.ext import ContextTypes
from loguru import logger
from sqlmodel import Session
from app.database.connection import engine
from app.models import GroupConfig, GroupMember, UserPoints
from app.services.points_service import points_service
from app.handlers.commands import is_admin
from app.utils.auto_delete import auto_delete_message


@auto_delete_message(delay=30)
async def checkin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """签到命令: /checkin"""
    if not update.effective_user or not update.effective_chat:
        return
    
    if not points_service.is_enabled():
        return await update.message.reply_text("❌ 积分系统未启用")
    
    with Session(engine) as session:
        # 检查群组是否初始化
        from sqlmodel import select
        statement = select(GroupConfig).where(GroupConfig.group_id == update.effective_chat.id)
        group = session.exec(statement).first()
        
        if not group or not group.is_initialized:
            return await update.message.reply_text("❌ 群组未初始化，请先使用 /init 命令")
        
        user = update.effective_user
        success, message, points = points_service.check_in(
            session,
            group.id,
            user.id,
            user.username,
            user.full_name or user.first_name
        )
        
        if success:
            return await update.message.reply_text(f"✅ {message}")
        else:
            return await update.message.reply_text(f"ℹ️ {message}")


@auto_delete_message(delay=30)
async def points_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看积分: /points [@用户]"""
    if not update.effective_chat:
        return
    
    if not points_service.is_enabled():
        return await update.message.reply_text("❌ 积分系统未启用")
    
    # 如果有参数且是管理员，可以查看其他人的积分
    target_user_id = update.effective_user.id if update.effective_user else None
    
    if context.args and await is_admin(update):
        # 尝试从@mention或user_id获取目标用户
        arg = context.args[0]
        try:
            if arg.startswith('@'):
                # TODO: 通过username查找user_id
                return await update.message.reply_text("暂不支持通过@用户名查询，请使用用户ID")
            else:
                target_user_id = int(arg)
        except ValueError:
            return await update.message.reply_text("❌ 无效的用户ID")
    
    if not target_user_id:
        return await update.message.reply_text("❌ 无法获取用户信息")
    
    with Session(engine) as session:
        from sqlmodel import select, and_
        statement = select(GroupConfig).where(GroupConfig.group_id == update.effective_chat.id)
        group = session.exec(statement).first()
        
        if not group or not group.is_initialized:
            return await update.message.reply_text("❌ 群组未初始化")
        
        # 获取积分
        user_points = points_service.get_or_create_user_points(session, group.id, target_user_id)
        
        # 获取用户信息
        statement = select(GroupMember).where(
            and_(
                GroupMember.group_id == group.id,
                GroupMember.user_id == target_user_id
            )
        )
        member = session.exec(statement).first()
        
        user_name = member.full_name if member else "未知用户"
        
        message = f"👤 {user_name}\n"
        message += f"💰 总积分: {user_points.total_points}\n"
        message += f"📅 今日消息积分: {user_points.message_points_today}/{points_service.POINTS_MESSAGE_DAILY_MAX}"
        
        return await update.message.reply_text(message)


async def points_rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """积分排行榜: /points_rank"""
    if not update.effective_chat:
        return
    
    if not points_service.is_enabled():
        await update.message.reply_text("❌ 积分系统未启用")
        return
    
    with Session(engine) as session:
        from sqlmodel import select
        statement = select(GroupConfig).where(GroupConfig.group_id == update.effective_chat.id)
        group = session.exec(statement).first()
        
        if not group or not group.is_initialized:
            return await update.message.reply_text("❌ 群组未初始化")
        
        # 获取排行榜
        rank_data = points_service.get_points_rank(session, group.id, limit=10)
        
        if not rank_data:
            await update.message.reply_text("暂无积分数据")
            return
        
        # 构建排行榜消息
        message = "🏆 积分排行榜 TOP 10\n\n"
        
        medals = ["🥇", "🥈", "🥉"]
        
        for user_id, points, rank in rank_data:
            # 获取用户信息
            from sqlmodel import and_
            statement = select(GroupMember).where(
                and_(
                    GroupMember.group_id == group.id,
                    GroupMember.user_id == user_id
                )
            )
            member = session.exec(statement).first()
            
            user_name = member.full_name if member else f"ID:{user_id}"
            medal = medals[rank - 1] if rank <= 3 else f"{rank}."
            
            message += f"{medal} {user_name}: {points} 分\n"
        
        await update.message.reply_text(message)


async def points_rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """积分规则说明: /points_rules"""
    rules_text = f"""
📖 积分系统规则

1️⃣ 发送消息
   • 每条消息 +{points_service.POINTS_MESSAGE} 分
   • 每日上限 {points_service.POINTS_MESSAGE_DAILY_MAX} 分

2️⃣ 上传资源
   • 每次上传 +{points_service.POINTS_UPLOAD} 分
   • 无上限

3️⃣ 评分资源
   • 每次评分 +{points_service.POINTS_RATING} 分

4️⃣ 每日签到
   • 基础奖励 {points_service.POINTS_CHECKIN_BASE} 分
   • 连续签到有额外加成
   • 例：连续3天签到可获得 {points_service.POINTS_CHECKIN_BASE + 2} 分

💡 使用 /checkin 签到
💡 使用 /points 查看积分
💡 使用 /points_rank 查看排行榜
"""
    
    await update.message.reply_text(rules_text)
