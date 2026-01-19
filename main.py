import uuid
from loguru import logger
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)
from app.config.settings import settings
from app.database.connection import create_db_and_tables
from app.handlers.commands import (
    help_command,
    config_command,
    ban_command,
    unban_command,
    kick_command,
    setadmin_command,
    admins_command,
    id_command,
    init_command,
    whitelist_command,
    unwhitelist_command,
    whitelists_command,
    removeadmin_command,
)
from app.handlers.stats import inactive_command, inactive_callback
from app.handlers.bind import bd_command, handle_start_command
from app.handlers.leaderboard import leaderboard_command, leaderboard_callback
from app.handlers.events import (
    on_chat_member_updated,
    on_message,
    check_unbound_channel,
)
from app.handlers.userbot import import_members_command, crawl_users_command
from app.handlers.ai import (
    analyze_user_command,
    detect_scammer_command,
    handle_scammer_confirmation,
    handle_scammer_page_callback,
)
from app.handlers.points_handlers import (
    checkin_command,
    points_command,
    points_rank_command,
    points_rules_command,
)
from app.handlers.summary_handlers import (
    summary_command,
    search_user_messages_command,
    search_messages_command,
)
from app.handlers.dm_handlers import dm_command, dm_handlers, my_dms_command
from app.handlers.dm_rating_handlers import dm_rating_command, dm_rating_callback
from app.handlers.message_query_handlers import (
    query_messages_command,
    query_messages_callback,
    handle_user_id_input,
)
from app.handlers.digest_config_handlers import (
    digest_config_command,
    digest_config_callback,
)
from app.handlers.ai_summary_handlers import (
    ai_summary_command,
    ai_summary_callback,
    handle_summary_user_id_input,
)

# 导入新增的resource handlers
from app.handlers.resource_handlers import (
    upload_conversation,
    search_command,
    add_category_command,
    add_tag_command,
    list_categories_command,
    list_tags_command,
    get_resource_command,
    resources_command,
    resources_callback,
    delete_resource_command,
)
from app.handlers.category_management_handlers import (
    manage_categories_command,
    manage_tags_command,
    category_management_callback,
    tag_management_callback,
    handle_category_edit_input,
    handle_tag_edit_input,
)
from app.handlers.resource_management_handlers import (
    manage_resources_command,
    manage_resources_callback,
)

from app.services.image_queue import image_queue
from app.services.image_detector import image_detector
from app.services.userbot import userbot_client, crawler_queue

# 全局初始化密钥（在程序启动时生成）
INIT_SECRET_KEY = str(uuid.uuid4())


async def post_init(application: Application):
    """Application 初始化后的钩子，在事件循环中运行"""

    # 设置 Bot 命令列表（输入 / 时自动弹出）
    from telegram import BotCommand

    commands = [
        BotCommand("help", "显示帮助信息"),
        BotCommand("checkin", "每日签到"),
        BotCommand("points", "查看我的积分"),
        BotCommand("points_rank", "积分排行榜"),
        BotCommand("search_user", "搜索用户消息"),
        BotCommand("summary", "AI总结群组消息"),
        BotCommand("resources", "资源浏览面板"),
        BotCommand("search", "搜索资源"),
        BotCommand("upload", "上传文件资源"),
        BotCommand("id", "查询用户信息"),
        BotCommand("leaderboard", "发言排行榜"),
        BotCommand("bd", "绑定频道"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot 命令列表已设置")

    image_queue.start()
    logger.info("图片检测队列已启动")

    # 启动 User Bot（如果已配置）
    if settings.is_userbot_configured:
        success = await userbot_client.start(
            api_id=settings.userbot_api_id,
            api_hash=settings.userbot_api_hash,
            session_path=settings.userbot_session_path,
        )
        if not success:
            logger.warning("User Bot 启动失败，相关功能将不可用")
        else:
            # 启动爬虫队列
            crawler_queue.set_bot(application.bot)
            crawler_queue.start()
            logger.info("爬虫队列已启动")
    else:
        logger.info("User Bot 未配置，跳过启动")


async def post_shutdown(application: Application):
    """Application 关闭后的钩子"""
    await image_queue.stop()
    logger.info("图片检测队列已停止")

    image_detector.shutdown()
    logger.info("图片检测服务已停止")

    # 停止爬虫队列和 User Bot
    if settings.is_userbot_configured:
        await crawler_queue.stop()
        logger.info("爬虫队列已停止")

        await userbot_client.stop()


def main():
    """初始化数据库并启动Telegram Bot"""
    logger.info("正在初始化数据库...")
    create_db_and_tables()
    logger.info("数据库初始化完成!")

    # 打印初始化密钥
    logger.info("=" * 80)
    logger.info(f"🔑 初始化密钥（请妥善保管）: {INIT_SECRET_KEY}")
    logger.info("=" * 80)

    # 创建Application，并注册生命周期钩子
    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # 将密钥存储到 bot_data 中供其他处理器使用
    application.bot_data["init_secret_key"] = INIT_SECRET_KEY

    # 注册命令处理器
    application.add_handler(CommandHandler("start", handle_start_command))
    application.add_handler(CommandHandler("init", init_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("config", config_command))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("kick", kick_command))
    application.add_handler(CommandHandler("setadmin", setadmin_command))
    application.add_handler(CommandHandler("removeadmin", removeadmin_command))
    application.add_handler(CommandHandler("admins", admins_command))
    application.add_handler(CommandHandler("whitelist", whitelist_command))
    application.add_handler(CommandHandler("unwhitelist", unwhitelist_command))
    application.add_handler(CommandHandler("whitelists", whitelists_command))
    application.add_handler(CommandHandler("id", id_command))
    application.add_handler(CommandHandler("inactive", inactive_command))
    application.add_handler(CommandHandler("bd", bd_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("import_members", import_members_command))
    application.add_handler(CommandHandler("crawl_users", crawl_users_command))
    application.add_handler(CommandHandler("analyze_user", analyze_user_command))
    application.add_handler(CommandHandler("detect_scammer", detect_scammer_command))

    # 新功能命令
    application.add_handler(CommandHandler("checkin", checkin_command))
    application.add_handler(CommandHandler("points", points_command))
    application.add_handler(CommandHandler("points_rank", points_rank_command))
    application.add_handler(CommandHandler("points_rules", points_rules_command))

    # 消息总结和搜索
    application.add_handler(CommandHandler("summary", summary_command))
    application.add_handler(CommandHandler("search_user", search_user_messages_command))
    application.add_handler(CommandHandler("search_messages", search_messages_command))

    # 可视化查询和配置面板
    application.add_handler(CommandHandler("query_messages", query_messages_command))
    application.add_handler(CommandHandler("digest_config", digest_config_command))
    application.add_handler(CommandHandler("ai_summary", ai_summary_command))

    # DM命令
    application.add_handler(CommandHandler("dm", dm_command))
    application.add_handler(CommandHandler("my_dms", my_dms_command))
    application.add_handler(CommandHandler("dm_rating", dm_rating_command))
    application.add_handler(
        CallbackQueryHandler(dm_rating_callback, pattern="^dm_rank_")
    )

    # 资源管理命令
    application.add_handler(upload_conversation)
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("add_category", add_category_command))
    application.add_handler(CommandHandler("add_tag", add_tag_command))
    application.add_handler(CommandHandler("categories", list_categories_command))
    application.add_handler(CommandHandler("tags", list_tags_command))
    application.add_handler(CommandHandler("resources", resources_command))
    application.add_handler(CommandHandler("delete_resource", delete_resource_command))
    application.add_handler(
        CommandHandler("manage_categories", manage_categories_command)
    )
    application.add_handler(CommandHandler("manage_tags", manage_tags_command))
    application.add_handler(
        CommandHandler("manage_resources", manage_resources_command)
    )

    # 资源获取（动态匹配 /get_数字）
    application.add_handler(
        MessageHandler(filters.Regex(r"^/get_\d+"), get_resource_command)
    )

    # 注册回调查询处理器（分页按钮）
    application.add_handler(
        CallbackQueryHandler(inactive_callback, pattern="^inactive:")
    )
    application.add_handler(CallbackQueryHandler(leaderboard_callback, pattern="^lb_"))
    application.add_handler(
        CallbackQueryHandler(handle_scammer_page_callback, pattern="^scammer_page:")
    )

    # 资源面板回调（包含筛选功能）
    application.add_handler(
        CallbackQueryHandler(
            resources_callback,
            pattern="^(get_res_|res_page_|res_send_|res_del_|filter_)",
        )
    )

    # 分类和标签管理回调
    application.add_handler(
        CallbackQueryHandler(category_management_callback, pattern="^cat_")
    )
    application.add_handler(
        CallbackQueryHandler(tag_management_callback, pattern="^tag_")
    )
    application.add_handler(
        CallbackQueryHandler(manage_resources_callback, pattern="^mgmt_res_")
    )

    # 查询面板回调
    application.add_handler(
        CallbackQueryHandler(query_messages_callback, pattern="^qmsg_")
    )
    application.add_handler(
        CallbackQueryHandler(digest_config_callback, pattern="^digest_")
    )
    application.add_handler(
        CallbackQueryHandler(ai_summary_callback, pattern="^aisum_")
    )

    # 用户输入处理器（查询和AI总结的用户ID输入，分类标签编辑）
    # 使用 group=-2 确保在消息记录之前处理，但不阻止消息继续传播
    async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理文本输入，不阻止消息传播"""
        await handle_user_id_input(update, context)
        await handle_summary_user_id_input(update, context)
        await handle_category_edit_input(update, context)
        await handle_tag_edit_input(update, context)
        # 不返回任何值，让消息继续传播到 on_message

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input), group=-2
    )

    # 注册DM相关的回调处理器
    for handler in dm_handlers:
        application.add_handler(handler)

    # 注册事件监听器（优先级很重要！）
    # 1. 最高优先级：检查未绑定频道消息（group=-1，最先执行）
    application.add_handler(
        MessageHandler(filters.ALL, check_unbound_channel), group=-1
    )

    # 2. 正常优先级：其他事件处理器
    # 使用 ChatMemberHandler 监听成员状态变化（加入、离开等）
    application.add_handler(
        ChatMemberHandler(on_chat_member_updated, ChatMemberHandler.MY_CHAT_MEMBER)
    )

    # 监听话题创建事件
    from app.handlers.events import on_forum_topic_created

    application.add_handler(
        MessageHandler(filters.StatusUpdate.FORUM_TOPIC_CREATED, on_forum_topic_created)
    )

    # 3. 最低优先级：通用消息处理器（group=0，最后执行）文本、图片、视频、语音、贴纸、文件等，排除命令）
    application.add_handler(MessageHandler(~filters.COMMAND, on_message))

    logger.info("Bot启动成功，开始监听...")
    # 启动Bot
    application.run_polling(
        allowed_updates=["message", "chat_member", "callback_query"]
    )


if __name__ == "__main__":
    main()
