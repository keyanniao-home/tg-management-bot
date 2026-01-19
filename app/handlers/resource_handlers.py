"""
资源管理命令处理器
"""
from datetime import datetime, UTC
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram.constants import ParseMode
from loguru import logger
from sqlmodel import Session, select
from app.database.connection import engine
from app.models import Resource, Category, Tag, ResourceTag
from app.services.resource_service import ResourceService, CategoryService, TagService
from app.services.points_service import PointsService

SELECTING_CATEGORY, SELECTING_TAGS, ENTERING_DESCRIPTION, CREATING_CATEGORY, CREATING_TAG = range(5)
TEMP_RESOURCE_DATA = "temp_resource_data"


async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("请回复一个包含文件的消息，然后发送 /upload 命令")
        return ConversationHandler.END
    
    replied_message = update.message.reply_to_message
    file_id = None
    file_unique_id = None
    file_name = None
    file_size = None
    file_type = None
    
    if replied_message.document:
        file_type = "document"
        file_id = replied_message.document.file_id
        file_unique_id = replied_message.document.file_unique_id
        file_name = replied_message.document.file_name
        file_size = replied_message.document.file_size
    elif replied_message.photo:
        file_type = "photo"
        photo = replied_message.photo[-1]
        file_id = photo.file_id
        file_unique_id = photo.file_unique_id
        file_name = f"photo_{photo.file_unique_id}.jpg"
        file_size = photo.file_size
    elif replied_message.video:
        file_type = "video"
        file_id = replied_message.video.file_id
        file_unique_id = replied_message.video.file_unique_id
        file_name = replied_message.video.file_name or f"video_{replied_message.video.file_unique_id}.mp4"
        file_size = replied_message.video.file_size
    elif replied_message.audio:
        file_type = "audio"
        file_id = replied_message.audio.file_id
        file_unique_id = replied_message.audio.file_unique_id
        file_name = replied_message.audio.file_name or f"audio_{replied_message.audio.file_unique_id}.mp3"
        file_size = replied_message.audio.file_size
    elif replied_message.voice:
        file_type = "voice"
        file_id = replied_message.voice.file_id
        file_unique_id = replied_message.voice.file_unique_id
        file_name = f"voice_{replied_message.voice.file_unique_id}.ogg"
        file_size = replied_message.voice.file_size
    else:
        await update.message.reply_text("回复的消息不包含文件")
        return ConversationHandler.END
    
    context.user_data[TEMP_RESOURCE_DATA] = {
        "message_id": replied_message.message_id,
        "message_thread_id": replied_message.message_thread_id,
        "file_id": file_id,
        "file_unique_id": file_unique_id,
        "file_name": file_name,
        "file_size": file_size,
        "file_type": file_type,
        "selected_tags": []
    }
    
    with Session(engine) as session:
        categories = CategoryService.get_categories(session, update.effective_chat.id)
        
        if not categories:
            await update.message.reply_text("该群组还没有分类，请管理员先使用 /add_category 命令创建分类")
            return ConversationHandler.END
        
        keyboard = []
        for category in categories:
            keyboard.append([InlineKeyboardButton(f"📂 {category.name}", callback_data=f"cat_{category.id}")])
        
        # 添加新建分类按钮
        keyboard.append([InlineKeyboardButton("➕ 新建分类", callback_data="cat_new")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"📁 文件: {file_name}\n\n请选择分类：", reply_markup=reply_markup)
    
    return SELECTING_CATEGORY


async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # 处理新建分类
    if query.data == "cat_new":
        await query.edit_message_text("📂 请输入新分类的名称：")
        return CREATING_CATEGORY
    
    category_id = int(query.data.split("_")[1])
    context.user_data[TEMP_RESOURCE_DATA]["category_id"] = category_id
    
    with Session(engine) as session:
        tags = TagService.get_tags(session, update.effective_chat.id)
        
        if not tags:
            await query.edit_message_text("请输入资源描述（或发送 /cancel 取消）：")
            return ENTERING_DESCRIPTION
        
        keyboard = []
        row = []
        for i, tag in enumerate(tags):
            row.append(InlineKeyboardButton(f"🏷️ {tag.name}", callback_data=f"tag_{tag.id}"))
            if (i + 1) % 2 == 0:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        # 添加新建标签和跳过按钮
        keyboard.append([
            InlineKeyboardButton("➕ 新建标签", callback_data="tag_new"),
            InlineKeyboardButton("⏭️ 跳过标签", callback_data="tags_done")
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text("请选择标签（可多选，或点击跳过）：", reply_markup=reply_markup)
    
    return SELECTING_TAGS


async def tag_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # 处理新建标签
    if query.data == "tag_new":
        await query.edit_message_text("🏷️ 请输入新标签的名称：")
        return CREATING_TAG
    
    if query.data == "tags_done":
        await query.edit_message_text("请输入资源描述（或发送 /cancel 取消）：")
        return ENTERING_DESCRIPTION
    
    tag_id = int(query.data.split("_")[1])
    selected_tags = context.user_data[TEMP_RESOURCE_DATA].get("selected_tags", [])
    
    if tag_id in selected_tags:
        selected_tags.remove(tag_id)
    else:
        selected_tags.append(tag_id)
    
    context.user_data[TEMP_RESOURCE_DATA]["selected_tags"] = selected_tags
    
    with Session(engine) as session:
        tags = TagService.get_tags(session, update.effective_chat.id)
        
        keyboard = []
        row = []
        for i, tag in enumerate(tags):
            prefix = "✅ " if tag.id in selected_tags else "🏷️ "
            row.append(InlineKeyboardButton(f"{prefix}{tag.name}", callback_data=f"tag_{tag.id}"))
            if (i + 1) % 2 == 0:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        # 始终显示新建和完成按钮
        keyboard.append([InlineKeyboardButton("➕ 新建标签", callback_data="tag_new")])
        keyboard.append([InlineKeyboardButton("✅ 完成选择", callback_data="tags_done")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(f"🏷️ 已选择 {len(selected_tags)} 个标签\n请继续选择或点击完成：", reply_markup=reply_markup)
    
    return SELECTING_TAGS


async def create_category_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理新建分类的输入"""
    category_name = update.message.text.strip()
    
    with Session(engine) as session:
        # 创建新分类
        category = CategoryService.create_category(session, update.effective_chat.id, category_name, None)
        
        if not category:
            await update.message.reply_text(f"❌ 分类 '{category_name}' 已存在，请重新输入：")
            return CREATING_CATEGORY
        
        # 自动选择新建的分类
        context.user_data[TEMP_RESOURCE_DATA]["category_id"] = category.id
        
        await update.message.reply_text(f"✅ 已创建并选择分类: {category_name}")
        
        # 继续到标签选择
        tags = TagService.get_tags(session, update.effective_chat.id)
        
        if not tags:
            await update.message.reply_text("请输入资源描述（或发送 /cancel 取消）：")
            return ENTERING_DESCRIPTION
        
        keyboard = []
        row = []
        for i, tag in enumerate(tags):
            row.append(InlineKeyboardButton(f"🏷️ {tag.name}", callback_data=f"tag_{tag.id}"))
            if (i + 1) % 2 == 0:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        keyboard.append([
            InlineKeyboardButton("➕ 新建标签", callback_data="tag_new"),
            InlineKeyboardButton("⏭️ 跳过标签", callback_data="tags_done")
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text("请选择标签（可多选，或点击跳过）：", reply_markup=reply_markup)
    
    return SELECTING_TAGS


async def create_tag_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理新建标签的输入"""
    tag_name = update.message.text.strip()
    
    with Session(engine) as session:
        # 创建新标签
        tag = TagService.create_tag(session, update.effective_chat.id, tag_name)
        
        if not tag:
            await update.message.reply_text(f"❌ 标签 '#{tag_name}' 已存在，请重新输入：")
            return CREATING_TAG
        
        # 自动选择新建的标签
        selected_tags = context.user_data[TEMP_RESOURCE_DATA].get("selected_tags", [])
        selected_tags.append(tag.id)
        context.user_data[TEMP_RESOURCE_DATA]["selected_tags"] = selected_tags
        
        await update.message.reply_text(f"✅ 已创建并选择标签: #{tag_name}")
        
        # 显示更新后的标签列表
        tags = TagService.get_tags(session, update.effective_chat.id)
        
        keyboard = []
        row = []
        for i, t in enumerate(tags):
            prefix = "✅ " if t.id in selected_tags else "🏷️ "
            row.append(InlineKeyboardButton(f"{prefix}{t.name}", callback_data=f"tag_{t.id}"))
            if (i + 1) % 2 == 0:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        keyboard.append([
            InlineKeyboardButton("➕ 新建标签", callback_data="tag_new"),
            InlineKeyboardButton("✅ 完成选择", callback_data="tags_done")
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(f"🏷️ 已选择 {len(selected_tags)} 个标签\n请继续选择或点击完成：", reply_markup=reply_markup)
    
    return SELECTING_TAGS


async def description_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收描述输入，完成资源上传"""
    description = update.message.text.strip()
    data = context.user_data.get(TEMP_RESOURCE_DATA)
    
    if not data:
        await update.message.reply_text("上传会话已过期，请重新开始")
        return ConversationHandler.END
    
    with Session(engine) as session:
        # 创建资源
        resource = ResourceService.create_resource(
            session=session,
            group_id=update.effective_chat.id,
            message_id=data["message_id"],
            message_thread_id=data.get("message_thread_id"),
            uploader_id=update.effective_user.id,
            uploader_username=update.effective_user.username,
            uploader_first_name=update.effective_user.first_name,
            category_id=data.get("category_id"),
            title=data.get("title", data["file_name"]),
            description=description if description else None,
            file_type=data.get("file_type"),
            file_id=data.get("file_id"),
            file_unique_id=data.get("file_unique_id"),
            file_name=data["file_name"],
            file_size=data.get("file_size")
        )
        
        # 添加标签
        tag_ids = data.get("selected_tags", [])
        if tag_ids:
            ResourceService.add_tags_to_resource(
                session=session,
                resource_id=resource.id,
                tag_ids=tag_ids,
                added_by=update.effective_user.id
            )
            tags = session.exec(select(Tag).where(Tag.id.in_(tag_ids))).all()
        else:
            tags = []
        
        # 获取分类
        category = session.get(Category, data.get("category_id")) if data.get("category_id") else None
        
        # 在session内获取所有需要的数据
        resource_id = resource.id
        file_name = data['file_name']
        category_name = category.name if category else '未分类'
        message_id = data['message_id']
        message_thread_id = data.get('message_thread_id')
    
    # session外使用已获取的数据
    user = update.effective_user
    
    # 积分奖励
    with Session(engine) as points_session:
        PointsService.add_points(
            session=points_session,
            group_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            points=5,
            transaction_type="upload",
            description=f"上传资源: {file_name}"
        )
    points_earned = 5
    
    tags_text = " ".join([f"#{tag.name}" for tag in tags]) if tags else "无"
    message_link = f"https://t.me/c/{str(update.effective_chat.id)[4:]}/{message_id}"
    if message_thread_id:
        message_link += f"/{message_thread_id}"
    
    # 转发文件（Bot重新发送）
    file_message = None
    try:
        # 根据文件类型转发
        if data.get("file_id"):
            file_id = data["file_id"]
            file_type = data.get("file_type", "document")
            
            caption = (
                f"📦 <b>新资源上传</b>\n\n"
                f"📁 文件: {file_name}\n"
                f"📂 分类: {category_name}\n"
                f"🏷️ 标签: {tags_text}\n"
                f"📝 说明: {description or '无'}\n"
                f"👤 上传者: {user.mention_html()}\n"
                f"⭐ 积分: +{points_earned}\n\n"
                f"🆔 资源ID: {resource_id}"
            )
            
            if file_type == "document":
                file_message = await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=file_id,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    message_thread_id=message_thread_id
                )
            elif file_type == "photo":
                file_message = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=file_id,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    message_thread_id=message_thread_id
                )
            elif file_type == "video":
                file_message = await context.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=file_id,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    message_thread_id=message_thread_id
                )
            elif file_type == "audio":
                file_message = await context.bot.send_audio(
                    chat_id=update.effective_chat.id,
                    audio=file_id,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    message_thread_id=message_thread_id
                )
            else:
                # 默认作为文档发送
                file_message = await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=file_id,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    message_thread_id=message_thread_id
                )
            
            logger.info(f"Bot forwarded file for resource {resource_id}")
    except Exception as e:
        logger.warning(f"Failed to forward file: {e}")
    
    # 如果转发失败，发送文本通知
    if not file_message:
        notification = (
            f"📦 <b>新资源上传</b>\n\n"
            f"📁 文件: {file_name}\n"
            f"📂 分类: {category_name}\n"
            f"🏷️ 标签: {tags_text}\n"
            f"📝 说明: {description or '无'}\n"
            f"👤 上传者: {user.mention_html()}\n"
            f"⭐ 积分: +{points_earned}\n\n"
            f"<a href='{message_link}'>📎 查看原文件</a>\n"
            f"资源ID: {resource_id}"
        )
        
        await update.message.reply_text(notification, parse_mode=ParseMode.HTML, message_thread_id=message_thread_id)
    
    del context.user_data[TEMP_RESOURCE_DATA]
    
    return ConversationHandler.END


async def cancel_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if TEMP_RESOURCE_DATA in context.user_data:
        del context.user_data[TEMP_RESOURCE_DATA]
    
    await update.message.reply_text("❌ 已取消上传")
    return ConversationHandler.END


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not context.args:
        await update.message.reply_text("用法: /search <关键词>\n例如: /search Python教程")
        return
    
    keyword = " ".join(context.args)
    
    with Session(engine) as session:
        resources, total = ResourceService.search_resources(
            session=session,
            group_id=update.effective_chat.id,
            keyword=keyword,
            message_thread_id=update.message.message_thread_id,
            limit=10
        )
        
        if not resources:
            await update.message.reply_text(f"未找到包含\"{keyword}\"的资源")
            return
        
        result_text = f"🔍 搜索结果（共找到 {total} 个）\n\n"
        
        for resource in resources:
            category = session.get(Category, resource.category_id) if resource.category_id else None
            result_text += (
                f"📁 <b>{resource.title}</b> (ID: {resource.id})\n"
                f"📂 {category.name if category else '未分类'}\n"
                f"📝 {resource.description[:50] if resource.description else '无描述'}...\n"
                f"👤 @{resource.uploader_username or resource.uploader_first_name}\n"
                f"使用 /get_{resource.id} 获取文件\n\n"
            )
    
    await update.message.reply_text(result_text, parse_mode=ParseMode.HTML)


async def add_category_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from app.handlers.commands import is_admin
    if not await is_admin(update):
        await update.message.reply_text("❌ 此命令仅限管理员使用")
        return
    
    if not update.message or not context.args:
        await update.message.reply_text("用法: /add_category <名称> [描述]")
        return
    
    name = context.args[0]
    description = " ".join(context.args[1:]) if len(context.args) > 1 else None
    
    with Session(engine) as session:
        category = CategoryService.create_category(session, update.effective_chat.id, name, description)
        
        if category:
            await update.message.reply_text(f"✅ 已添加分类: {name}")
        else:
            await update.message.reply_text(f"❌ 分类已存在: {name}")


async def add_tag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from app.handlers.commands import is_admin
    if not await is_admin(update):
        await update.message.reply_text("❌ 此命令仅限管理员使用")
        return
    
    if not update.message or not context.args:
        await update.message.reply_text("用法: /add_tag <名称>")
        return
    
    name = context.args[0]
    
    with Session(engine) as session:
        tag = TagService.create_tag(session, update.effective_chat.id, name)
        
        if tag:
            await update.message.reply_text(f"✅ 已添加标签: #{name}")
        else:
            await update.message.reply_text(f"❌ 标签已存在: #{name}")


async def list_categories_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with Session(engine) as session:
        categories = CategoryService.get_categories(session, update.effective_chat.id)
        
        if not categories:
            await update.message.reply_text("该群组还没有分类")
            return
        
        text = "📂 <b>所有分类</b>\n\n"
        for cat in categories:
            text += f"• {cat.name}"
            if cat.description:
                text += f" - {cat.description}"
            text += f" (ID: {cat.id})\n"
        
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def list_tags_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with Session(engine) as session:
        tags = TagService.get_tags(session, update.effective_chat.id)
        
        if not tags:
            await update.message.reply_text("该群组还没有标签")
            return
        
        text = "🏷️ <b>所有标签</b>\n\n"
        text += " ".join([f"#{tag.name}" for tag in tags])
        
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)


upload_conversation = ConversationHandler(
    entry_points=[CommandHandler("upload", upload_command)],
    states={
        SELECTING_CATEGORY: [CallbackQueryHandler(category_callback, pattern="^cat_")],
        SELECTING_TAGS: [CallbackQueryHandler(tag_callback, pattern="^tag_|^tags_done$")],
        ENTERING_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, description_input)],
        CREATING_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_category_input)],
        CREATING_TAG: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_tag_input)],
    },
    fallbacks=[CommandHandler("cancel", cancel_upload)],
)


async def get_resource_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    
    text = update.message.text
    match = re.match(r'/get_(\d+)', text)
    if not match:
        return
    
    resource_id = int(match.group(1))
    
    with Session(engine) as session:
        resource = session.get(Resource, resource_id)
        
        if not resource or resource.group_id != update.effective_chat.id:
            await update.message.reply_text("❌ 资源不存在或无权访问")
            return
        
        try:
            await context.bot.forward_message(
                chat_id=update.effective_chat.id,
                from_chat_id=update.effective_chat.id,
                message_id=resource.message_id,
                message_thread_id=update.message.message_thread_id
            )
            
            category = session.get(Category, resource.category_id) if resource.category_id else None
            info_text = (
                f"📁 {resource.title}\n"
                f"📂 {category.name if category else '未分类'}\n"
                f"👤 上传者: @{resource.uploader_username or resource.uploader_first_name}"
            )
            if resource.description:
                info_text += f"\n📝 {resource.description}"
            
            await update.message.reply_text(info_text)
            
        except Exception as e:
            logger.debug(f"转发文件失败: {e}")
            
            message_link = f"https://t.me/c/{str(update.effective_chat.id)[4:]}/{resource.message_id}"
            if resource.message_thread_id:
                message_link += f"?thread={resource.message_thread_id}"
            
            category = session.get(Category, resource.category_id) if resource.category_id else None
            link_text = (
                f"📁 <b>{resource.title}</b>\n"
                f"📂 {category.name if category else '未分类'}\n"
                f"👤 @{resource.uploader_username or resource.uploader_first_name}\n\n"
            )
            if resource.description:
                link_text += f"📝 {resource.description}\n\n"
            
            link_text += f"👉 <a href='{message_link}'>点击查看原文件</a>"
            
            await update.message.reply_text(link_text, parse_mode=ParseMode.HTML)


async def resources_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    
    with Session(engine) as session:
        resources, total = ResourceService.list_resources(
            session=session,
            group_id=update.effective_chat.id,
            message_thread_id=update.message.message_thread_id,
            limit=5,
            offset=0
        )
        
        if not resources:
            await update.message.reply_text("📦 该群组/话题还没有资源\n\n使用 /upload 上传第一个文件吧！")
            return
        
        text = f"📦 资源库 (共 {total} 个)\n\n"
        keyboard = []
        
        for resource in resources:
            category = session.get(Category, resource.category_id) if resource.category_id else None
            
            text += (
                f"📁 <b>{resource.title}</b>\n"
                f"📂 {category.name if category else '未分类'} | "
                f"👤 @{resource.uploader_username or resource.uploader_first_name}\n"
            )
            if resource.description:
                desc_preview = resource.description[:50] + "..." if len(resource.description) > 50 else resource.description
                text += f"📝 {desc_preview}\n"
            text += "\n"
            
            keyboard.append([InlineKeyboardButton(f"🔗 {resource.title[:20]}", callback_data=f"get_res_{resource.id}")])
        
        nav_buttons = []
        if total > 5:
            nav_buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data="res_page_1"))
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        keyboard.append([
            InlineKeyboardButton("📂 按分类筛选", callback_data="filter_category"),
            InlineKeyboardButton("🏷️ 按标签筛选", callback_data="filter_tag")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def resources_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理资源面板的回调"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # 处理资源详情查看
    if data.startswith("get_res_"):
        resource_id = int(data.split("_")[2])
        
        with Session(engine) as session:
            resource = session.get(Resource, resource_id)
            
            if not resource:
                await query.answer("资源不存在", show_alert=True)
                return
            
            # 构建资源详情
            category = session.get(Category, resource.category_id) if resource.category_id else None
            tags_statement = select(Tag).join(ResourceTag).where(ResourceTag.resource_id == resource.id)
            tags = list(session.exec(tags_statement).all())
            
            file_link = f"https://t.me/c/{str(update.effective_chat.id)[4:]}/{resource.message_id}"
            if resource.message_thread_id:
                file_link += f"/{resource.message_thread_id}"
            
            text = f"📦 <b>{resource.title}</b>\n\n"
            text += f"📂 分类: {category.name if category else '未分类'}\n"
            
            if tags:
                tags_text = " ".join([f"#{tag.name}" for tag in tags])
                text += f"🏷️ 标签: {tags_text}\n"
            
            text += f"👤 上传者: @{resource.uploader_username or resource.uploader_first_name}\n"
            
            if resource.description:
                text += f"\n📝 描述:\n{resource.description}\n"
            
            if resource.file_size:
                size_mb = resource.file_size / (1024 * 1024)
                text += f"\n📊 大小: {size_mb:.2f} MB"
            
            text += f"\n\n🆔 资源ID: {resource.id}\n"
            text += f"<a href='{file_link}'>📎 查看原文件</a>"
            
            # 检查删除权限
            user_id = update.effective_user.id
            can_delete = ResourceService.can_delete_resource(resource, user_id, False)
            
            # 构建按钮  
            keyboard = []
            keyboard.append([InlineKeyboardButton("📤 发送文件", callback_data=f"res_send_{resource_id}")])
            if can_delete:
                keyboard.append([InlineKeyboardButton("🗑️ 删除资源", callback_data=f"res_del_{resource_id}")])
            keyboard.append([InlineKeyboardButton("🔙 返回资源库", callback_data="res_page_0")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
    
    # 处理发送文件
    elif data.startswith("res_send_"):
        resource_id = int(data.split("_")[2])
        
        with Session(engine) as session:
            resource = session.get(Resource, resource_id)
            if not resource:
                await query.answer("资源不存在", show_alert=True)
                return
            
            # 准备caption
            category = session.get(Category, resource.category_id) if resource.category_id else None
            tags_statement = select(Tag).join(ResourceTag).where(ResourceTag.resource_id == resource.id)
            tags = list(session.exec(tags_statement).all())
            tags_text = " ".join([f"#{tag.name}" for tag in tags]) if tags else "无"
            
            caption = (
                f"📦 <b>{resource.title}</b>\n\n"
                f"📂 分类: {category.name if category else '未分类'}\n"
                f"🏷️ 标签: {tags_text}\n"
            )
            if resource.description:
                caption += f"\n📝 {resource.description}\n"
            caption += f"\n👤 上传者: @{resource.uploader_username or resource.uploader_first_name}"
            caption += f"\n🆔 资源ID: {resource.id}"
            
            # 发送文件
            try:
                if resource.file_id and resource.file_type:
                    await query.answer("正在发送文件...", show_alert=False)
                    
                    if resource.file_type == "document":
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=resource.file_id,
                            caption=caption,
                            parse_mode=ParseMode.HTML,
                            message_thread_id=resource.message_thread_id
                        )
                    elif resource.file_type == "photo":
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=resource.file_id,
                            caption=caption,
                            parse_mode=ParseMode.HTML,
                            message_thread_id=resource.message_thread_id
                        )
                    elif resource.file_type == "video":
                        await context.bot.send_video(
                            chat_id=update.effective_chat.id,
                            video=resource.file_id,
                            caption=caption,
                            parse_mode=ParseMode.HTML,
                            message_thread_id=resource.message_thread_id
                        )
                    elif resource.file_type == "audio":
                        await context.bot.send_audio(
                            chat_id=update.effective_chat.id,
                            audio=resource.file_id,
                            caption=caption,
                            parse_mode=ParseMode.HTML,
                            message_thread_id=resource.message_thread_id
                        )
                    else:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=resource.file_id,
                            caption=caption,
                            parse_mode=ParseMode.HTML,
                            message_thread_id=resource.message_thread_id
                        )
                    
                    await query.answer("✅ 文件已发送", show_alert=True)
                else:
                    await query.answer("❌ 文件信息不完整", show_alert=True)
            except Exception as e:
                logger.error(f"Failed to send file: {e}")
                await query.answer("❌ 发送失败", show_alert=True)
    
    elif data.startswith("res_page_"):
        page = int(data.split("_")[2])
        offset = page * 5
        
        with Session(engine) as session:
            resources, total = ResourceService.list_resources(
                session=session,
                group_id=update.effective_chat.id,
                message_thread_id=query.message.message_thread_id,
                limit=5,
                offset=offset
            )
            
            if not resources:
                await query.answer("没有更多资源了", show_alert=True)
                return
            
            text = f"📦 资源库 (共 {total} 个) - 第 {page + 1} 页\n\n"
            keyboard = []
            
            for resource in resources:
                category = session.get(Category, resource.category_id) if resource.category_id else None
                text += (
                    f"📁 <b>{resource.title}</b>\n"
                    f"📂 {category.name if category else '未分类'} | "
                    f"👤 @{resource.uploader_username or resource.uploader_first_name}\n"
                )
                if resource.description:
                    desc_preview = resource.description[:50] + "..." if len(resource.description) > 50 else resource.description
                    text += f"📝 {desc_preview}\n"
                text += "\n"
                
                keyboard.append([InlineKeyboardButton(f"🔗 {resource.title[:20]}", callback_data=f"get_res_{resource.id}")])
            
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"res_page_{page - 1}"))
            if offset + 5 < total:
                nav_buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"res_page_{page + 1}"))
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            keyboard.append([
                InlineKeyboardButton("📂 按分类筛选", callback_data="filter_category"),
                InlineKeyboardButton("🏷️ 按标签筛选", callback_data="filter_tag")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    
    elif data == "filter_category":
        # 显示分类列表供用户选择
        with Session(engine) as session:
            categories = CategoryService.get_categories(session, update.effective_chat.id)
            
            if not categories:
                await query.answer("该群组还没有分类", show_alert=True)
                return
            
            keyboard = []
            for category in categories:
                keyboard.append([InlineKeyboardButton(
                    f"📂 {category.name}",
                    callback_data=f"filter_cat_{category.id}"
                )])
            keyboard.append([InlineKeyboardButton("🔙 返回资源库", callback_data="res_page_0")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("📂 选择分类进行筛选：", reply_markup=reply_markup)
    
    elif data == "filter_tag":
        # 显示标签列表供用户选择
        with Session(engine) as session:
            tags = TagService.get_tags(session, update.effective_chat.id)
            
            if not tags:
                await query.answer("该群组还没有标签", show_alert=True)
                return
            
            keyboard = []
            row = []
            for i, tag in enumerate(tags):
                row.append(InlineKeyboardButton(
                    f"🏷️ {tag.name}",
                    callback_data=f"filter_tag_{tag.id}"
                ))
                if (i + 1) % 2 == 0:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            keyboard.append([InlineKeyboardButton("🔙 返回资源库", callback_data="res_page_0")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("🏷️ 选择标签进行筛选：", reply_markup=reply_markup)
    
    elif data.startswith("filter_cat_"):
        # 按分类筛选
        category_id = int(data.split("_")[2])
        
        with Session(engine) as session:
            resources, total = ResourceService.list_resources(
                session=session,
                group_id=update.effective_chat.id,
                category_id=category_id,
                message_thread_id=query.message.message_thread_id,
                limit=5,
                offset=0
            )
            
            category = session.get(Category, category_id)
            
            if not resources:
                await query.answer(f"分类 '{category.name}' 下还没有资源", show_alert=True)
                return
            
            text = f"📦 资源库 - {category.name} (共 {total} 个)\n\n"
            keyboard = []
            
            for resource in resources:
                text += (
                    f"📁 <b>{resource.title}</b>\n"
                    f"👤 @{resource.uploader_username or resource.uploader_first_name}\n"
                )
                if resource.description:
                    desc_preview = resource.description[:50] + "..." if len(resource.description) > 50 else resource.description
                    text += f"📝 {desc_preview}\n"
                text += "\n"
                
                keyboard.append([InlineKeyboardButton(f"🔗 {resource.title[:20]}", callback_data=f"get_res_{resource.id}")])
            
            keyboard.append([InlineKeyboardButton("🔙 返回资源库", callback_data="res_page_0")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    
    elif data.startswith("filter_tag_"):
        # 按标签筛选
        tag_id = int(data.split("_")[2])
        
        with Session(engine) as session:
            resources, total = ResourceService.list_resources(
                session=session,
                group_id=update.effective_chat.id,
                tag_ids=[tag_id],
                message_thread_id=query.message.message_thread_id,
                limit=5,
                offset=0
            )
            
            tag = session.get(Tag, tag_id)
            
            if not resources:
                await query.answer(f"标签 '#{tag.name}' 下还没有资源", show_alert=True)
                return
            
            text = f"📦 资源库 - #{tag.name} (共 {total} 个)\n\n"
            keyboard = []
            
            for resource in resources:
                category = session.get(Category, resource.category_id) if resource.category_id else None
                text += (
                    f"📁 <b>{resource.title}</b>\n"
                    f"📂 {category.name if category else '未分类'} | "
                    f"👤 @{resource.uploader_username or resource.uploader_first_name}\n"
                )
                if resource.description:
                    desc_preview = resource.description[:50] + "..." if len(resource.description) > 50 else resource.description
                    text += f"📝 {desc_preview}\n"
                text += "\n"
                
                keyboard.append([InlineKeyboardButton(f"🔗 {resource.title[:20]}", callback_data=f"get_res_{resource.id}")])
            
            keyboard.append([InlineKeyboardButton("🔙 返回资源库", callback_data="res_page_0")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def delete_resource_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /delete_resource <id> - 删除资源
    
    权限：上传者本人或管理员
    """
    if not update.message or not context.args:
        await update.message.reply_text(
            "用法: /delete_resource <资源ID>\n\n"
            "例如: /delete_resource 123"
        )
        return
    
    try:
        resource_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ 资源ID必须是数字")
        return
    
    # 检查管理员权限
    from app.handlers.commands import is_admin
    user_is_admin = await is_admin(update)
    
    user_id = update.effective_user.id
    
    # 执行删除
    with Session(engine) as session:
        success, message = ResourceService.delete_resource(
            session=session,
            resource_id=resource_id,
            user_id=user_id,
            is_admin=user_is_admin
        )
        
        if success:
            await update.message.reply_text(f"✅ {message}")
        else:
            await update.message.reply_text(f"❌ {message}")

