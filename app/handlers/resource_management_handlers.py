"""
资源管理面板

提供资源管理功能：
- 查看所有资源
- 删除资源（同时删除Telegram消息和数据库记录）
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from sqlmodel import Session, select, func, or_
from app.database.connection import engine
from app.models import Resource, Category, Tag, ResourceTag
from app.services.resource_service import ResourceService
from loguru import logger


async def manage_resources_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /manage_resources - 资源管理面板（仅管理员）
    显示所有资源，支持分页和删除
    """
    from app.handlers.commands import is_admin
    if not await is_admin(update):
        await update.message.reply_text("❌ 此命令仅限管理员使用")
        return
    
    with Session(engine) as session:
        # 获取资源总数
        total = session.exec(
            select(func.count(Resource.id))
            .where(Resource.group_id == update.effective_chat.id)
        ).one()
        
        if total == 0:
            await update.message.reply_text("📦 暂无资源")
            return
        
        # 获取前10个资源
        resources = session.exec(
            select(Resource)
            .where(Resource.group_id == update.effective_chat.id)
            .order_by(Resource.created_at.desc())
            .limit(10)
        ).all()
        
        text = f"📦 资源管理 (共 {total} 个)\n\n"
        keyboard = []
        
        for resource in resources:
            category = session.get(Category, resource.category_id) if resource.category_id else None
            
            # 资源信息
            title = resource.title[:30] + "..." if len(resource.title) > 30 else resource.title
            info = f"📁 {title}"
            if category:
                info += f" | 📂 {category.name}"
            
            text += f"{info}\n"
            text += f"   ID: {resource.id} | 上传者: @{resource.uploader_username or resource.uploader_first_name}\n\n"
            
            # 删除按钮
            keyboard.append([
                InlineKeyboardButton(f"🗑️ 删除 #{resource.id}", callback_data=f"mgmt_res_del_{resource.id}")
            ])
        
        # 分页按钮
        if total > 10:
            keyboard.append([
                InlineKeyboardButton("➡️ 下一页", callback_data="mgmt_res_page_1")
            ])
        
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def manage_resources_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理资源管理的回调"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # 分页
    if data.startswith("mgmt_res_page_"):
        page = int(data.split("_")[3])
        offset = page * 10
        
        with Session(engine) as session:
            total = session.exec(
                select(func.count(Resource.id))
                .where(Resource.group_id == update.effective_chat.id)
            ).one()
            
            resources = session.exec(
                select(Resource)
                .where(Resource.group_id == update.effective_chat.id)
                .order_by(Resource.created_at.desc())
                .offset(offset)
                .limit(10)
            ).all()
            
            text = f"📦 资源管理 (共 {total} 个) - 第 {page + 1} 页\n\n"
            keyboard = []
            
            for resource in resources:
                category = session.get(Category, resource.category_id) if resource.category_id else None
                
                title = resource.title[:30] + "..." if len(resource.title) > 30 else resource.title
                info = f"📁 {title}"
                if category:
                    info += f" | 📂 {category.name}"
                
                text += f"{info}\n"
                text += f"   ID: {resource.id} | 上传者: @{resource.uploader_username or resource.uploader_first_name}\n\n"
                
                keyboard.append([
                    InlineKeyboardButton(f"🗑️ 删除 #{resource.id}", callback_data=f"mgmt_res_del_{resource.id}")
                ])
            
            # 导航按钮
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"mgmt_res_page_{page - 1}"))
            if offset + 10 < total:
                nav_buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"mgmt_res_page_{page + 1}"))
            
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    # 删除确认
    elif data.startswith("mgmt_res_del_"):
        if "_confirm_" in data:
            # 执行删除
            resource_id = int(data.split("_")[4])
            
            with Session(engine) as session:
                resource = session.get(Resource, resource_id)
                if not resource:
                    await query.edit_message_text("❌ 资源不存在")
                    return
                
                title = resource.title
                message_id = resource.message_id
                
                # 1. 删除Telegram消息
                msg_deleted = False
                try:
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id,
                        message_id=message_id
                    )
                    msg_deleted = True
                    logger.info(f"Deleted Telegram message {message_id}")
                except Exception as e:
                    logger.warning(f"Failed to delete message {message_id}: {e}")
                
                # 2. 删除关联的标签（外键约束）
                try:
                    delete_tags = session.exec(
                        select(ResourceTag).where(ResourceTag.resource_id == resource_id)
                    ).all()
                    for tag_link in delete_tags:
                        session.delete(tag_link)
                    # 先flush标签删除，确保外键约束解除
                    session.flush()
                    logger.info(f"Deleted {len(delete_tags)} tag links for resource {resource_id}")
                except Exception as e:
                    logger.warning(f"Failed to delete tag links: {e}")
                
                # 3. 删除数据库记录
                session.delete(resource)
                session.commit()
                logger.info(f"Deleted resource {resource_id} from database")
                
                # 结果提示
                result_text = f"✅ 资源「{title}」已删除\n\n"
                if msg_deleted:
                    result_text += "📝 聊天记录已删除\n"
                    result_text += "💾 数据库记录已删除"
                else:
                    result_text += "⚠️ 聊天记录删除失败（可能已手动删除）\n"
                    result_text += "💾 数据库记录已删除"
                
                await query.edit_message_text(
                    result_text,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 返回资源管理", callback_data="mgmt_res_page_0")
                    ]])
                )
        else:
            # 显示删除确认
            resource_id = int(data.split("_")[3])
            
            with Session(engine) as session:
                resource = session.get(Resource, resource_id)
                if not resource:
                    await query.answer("资源不存在", show_alert=True)
                    return
                
                keyboard = [
                    [
                        InlineKeyboardButton("✅ 确认删除", callback_data=f"mgmt_res_del_confirm_{resource_id}"),
                        InlineKeyboardButton("❌ 取消", callback_data="mgmt_res_page_0")
                    ]
                ]
                
                await query.edit_message_text(
                    f"🗑️ 确定要删除资源吗？\n\n"
                    f"📁 {resource.title}\n"
                    f"🆔 ID: {resource.id}\n\n"
                    f"⚠️ 此操作将：\n"
                    f"1. 删除Telegram聊天记录中的原始消息\n"
                    f"2. 删除数据库中的资源记录\n"
                    f"3. 此操作不可撤销！",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
