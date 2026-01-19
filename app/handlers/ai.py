"""
AI 功能命令处理器

提供基于 AI 的用户画像分析和号商识别功能
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from loguru import logger
from sqlmodel import Session, select
import asyncio
import uuid

from app.utils.auto_delete import auto_delete_message
from app.utils.user_resolver import UserResolver
from app.database.connection import engine
from app.models import GroupConfig, GroupAdmin, GroupMember
from app.services.ai import user_profile_analyzer
from app.services.ai.scammer_cache import scammer_cache_service
from app.handlers.stats import LRUCache


async def is_admin(update: Update) -> bool:
    """检查用户或频道是否是管理员"""
    if update.message.sender_chat:
        check_id = update.message.sender_chat.id
    elif update.effective_user:
        check_id = update.effective_user.id
    else:
        return False

    with Session(engine) as session:
        statement = select(GroupConfig).where(GroupConfig.group_id == update.effective_chat.id)
        group = session.exec(statement).first()
        if not group:
            return False

        statement = select(GroupAdmin).where(
            GroupAdmin.group_id == group.id,
            GroupAdmin.user_id == check_id,
        )
        admin = session.exec(statement).first()
        return admin is not None


from app.config.settings import settings


# 号商检测结果缓存（用于分页展示）
scammer_results_cache = LRUCache(capacity=100)


async def detect_scammer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    号商识别命令

    用法:
    - /kobe_detect_scammer - 检测全群（使用缓存）
    - /kobe_detect_scammer <user_id|@username|reply> - 检测单用户
    """
    # 检查是否是管理员，非管理员直接返回
    if not await is_admin(update):
        return None

    # 检查是否启用 AI
    if not settings.is_ai_configured:
        return await update.message.reply_text(
            "❌ AI 功能未启用\n\n"
            "启用步骤：\n"
            "1. 在 .env 中配置 AI_ENABLED=true\n"
            "2. 配置 AI_BASE_URL 和 AI_API_KEY\n"
            "3. 配置 AI_MODEL_ID"
        )

    # 获取群组配置
    with Session(engine) as session:
        statement = select(GroupConfig).where(GroupConfig.group_id == update.effective_chat.id)
        group = session.exec(statement).first()

        if not group:
            return await update.message.reply_text("❌ 群组未初始化")

        # 使用 UserResolver 解析目标用户
        user_info = UserResolver.resolve_with_db(update, context.args, session, group.id)

    # 如果有目标用户，进行单用户检测
    if user_info:
        target_user_id, _, _ = user_info
        return await _detect_single_scammer(update, context, target_user_id, group.id)

    # 否则进行全群检测
    return await _detect_group_scammers(update, context, group.id)


async def _detect_single_scammer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    group_db_id: int
):
    """检测单个用户（无缓存）"""
    status_msg = await update.message.reply_text("🔄 正在检测号商，请稍候...")

    try:
        # 获取管理员ID
        admin_id = update.effective_user.id if update.effective_user else 0

        # 检测号商（单用户不使用缓存，但会检查爬虫缓存）
        result = await scammer_cache_service.detect_single_user(
            group_telegram_id=update.effective_chat.id,
            user_id=user_id,
            detected_by_user_id=admin_id,
            use_cache=True  # 优先使用缓存
        )

        if not result:
            return await status_msg.edit_text(
                "❌ 该用户数据不足，无法进行检测\n\n"
                "提示：请先使用 /kobe_crawl_users --channels 爬取用户数据"
            )

        # 获取用户信息
        with Session(engine) as session:
            statement = select(GroupMember).where(
                GroupMember.group_id == group_db_id,
                GroupMember.user_id == user_id
            )
            member = session.exec(statement).first()

        username = member.username if member else None
        full_name = member.full_name if member else "未知用户"

        # 格式化结果
        status_emoji = "⚠️" if result.is_scammer else "✅"
        confidence_percent = result.confidence * 100

        result_text = (
            f"{status_emoji} 号商检测结果\n\n"
            f"用户ID: {user_id}\n"
            f"用户名: {('@' + username) if username else '无'}\n"
            f"昵称: {full_name}\n\n"
            f"是否为号商: {'是' if result.is_scammer else '否'}\n"
            f"置信度: {confidence_percent:.1f}%\n\n"
            f"判断依据：\n{result.evidence}"
        )

        return await status_msg.edit_text(result_text)

    except Exception as e:
        logger.exception("号商检测失败")
        return await status_msg.edit_text(f"❌ 检测失败: {str(e)}")


async def _detect_group_scammers(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    group_db_id: int
):
    """检测全群用户（使用缓存）"""
    status_msg = await update.message.reply_text(
        "🔄 正在检测全群号商（使用缓存优先）...\n\n"
        "提示：检测结果缓存3天，如需重新检测，请等待缓存过期"
    )

    try:
        # 获取管理员ID
        admin_id = update.effective_user.id if update.effective_user else 0

        # 检测全群（使用缓存）
        results = await scammer_cache_service.detect_group_users(
            group_telegram_id=update.effective_chat.id,
            detected_by_user_id=admin_id,
            use_cache=True
        )

        if not results:
            return await status_msg.edit_text(
                "✅ 检测完成，未发现号商\n\n"
                "提示：如果还没有爬取用户数据，请使用 /kobe_crawl_users --channels"
            )

        # 筛选出号商
        scammers = [r for r in results if r['result'].is_scammer]

        if not scammers:
            return await status_msg.edit_text(
                f"✅ 检测完成，共检测 {len(results)} 个用户\n"
                f"未发现号商"
            )

        # 生成缓存键用于分页
        cache_key = str(uuid.uuid4())
        scammer_results_cache.put(cache_key, scammers)

        # 显示第一页
        await _show_scammer_page(
            update=update,
            context=context,
            message=status_msg,
            cache_key=cache_key,
            scammers=scammers,
            page=0,
            is_new=True
        )

    except Exception as e:
        logger.exception("全群号商检测失败")
        return await status_msg.edit_text(f"❌ 检测失败: {str(e)}")


async def _show_scammer_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    message,
    cache_key: str,
    scammers: list,
    page: int,
    is_new: bool = False
):
    """显示号商检测结果的某一页"""
    page_size = 10
    total_pages = (len(scammers) + page_size - 1) // page_size
    start_idx = page * page_size
    end_idx = min(start_idx + page_size, len(scammers))

    page_scammers = scammers[start_idx:end_idx]

    # 构建结果文本
    lines = [
        f"⚠️ 号商检测结果（第 {page + 1}/{total_pages} 页）\n",
        f"共发现 {len(scammers)} 个疑似号商：\n"
    ]

    for idx, scammer in enumerate(page_scammers, start=start_idx + 1):
        user_id = scammer['user_id']
        username = scammer['username']
        full_name = scammer['full_name'] or "未知用户"
        result = scammer['result']
        confidence = result.confidence * 100

        username_str = f"@{username}" if username else "无"
        lines.append(
            f"{idx}. {full_name} ({username_str})\n"
            f"   ID: {user_id}\n"
            f"   置信度: {confidence:.1f}%\n"
            f"   依据: {result.evidence[:50]}...\n"
        )

    # 添加提示（仅第一页）
    if page == 0 and is_new:
        lines.append('\n💡 回复"确认"来批量踢出这些用户')

    result_text = "\n".join(lines)

    # 构建翻页按钮
    keyboard = []
    nav_buttons = []

    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ 上一页", callback_data=f"scammer_page:{cache_key}:{page-1}"))

    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("下一页 ▶️", callback_data=f"scammer_page:{cache_key}:{page+1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    try:
        await message.edit_text(result_text, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"编辑消息失败: {e}")

    # 保存待确认信息（仅第一页）
    if page == 0 and is_new:
        context.bot_data.setdefault('pending_scammer_kick', {})[update.effective_chat.id] = {
            'cache_key': cache_key,
            'scammers': scammers,
            'message_id': message.message_id,
        }


async def handle_scammer_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理号商踢出确认

    用户回复"确认"时触发
    """
    # 检查是否有待确认的踢出任务
    pending = context.bot_data.get('pending_scammer_kick', {}).get(update.effective_chat.id)

    if not pending:
        return

    # 检查是否是回复检测结果消息
    if update.message.reply_to_message and update.message.reply_to_message.message_id == pending['message_id']:
        # 检查是否是管理员
        if not await is_admin(update):
            return await update.message.reply_text("❌ 只有管理员可以确认踢出")

        # 检查消息内容是否是"确认"
        if update.message.text and update.message.text.strip() == "确认":
            scammers = pending['scammers']

            # 删除待确认记录
            del context.bot_data['pending_scammer_kick'][update.effective_chat.id]

            # 开始批量踢出
            await _batch_kick_scammers(
                update=update,
                context=context,
                scammers=scammers
            )


async def _batch_kick_scammers(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    scammers: list
):
    """批量踢出号商"""
    status_msg = await update.message.reply_text(
        f"🔄 开始批量踢出 {len(scammers)} 个号商...\n"
        f"进度: 0/{len(scammers)}"
    )

    success_count = 0
    fail_count = 0
    failed_users = []

    for idx, scammer in enumerate(scammers, 1):
        user_id = scammer['user_id']
        username = scammer['username']
        full_name = scammer['full_name'] or "未知用户"

        try:
            # 踢出用户（ban + unban）
            await context.bot.ban_chat_member(
                chat_id=update.effective_chat.id,
                user_id=user_id
            )
            await context.bot.unban_chat_member(
                chat_id=update.effective_chat.id,
                user_id=user_id
            )

            success_count += 1
            logger.info(f"踢出号商成功: {user_id} ({username})")

        except Exception as e:
            fail_count += 1
            failed_users.append((user_id, username, full_name, str(e)))
            logger.error(f"踢出号商失败: {user_id} ({username}): {e}")

        # 每10个更新一次进度
        if idx % 10 == 0 or idx == len(scammers):
            try:
                await status_msg.edit_text(
                    f"🔄 批量踢出进度\n\n"
                    f"总数: {len(scammers)}\n"
                    f"成功: {success_count}\n"
                    f"失败: {fail_count}\n"
                    f"进度: {idx}/{len(scammers)}"
                )
            except Exception:
                pass

        # 避免触发限流
        await asyncio.sleep(0.5)

    # 构建结果消息
    result_lines = [
        f"✅ 批量踢出完成\n",
        f"总数: {len(scammers)}",
        f"成功: {success_count}",
        f"失败: {fail_count}"
    ]

    if failed_users:
        result_lines.append("\n失败列表：")
        for user_id, username, full_name, error in failed_users[:10]:  # 最多显示10个
            username_str = f"@{username}" if username else "无"
            result_lines.append(f"- {full_name} ({username_str}): {error}")

        if len(failed_users) > 10:
            result_lines.append(f"... 还有 {len(failed_users) - 10} 个失败")

    await status_msg.edit_text("\n".join(result_lines))


async def handle_scammer_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理号商检测结果翻页回调"""
    query = update.callback_query
    await query.answer()

    # 解析回调数据: scammer_page:cache_key:page
    try:
        _, cache_key, page_str = query.data.split(":")
        page = int(page_str)
    except (ValueError, AttributeError):
        return await query.edit_message_text("❌ 无效的回调数据")

    # 从缓存中获取结果
    scammers = scammer_results_cache.get(cache_key)
    if not scammers:
        return await query.edit_message_text("❌ 缓存已过期，请重新执行检测")

    # 显示指定页
    await _show_scammer_page(
        update=update,
        context=context,
        message=query.message,
        cache_key=cache_key,
        scammers=scammers,
        page=page,
        is_new=False
    )

async def analyze_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    分析用户画像命令

    用法:
    - /kobe_analyze_user [风格] - 分析发送者自己（支持用户和频道）
    - /kobe_analyze_user <user_id|@username> [风格] - 分析指定用户/频道
    - /kobe_analyze_user [风格] (回复消息) - 分析被回复的用户/频道
    - 风格参数可选，限制10个字符，如：中二风、文艺风、冷幽默、客观风等
    """

    # 检查是否启用 AI
    if not settings.is_ai_configured:
        return await update.message.reply_text(
            "❌ AI 功能未启用\n\n"
            "启用步骤：\n"
            "1. 在 .env 中配置 AI_ENABLED=true\n"
            "2. 配置 AI_BASE_URL 和 AI_API_KEY\n"
            "3. 配置 AI_MODEL_ID"
        )

    # 获取群组配置
    with Session(engine) as session:
        statement = select(GroupConfig).where(GroupConfig.group_id == update.effective_chat.id)
        group = session.exec(statement).first()

        if not group:
            return await update.message.reply_text("❌ 群组未初始化")

        # 使用 UserResolver 解析目标用户
        user_info = UserResolver.resolve_with_db(update, context.args, session, group.id)

    # 提取风格参数
    style = "客观风"  # 默认风格

    # 如果没有指定用户，默认分析命令发送者自己（支持频道）
    if not user_info:
        # 判断是频道还是用户
        if update.message.sender_chat:
            # 频道发言
            target_user_id = update.message.sender_chat.id
        elif update.effective_user:
            # 用户发言
            target_user_id = update.effective_user.id
        else:
            return await update.message.reply_text("❌ 无法确定发送者")

        # 没有指定用户时，第一个参数（如果有）就是风格
        if context.args:
            style = context.args[0]
    else:
        target_user_id, _, _ = user_info
        # 指定了用户时，提取风格参数
        if context.args:
            # 如果是回复消息，第一个参数就是风格
            if update.message.reply_to_message:
                style = context.args[0]
            # 如果通过参数指定用户，第二个参数才是风格
            elif len(context.args) > 1:
                style = context.args[1]

    status_msg = await update.message.reply_text(f"🔄 正在分析用户画像（{style}），请稍候...")

    # 创建后台任务，避免阻塞其他 update 处理
    asyncio.create_task(
        _analyze_user_background(
            chat_id=update.effective_chat.id,
            status_message_id=status_msg.message_id,
            group_id=group.id,
            target_user_id=target_user_id,
            style=style,
            context=context
        )
    )


async def _analyze_user_background(
    chat_id: int,
    status_message_id: int,
    group_id: int,
    target_user_id: int,
    style: str,
    context: ContextTypes.DEFAULT_TYPE
):
    """后台执行用户画像分析，避免阻塞主事件循环"""
    try:
        # 获取用户/频道的详细信息用于显示
        with Session(engine) as session:
            statement = select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.user_id == target_user_id
            )
            member = session.exec(statement).first()

        # 构建用户标识显示
        if member:
            username = member.username
            full_name = member.full_name or "未知"

            # 判断是否是频道（ID为负数）
            is_channel = target_user_id < 0

            if is_channel:
                # 频道：显示 @username 或频道名称
                user_display = f"@{username}" if username else full_name
            else:
                # 普通用户：统一使用蓝色可点击链接
                user_display = f"[{full_name}](tg://user?id={target_user_id})"
        else:
            # 数据库中找不到，使用ID
            user_display = f"用户 {target_user_id}"

        # 分析用户画像
        profile_text = await user_profile_analyzer.analyze_user_profile(
            group_db_id=group_id,
            user_id=target_user_id,
            style=style
        )

        result_text = (
            f"👤 用户画像分析（{style}）\n\n"
            f"分析对象: {user_display}\n"
            f"ID: `{target_user_id}`\n\n"
            f"{profile_text}"
        )

        # 删除状态消息
        await context.bot.delete_message(chat_id=chat_id, message_id=status_message_id)

        # 发送结果消息（使用 Markdown 解析模式）
        result_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=result_text,
            parse_mode="Markdown"
        )

        # 设置自动删除（300秒后）
        await asyncio.sleep(300)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=result_msg.message_id)
        except Exception:
            pass  # 消息可能已被手动删除

    except Exception as e:
        logger.exception(f"分析用户画像失败:", e)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=status_message_id)
            await context.bot.send_message(chat_id=chat_id, text=f"❌ 分析失败: {str(e)}")
        except Exception:
            pass
