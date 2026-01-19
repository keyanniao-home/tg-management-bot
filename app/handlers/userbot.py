"""
User Bot 命令处理器

提供基于 User Bot 的功能命令，用于补充 Bot API 无法实现的功能
"""

from telegram import Update
from telegram.ext import ContextTypes
from loguru import logger
from sqlmodel import Session, select

from app.config.settings import settings
from app.database.connection import engine
from app.models import GroupConfig, GroupAdmin
from app.services.userbot import userbot_client, MemberImportService, crawler_queue


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


async def import_members_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    导入当前群组成员命令
    使用 User Bot 拉取群组成员并导入数据库

    用法: /kobe_import_members
    """
    # 检查是否是管理员，非管理员直接返回
    if not await is_admin(update):
        return None

    # 检查是否启用 User Bot
    if not settings.is_userbot_configured:
        return await update.message.reply_text(
            "❌ User Bot 功能未启用\n\n"
            "启用步骤：\n"
            "1. 在 .env 中配置 USERBOT_API_ID 和 USERBOT_API_HASH\n"
            "2. 运行 python userbot_login.py 登录\n"
            "3. 在 .env 中设置 USERBOT_ENABLED=true"
        )

    # 检查客户端连接状态
    if not userbot_client.is_connected():
        return await update.message.reply_text("❌ User Bot 客户端未连接")

    # 只支持当前群组
    target_group = update.effective_chat.id

    status_msg = await update.message.reply_text("🔄 正在拉取群组成员...")

    try:
        # 创建成员导入服务
        import_service = MemberImportService()

        # 定义进度回调
        async def progress_callback(current: int, total: int):
            if current % 100 == 0:
                percent = (current / total) * 100
                await status_msg.edit_text(
                    f"🔄 正在导入成员...\n"
                    f"进度: {current}/{total} ({percent:.1f}%)"
                )

        # 执行导入
        result = await import_service.import_members(
            target_group,
            userbot_client,
            progress_callback=progress_callback
        )

        # 显示结果
        return await status_msg.edit_text(
            f"✅ 导入完成！\n\n"
            f"群组: {result['group_name']}\n"
            f"群组ID: {result['group_id']}\n\n"
            f"总成员数: {result['total']}\n"
            f"新增: {result['added']}\n"
            f"更新: {result['updated']}\n"
            f"跳过: {result['skipped']}\n"
            + (f"错误: {result['error']}\n" if result['error'] > 0 else "")
        )

    except Exception as e:
        logger.error(f"导入成员失败: {e}")
        return await status_msg.edit_text(f"❌ 导入失败: {str(e)}")


async def crawl_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    爬取群组用户信息和频道命令

    用法:
    - /kobe_crawl_users [--channels] [--depth=10]  # 爬取整个群
    - /kobe_crawl_users @username [--channels] [--depth=10]  # 爬取指定用户
    - /kobe_crawl_users 123456 [--channels] [--depth=10]  # 通过ID爬取
    - 回复消息后 /kobe_crawl_users [--channels] [--depth=10]  # 爬取被回复的用户
    """
    # 检查是否是管理员，非管理员直接返回
    if not await is_admin(update):
        return None

    # 检查是否启用 User Bot
    if not settings.is_userbot_configured:
        return await update.message.reply_text(
            "❌ User Bot 功能未启用\n\n"
            "启用步骤：\n"
            "1. 在 .env 中配置 USERBOT_API_ID 和 USERBOT_API_HASH\n"
            "2. 运行 python userbot_login.py 登录\n"
            "3. 在 .env 中设置 USERBOT_ENABLED=true"
        )

    # 检查客户端连接状态
    if not userbot_client.is_connected():
        return await update.message.reply_text("❌ User Bot 客户端未连接")

    # 解析参数
    args = context.args or []
    crawl_channels = "--channels" in args
    channel_depth = 10  # 默认深度

    # 过滤出非选项参数
    user_args = [arg for arg in args if not arg.startswith("--")]

    for arg in args:
        if arg.startswith("--depth="):
            try:
                channel_depth = int(arg.split("=")[1])
                if channel_depth < 1 or channel_depth > 100:
                    return await update.message.reply_text("❌ 深度必须在 1-100 之间")
            except ValueError:
                return await update.message.reply_text("❌ 深度参数格式错误")

    # 获取群组配置
    with Session(engine) as session:
        statement = select(GroupConfig).where(GroupConfig.group_id == update.effective_chat.id)
        group = session.exec(statement).first()

        if not group:
            return await update.message.reply_text("❌ 群组未初始化")

        # 解析目标用户（如果指定了）
        target_user_id = None
        target_username = None

        # 检查是否是回复消息
        if update.message.reply_to_message and update.message.reply_to_message.from_user:
            target_user_id = update.message.reply_to_message.from_user.id
            target_username = update.message.reply_to_message.from_user.username
        # 检查是否提供了用户参数
        elif user_args:
            from app.utils.user_resolver import UserResolver
            user_info = UserResolver.resolve_with_db(update, user_args, session, group.id)
            if user_info:
                target_user_id, target_username, _ = user_info
            else:
                return await update.message.reply_text("❌ 无法找到指定用户")

    # 如果指定了用户，直接爬取该用户（不使用队列）
    if target_user_id:
        status_text = (
            f"🔄 开始爬取用户信息\n\n"
            f"用户ID: {target_user_id}\n"
            + (f"用户名: @{target_username}\n" if target_username else "") +
            f"爬取频道: {'是' if crawl_channels else '否'}\n"
        )
        if crawl_channels:
            status_text += f"频道深度: {channel_depth}\n"

        status_msg = await update.message.reply_text(status_text)

        try:
            from app.services.userbot.user_crawler import UserCrawler
            from app.services.userbot.channel_crawler import ChannelCrawler

            user_crawler = UserCrawler(userbot_client, min_delay=0, max_delay=2)  # 测试时使用短延迟
            channel_crawler = ChannelCrawler(userbot_client)

            # 使用和群组爬取相同的方法：crawl_user_with_delay
            profile = await user_crawler.crawl_user_with_delay(target_user_id)

            if not profile:
                return await status_msg.edit_text(f"❌ 爬取用户 {target_user_id} 失败")

            result_text = (
                f"✅ 用户信息爬取完成！\n\n"
                f"用户ID: {target_user_id}\n"
            )

            if profile.username:
                result_text += f"用户名: @{profile.username}\n"

            if profile.first_name:
                full_name = f"{profile.first_name or ''} {profile.last_name or ''}".strip()
                result_text += f"姓名: {full_name}\n"

            if profile.bio:
                if len(profile.bio) > 50:
                    result_text += f"简介: {profile.bio[:50]}...\n"
                else:
                    result_text += f"简介: {profile.bio}\n"

            # 显示是否有个人频道
            if profile.has_personal_channel:
                result_text += f"个人频道: 有 (ID: {profile.personal_channel_id})\n"

            # 如果需要爬取频道
            if crawl_channels and profile.has_personal_channel:
                await status_msg.edit_text(result_text + "\n🔄 正在爬取个人频道...")

                channel_count = await channel_crawler.crawl_user_channels(
                    target_user_id,
                    crawl_messages=True,
                    message_depth=channel_depth
                )

                if channel_count:
                    result_text += f"\n✅ 已爬取 {channel_count} 个频道"

            return await status_msg.edit_text(result_text)

        except Exception as e:
            logger.exception(f"爬取用户 {target_user_id} 失败: ",e)
            return await status_msg.edit_text(f"❌ 爬取失败: {str(e)}")

    # 没有指定用户，爬取整个群
    status_text = (
        f"🔄 开始爬取群组用户信息\n\n"
        f"爬取频道: {'是' if crawl_channels else '否'}\n"
    )
    if crawl_channels:
        status_text += f"频道深度: {channel_depth}\n"

    status_text += f"\n正在初始化任务..."

    status_msg = await update.message.reply_text(status_text)

    try:
        # 获取创建者信息
        if update.message.sender_chat:
            creator_id = update.message.sender_chat.id
            creator_username = update.message.sender_chat.username
        else:
            creator_id = update.effective_user.id
            creator_username = update.effective_user.username

        # 添加到爬虫队列
        task = await crawler_queue.add_task(
            group_id=group.id,
            crawl_channels=crawl_channels,
            channel_depth=channel_depth,
            created_by_user_id=creator_id,
            created_by_username=creator_username,
            status_chat_id=update.effective_chat.id,
            status_message_id=status_msg.message_id
        )

        return await status_msg.edit_text(
            f"✅ 任务已创建 #{task.id}\n\n"
            f"总用户数: {task.total_users}\n"
            f"爬取频道: {'是' if crawl_channels else '否'}\n"
            + (f"频道深度: {channel_depth}\n" if crawl_channels else "") +
            f"\n任务已加入队列，请稍候...\n"
            f"预计耗时: {task.total_users * 30 // 60} 分钟"
        )

    except Exception as e:
        logger.error(f"创建爬取任务失败: {e}")
        return await status_msg.edit_text(f"❌ 创建任务失败: {str(e)}")

