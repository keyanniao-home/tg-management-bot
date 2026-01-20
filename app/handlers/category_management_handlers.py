"""
分类和标签管理面板

提供可视化管理界面：
- 查看所有分类/标签及使用情况
- 编辑分类/标签名称
- 删除分类/标签
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters
from sqlmodel import Session, select, func
from app.database.connection import engine
from app.models import Category, Tag, Resource, ResourceTag
from app.services.resource_service import CategoryService, TagService
from app.utils.auto_delete import auto_delete_message
from loguru import logger


EDITING_CATEGORY, EDITING_TAG = range(2)


@auto_delete_message(delay=120)
async def manage_categories_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /manage_categories - 分类管理面板（仅管理员）
    """
    from app.handlers.commands import is_admin

    if not await is_admin(update):
        return await update.message.reply_text("❌ 此命令仅限管理员使用")

    with Session(engine) as session:
        categories = CategoryService.get_categories(session, update.effective_chat.id)

        if not categories:
            return await update.message.reply_text(
                "📂 暂无分类\n\n使用 /add_category 命令创建分类",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 返回", callback_data="catmgmt_close")]]
                ),
            )

        text = "📂 分类管理\n\n"
        keyboard = []

        for category in categories:
            # 统计使用数量
            count = session.exec(
                select(func.count(Resource.id)).where(
                    Resource.category_id == category.id
                )
            ).one()

            text += f"📂 {category.name} ({count}个资源)\n"
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"✏️ {category.name}",
                        callback_data=f"catmgmt_edit_{category.id}",
                    ),
                    InlineKeyboardButton(
                        "🗑️", callback_data=f"catmgmt_del_{category.id}"
                    ),
                ]
            )

        return await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard)
        )


@auto_delete_message(delay=120)
async def manage_tags_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /manage_tags - 标签管理面板（仅管理员）
    """
    from app.handlers.commands import is_admin

    if not await is_admin(update):
        return await update.message.reply_text("❌ 此命令仅限管理员使用")

    with Session(engine) as session:
        tags = TagService.get_tags(session, update.effective_chat.id)

        if not tags:
            return await update.message.reply_text(
                "🏷️ 暂无标签\n\n使用 /add_tag 命令创建标签",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 返回", callback_data="tagmgmt_close")]]
                ),
            )

        text = "🏷️ 标签管理\n\n"
        keyboard = []

        for tag in tags:
            # 统计使用数量
            count = session.exec(
                select(func.count(ResourceTag.resource_id)).where(
                    ResourceTag.tag_id == tag.id
                )
            ).one()

            text += f"🏷️ {tag.name} ({count}次使用)\n"
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"✏️ {tag.name}", callback_data=f"tagmgmt_edit_{tag.id}"
                    ),
                    InlineKeyboardButton("🗑️", callback_data=f"tagmgmt_del_{tag.id}"),
                ]
            )

        return await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def category_management_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """处理分类管理的回调"""
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        # 忽略回调查询超时错误
        pass

    data = query.data

    if data.startswith("catmgmt_edit_"):
        # 编辑分类
        category_id = int(data.split("_")[2])

        with Session(engine) as session:
            category = session.get(Category, category_id)
            if not category:
                await query.answer("分类不存在", show_alert=True)
                return

            await query.edit_message_text(
                f"✏️ 编辑分类: {category.name}\n\n请回复此消息输入新的分类名称："
            )
            context.user_data["editing_category_id"] = category_id

    elif data.startswith("catmgmt_del_") and not data.startswith(
        "catmgmt_del_confirm_"
    ):
        # 删除分类
        category_id = int(data.split("_")[2])

        with Session(engine) as session:
            category = session.get(Category, category_id)
            if not category:
                await query.answer("分类不存在", show_alert=True)
                return

            # 检查是否有资源使用此分类
            count = session.exec(
                select(func.count(Resource.id)).where(
                    Resource.category_id == category_id
                )
            ).one()

            warning = (
                f'\n\n⚠️ 有 {count} 个资源使用此分类\n关联的资源将变为"未分类"'
                if count > 0
                else ""
            )

            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ 确认删除",
                        callback_data=f"catmgmt_del_confirm_{category_id}",
                    ),
                    InlineKeyboardButton("❌ 取消", callback_data="catmgmt_back"),
                ]
            ]

            await query.edit_message_text(
                f"🗑️ 确定要删除分类「{category.name}」吗？{warning}",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

    elif data.startswith("catmgmt_del_confirm_"):
        # 确认删除分类
        category_id = int(data.split("_")[3])

        with Session(engine) as session:
            category = session.get(Category, category_id)
            if category:
                name = category.name
                session.delete(category)
                session.commit()
                await query.edit_message_text(f"✅ 分类「{name}」已删除")
            else:
                await query.edit_message_text("❌ 分类不存在")

    elif data == "catmgmt_back" or data == "catmgmt_close":
        await query.edit_message_text("已取消操作")


async def tag_management_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理标签管理的回调"""
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        # 忽略回调查询超时错误
        pass

    data = query.data

    if data.startswith("tagmgmt_edit_"):
        # 编辑标签
        tag_id = int(data.split("_")[2])

        with Session(engine) as session:
            tag = session.get(Tag, tag_id)
            if not tag:
                await query.answer("标签不存在", show_alert=True)
                return

            await query.edit_message_text(
                f"✏️ 编辑标签: #{tag.name}\n\n请回复此消息输入新的标签名称："
            )
            context.user_data["editing_tag_id"] = tag_id

    elif data.startswith("tagmgmt_del_") and not data.startswith(
        "tagmgmt_del_confirm_"
    ):
        # 删除标签
        tag_id = int(data.split("_")[2])

        with Session(engine) as session:
            tag = session.get(Tag, tag_id)
            if not tag:
                await query.answer("标签不存在", show_alert=True)
                return

            # 检查使用情况
            count = session.exec(
                select(func.count(ResourceTag.resource_id)).where(
                    ResourceTag.tag_id == tag_id
                )
            ).one()

            warning = (
                f"\n\n⚠️ 此标签被使用了 {count} 次\n相关关联将被删除"
                if count > 0
                else ""
            )

            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ 确认删除", callback_data=f"tagmgmt_del_confirm_{tag_id}"
                    ),
                    InlineKeyboardButton("❌ 取消", callback_data="tagmgmt_back"),
                ]
            ]

            await query.edit_message_text(
                f"🗑️ 确定要删除标签「#{tag.name}」吗？{warning}",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

    elif data.startswith("tagmgmt_del_confirm_"):
        # 确认删除标签
        tag_id = int(data.split("_")[3])

        with Session(engine) as session:
            tag = session.get(Tag, tag_id)
            if tag:
                name = tag.name
                # 先删除关联的 resource_tags 记录（外键约束）
                resource_tag_links = session.exec(
                    select(ResourceTag).where(ResourceTag.tag_id == tag_id)
                ).all()
                for link in resource_tag_links:
                    session.delete(link)
                # 然后删除标签
                session.delete(tag)
                session.commit()
                await query.edit_message_text(f"✅ 标签「#{name}」已删除")
            else:
                await query.edit_message_text("❌ 标签不存在")

    elif data in ("tagmgmt_back", "tagmgmt_close"):
        await query.edit_message_text("已取消操作")


@auto_delete_message(delay=120)
async def handle_category_edit_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """处理分类编辑输入"""
    category_id = context.user_data.get("editing_category_id")
    if not category_id:
        return

    new_name = update.message.text.strip()

    if not new_name:
        return await update.message.reply_text("❌ 分类名称不能为空")

    with Session(engine) as session:
        category = session.get(Category, category_id)
        if not category:
            # 清除编辑状态
            del context.user_data["editing_category_id"]
            return await update.message.reply_text("❌ 分类不存在")

        old_name = category.name
        category.name = new_name
        session.add(category)
        session.commit()

        # 清除编辑状态
        del context.user_data["editing_category_id"]
        return await update.message.reply_text(
            f"✅ 分类已更新\n\n{old_name} → {new_name}"
        )


@auto_delete_message(delay=120)
async def handle_tag_edit_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理标签编辑输入"""
    tag_id = context.user_data.get("editing_tag_id")
    if not tag_id:
        return

    new_name = update.message.text.strip()

    if not new_name:
        return await update.message.reply_text("❌ 标签名称不能为空")

    with Session(engine) as session:
        tag = session.get(Tag, tag_id)
        if not tag:
            # 清除编辑状态
            del context.user_data["editing_tag_id"]
            return await update.message.reply_text("❌ 标签不存在")

        old_name = tag.name
        tag.name = new_name
        session.add(tag)
        session.commit()

        # 清除编辑状态
        del context.user_data["editing_tag_id"]
        return await update.message.reply_text(
            f"✅ 标签已更新\n\n#{old_name} → #{new_name}"
        )
