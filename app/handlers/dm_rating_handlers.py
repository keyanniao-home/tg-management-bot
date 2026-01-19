"""
DM 榜单命令处理器
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from sqlmodel import Session
from app.database.connection import engine
from app.services.dm_detection_service import DMDetectionService


async def dm_rating_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /dm_rating - 显示 DM 榜单
    列出每个 dm 次数非0的成员
    """
    if not update.message or not update.effective_chat:
        return
    
    page = 0
    if context.args:
        try:
            page = max(0, int(context.args[0]) - 1)
        except ValueError:
            pass
    
    await show_dm_ranking(update, context, page)


async def show_dm_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    """显示 DM 榜单"""
    group_id = update.effective_chat.id
    limit = 10
    offset = page * limit
    
    with Session(engine) as session:
        rankings, total = DMDetectionService.get_ranking(
            session=session,
            group_id=group_id,
            limit=limit,
            offset=offset
        )
        
        if not rankings and page == 0:
            await update.message.reply_text("📊 暂无 DM 记录")
            return
        
        if not rankings:
            await update.message.reply_text("❌ 没有更多数据了")
            return
        
        # 构建榜单文本
        total_pages = (total + limit - 1) // limit
        text = f"📊 <b>DM 榜单</b> (第 {page + 1}/{total_pages} 页)\n\n"
        
        for i, record in enumerate(rankings):
            rank = offset + i + 1
            # 用户显示名称
            if record.username:
                user_display = f"@{record.username}"
            elif record.full_name:
                user_display = record.full_name
            else:
                user_display = f"用户{record.user_id}"
            
            # 排名图标
            if rank == 1:
                rank_icon = "🥇"
            elif rank == 2:
                rank_icon = "🥈"
            elif rank == 3:
                rank_icon = "🥉"
            else:
                rank_icon = f"{rank}."
            
            text += f"{rank_icon} {user_display}\n"
            text += f"    ID: <code>{record.user_id}</code> | 次数: <b>{record.dm_count}</b>\n\n"
        
        # 翻页按钮
        keyboard = []
        nav_buttons = []
        
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton("⬅️ 上一页", callback_data=f"dm_rank_{page - 1}")
            )
        
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton("下一页 ➡️", callback_data=f"dm_rank_{page + 1}")
            )
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )


async def dm_rating_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 DM 榜单翻页回调"""
    query = update.callback_query
    await query.answer()
    
    # 解析页码
    page = int(query.data.split("_")[2])
    group_id = update.effective_chat.id
    limit = 10
    offset = page * limit
    
    with Session(engine) as session:
        rankings, total = DMDetectionService.get_ranking(
            session=session,
            group_id=group_id,
            limit=limit,
            offset=offset
        )
        
        if not rankings:
            await query.edit_message_text("❌ 没有更多数据了")
            return
        
        # 构建榜单文本
        total_pages = (total + limit - 1) // limit
        text = f"📊 <b>DM 榜单</b> (第 {page + 1}/{total_pages} 页)\n\n"
        
        for i, record in enumerate(rankings):
            rank = offset + i + 1
            if record.username:
                user_display = f"@{record.username}"
            elif record.full_name:
                user_display = record.full_name
            else:
                user_display = f"用户{record.user_id}"
            
            if rank == 1:
                rank_icon = "🥇"
            elif rank == 2:
                rank_icon = "🥈"
            elif rank == 3:
                rank_icon = "🥉"
            else:
                rank_icon = f"{rank}."
            
            text += f"{rank_icon} {user_display}\n"
            text += f"    ID: <code>{record.user_id}</code> | 次数: <b>{record.dm_count}</b>\n\n"
        
        # 翻页按钮
        keyboard = []
        nav_buttons = []
        
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton("⬅️ 上一页", callback_data=f"dm_rank_{page - 1}")
            )
        
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton("下一页 ➡️", callback_data=f"dm_rank_{page + 1}")
            )
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )

