from datetime import datetime, timedelta, UTC, timezone
from telegram import Update
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown
from sqlmodel import Session, select
from sqlalchemy.orm.attributes import flag_modified
from app.models import ChannelBinding
from app.database.connection import engine
from app.models import GroupConfig, GroupAdmin, GroupMember, BanRecord
from app.utils.user_resolver import UserResolver
from app.utils.auto_delete import auto_delete_message


@auto_delete_message(delay=30)
async def init_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /kobe_init <密钥>
    初始化群组，执行者（用户或频道）成为超级管理员
    要求：提供正确的初始化密钥
    """
    # 先检查群组是否已经初始化
    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()

        if group and group.is_initialized:
            # 已经初始化，啥也不做，不响应
            return None

    # 验证密钥
    if not context.args or len(context.args) != 1:
        return await update.message.reply_text(
            "❌ 请提供初始化密钥\n\n用法: /kobe_init <密钥>"
        )

    provided_key = context.args[0]
    init_secret_key = context.bot_data.get("init_secret_key")

    if provided_key != init_secret_key:
        return await update.message.reply_text("❌ 密钥错误", parse_mode="Markdown")

    # 判断是用户还是频道执行
    is_channel = update.message.sender_chat is not None

    if is_channel:
        # 频道发言
        executor_id = update.message.sender_chat.id
        executor_name = update.message.sender_chat.title or "Unknown Channel"
        executor_username = update.message.sender_chat.username
    else:
        # 用户发言
        executor_id = update.effective_user.id
        executor_name = update.effective_user.full_name or "Unknown"
        executor_username = update.effective_user.username

    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()

        # 创建或更新群组配置
        if not group:
            group = GroupConfig(
                group_id=update.effective_chat.id,
                group_name=update.effective_chat.title or "Unknown",
                is_initialized=True,
                initialized_by_user_id=executor_id,
            )
            session.add(group)
            session.commit()
            session.refresh(group)
        else:
            group.is_initialized = True
            group.initialized_by_user_id = executor_id
            group.updated_at = datetime.now(UTC)
            session.add(group)
            session.commit()
            session.refresh(group)

            # 清除该群组的配置缓存
            from app.utils.channel_cache import group_config_cache

            group_config_cache.invalidate(update.effective_chat.id)

        # 设置初始化者为超级管理员
        statement = select(GroupAdmin).where(
            GroupAdmin.group_id == group.id, GroupAdmin.user_id == executor_id
        )
        admin = session.exec(statement).first()

        if not admin:
            admin = GroupAdmin(
                group_id=group.id,
                user_id=executor_id,
                username=executor_username,
                full_name=executor_name,
                permission_level=1,  # 超级管理员
                appointed_by_user_id=None,  # 自己初始化
            )
            session.add(admin)
            session.commit()

        executor_mention = (
            f"[{executor_name}](tg://user?id={executor_id})"
            if not is_channel
            else f"频道 {executor_name}"
        )

        return await update.message.reply_text(
            f"✅ 群组初始化成功！\n\n初始化者 {executor_mention} 已成为超级管理员",
            parse_mode="Markdown",
        )


def format_help_text() -> str:
    """生成帮助文档文本"""
    e = lambda t: escape_markdown(t, version=2)

    return f"""🤖 *群组管理机器人*

*📝 消息查询与总结*
{e("/summary [小时数] - AI总结群组消息（默认从上次发言到现在）")}
{e("/search_messages [小时数] - 查询时间段内所有消息统计（默认24小时）")}
{e("/search_user <user_id> [小时数] - 搜索特定用户的消息（默认24小时）")}
{e("  示例: /search_user 123456789 48")}
{e("/query_messages - 🆕 可视化消息查询面板")}
{e("/ai_summary - 🆕 AI总结可视化面板")}
{e("/digest_config - 🆕 每日推送配置面板（管理员）")}

*📁 文件资源管理*
{e("/upload - 上传文件资源（回复包含文件的消息）")}
{e("/resources - 打开资源浏览面板")}
{e("/search <关键词> - 搜索资源")}
{e("/get_<id> - 获取指定ID的资源")}
{e("/delete_resource <id> - 删除资源（上传者或管理员）")}
{e("/categories - 查看所有分类")}
{e("/tags - 查看所有标签")}
{e("/add_category <名称> [描述] - 添加分类（管理员）")}
{e("/add_tag <名称> - 添加标签（管理员）")}
{e("/manage_categories - 分类管理面板（管理员）")}
{e("/manage_tags - 标签管理面板（管理员）")}
{e("/manage_resources - 资源管理面板（管理员）")}
{e("💡 上传时可直接创建新分类和标签")}

*💬 私信转达系统*
{e("/dm <user_id> <消息> - 向指定用户发送私信")}
{e("  示例: /dm 123456789 你好")}
{e("/my_dms - 查看我的私信列表")}
{e("💡 接收者需先私聊Bot发送 /start")}

*👮 群组管理*
{e("/id [用户] - 查看用户详细信息")}
{e("/admins - 查看管理员列表")}
{e("/setadmin [用户] - 设置管理员（仅超级管理员）")}
{e("/ban [用户] - 永久封禁用户")}
{e("/unban [用户] - 解封用户")}
{e("/kick [用户] - 踢出用户（可再次加入）")}
{e("/inactive [天数] - 查看未发言用户")}

*📊 积分与统计*
{e("/checkin - 每日签到")}
{e("/points - 查看我的积分")}
{e("/leaderboard 或 /榜单 - 查看群组榜单")}

*⚙️ 其他命令*
{e("/config 键名 值 - 配置群组参数（管理员）")}
{e("/help - 显示此帮助信息")}

*💡 用户指定方式*
{e("• @username - 使用用户名")}
{e("• 用户ID - 直接输入数字ID")}
{e("• 回复消息 - 回复某条消息后使用命令")}"""


@auto_delete_message(delay=30, custom_delays={"stats": 120, "inactive": 240})
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    显示帮助信息

    说明：
    - 仅管理员可查看帮助
    - 消息会在30秒后自动删除
    """
    if not await is_admin(update):
        return None

    return await update.message.reply_text(format_help_text(), parse_mode="MarkdownV2")


async def is_admin(update: Update) -> bool:
    """检查用户或频道是否是管理员"""
    # 判断是频道消息还是用户消息
    if update.message.sender_chat:
        # 频道消息
        check_id = update.message.sender_chat.id
    elif update.effective_user:
        # 用户消息
        check_id = update.effective_user.id
    else:
        return False

    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()
        if not group:
            return False

        statement = select(GroupAdmin).where(
            GroupAdmin.group_id == group.id,
            GroupAdmin.user_id == check_id,
            GroupAdmin.is_active == True,
        )
        admin = session.exec(statement).first()
        return admin is not None


@auto_delete_message(delay=30, custom_delays={"stats": 120, "inactive": 240})
async def config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /config 键名 值
    设置群组配置
    """
    if not await is_admin(update):
        return None

    args = context.args
    if len(args) < 2:
        return await update.message.reply_text("用法: /config 键名 值")

    key = args[0]
    value = " ".join(args[1:])

    # 尝试解析为JSON（支持数组和对象）
    import json

    try:
        value = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        # 如果不是JSON，处理布尔值
        if value.lower() in ["true", "1", "yes", "on"]:
            value = True
        elif value.lower() in ["false", "0", "no", "off"]:
            value = False

    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()

        if not group:
            return await update.message.reply_text("群组未初始化")

        # 修改配置（支持点分隔的嵌套路径）
        if "." in key:
            # 嵌套配置，使用点分隔路径
            keys = key.split(".")
            current = group.config
            for k in keys[:-1]:
                if k not in current:
                    current[k] = {}
                current = current[k]
            current[keys[-1]] = value
        else:
            # 简单配置
            group.config[key] = value
        # 标记字段已修改（重要！）
        flag_modified(group, "config")
        group.updated_at = datetime.now(UTC)
        session.add(group)
        session.commit()

        # 清除该群组的配置缓存
        from app.utils.channel_cache import group_config_cache

        group_config_cache.invalidate(update.effective_chat.id)

        return await update.message.reply_text(f"配置已更新: {key} = {value}")


@auto_delete_message(delay=30, custom_delays={"stats": 120, "inactive": 240})
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /ban [用户ID/@用户名/回复消息]
    永久封禁用户
    如果指定的是频道ID，会自动查找绑定的用户并封禁
    """
    if not await is_admin(update):
        return None

    args = context.args

    # 从数据库获取群组信息
    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()
        if not group:
            return await update.message.reply_text("群组未初始化")

        # 解析目标用户（传入session和group.id用于@username查询）
        user_info = UserResolver.resolve(update, args, session, group.id)
        if not user_info:
            return await update.message.reply_text(
                "无法识别目标用户，请使用 /ban [天数] 用户ID/@用户名 或回复消息"
            )

        target_user_id, target_username, target_full_name = user_info

        # 如果是频道ID（负数），查找绑定的用户（全局共享）
        if target_user_id < 0:
            statement = select(ChannelBinding).where(
                ChannelBinding.channel_id == target_user_id
            )
            binding = session.exec(statement).first()

            if not binding:
                return await update.message.reply_text(f"❌ 该频道未绑定用户，无法封禁")

            # 使用绑定的用户ID
            target_user_id = binding.user_id
            target_username = binding.user_username
            target_full_name = binding.user_full_name

        # 检查白名单（管理员、群组白名单、全局白名单）
        from app.config.settings import settings

        statement = select(GroupAdmin).where(
            GroupAdmin.group_id == group.id,
            GroupAdmin.user_id == target_user_id,
            GroupAdmin.is_active == True,
        )
        if session.exec(statement).first():
            return await update.message.reply_text("❌ 无法封禁管理员")

        if (
            target_user_id in group.whitelist
            or target_user_id in settings.global_whitelist_ids
        ):
            return await update.message.reply_text("❌ 该用户在白名单中，无法封禁")

        # 如果只有ID，从数据库获取其他信息
        if not target_full_name:
            statement = select(GroupMember).where(
                GroupMember.group_id == group.id, GroupMember.user_id == target_user_id
            )
            member = session.exec(statement).first()
            if member:
                target_username = member.username
                target_full_name = member.full_name

        # 创建封禁记录
        ban = BanRecord(
            group_id=group.id,
            user_id=target_user_id,
            username=target_username,
            full_name=target_full_name or "Unknown",
            ban_days=None,  # 永久封禁
            banned_by_admin_id=update.effective_user.id,
        )
        session.add(ban)
        session.commit()

        # 执行永久封禁
        try:
            await context.bot.ban_chat_member(
                chat_id=update.effective_chat.id, user_id=target_user_id
            )
            return await update.message.reply_text(
                f"已永久封禁用户 {target_full_name} ({target_user_id})"
            )
        except Exception as e:
            return await update.message.reply_text(f"封禁失败: {str(e)}")


@auto_delete_message(delay=30, custom_delays={"stats": 120, "inactive": 240})
async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /unban [用户ID/@用户名/回复消息]
    解封用户
    """
    if not await is_admin(update):
        return None

    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()
        if not group:
            return await update.message.reply_text("群组未初始化")

        # 解析目标用户
        user_info = UserResolver.resolve(update, context.args, session, group.id)
        if not user_info:
            return await update.message.reply_text("无法识别目标用户")

        target_user_id, _, target_full_name = user_info

        # 更新封禁记录
        statement = select(BanRecord).where(
            BanRecord.group_id == group.id,
            BanRecord.user_id == target_user_id,
            BanRecord.is_active == True,
        )
        ban = session.exec(statement).first()
        if ban:
            ban.is_active = False
            ban.unbanned_at = datetime.now(UTC)
            session.add(ban)
            session.commit()

    # 执行解封
    try:
        await context.bot.unban_chat_member(
            chat_id=update.effective_chat.id, user_id=target_user_id
        )
        return await update.message.reply_text(
            f"已解封用户 {target_full_name} ({target_user_id})"
        )
    except Exception as e:
        return await update.message.reply_text(f"解封失败: {str(e)}")


@auto_delete_message(delay=30, custom_delays={"stats": 120, "inactive": 240})
async def kick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /kick [用户ID/@用户名/回复消息]
    踢出用户但不封禁
    如果指定的是频道ID，会自动查找绑定的用户并踢出
    """
    if not await is_admin(update):
        return None

    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()
        if not group:
            return await update.message.reply_text("群组未初始化")

        # 解析目标用户
        user_info = UserResolver.resolve(update, context.args, session, group.id)
        if not user_info:
            return await update.message.reply_text("无法识别目标用户")

        target_user_id, target_username, target_full_name = user_info

        # 如果是频道ID（负数），查找绑定的用户（全局共享）
        if target_user_id < 0:
            statement = select(ChannelBinding).where(
                ChannelBinding.channel_id == target_user_id
            )
            binding = session.exec(statement).first()

            if not binding:
                return await update.message.reply_text(f"❌ 该频道未绑定用户，无法踢出")

            # 使用绑定的用户ID
            target_user_id = binding.user_id
            target_username = binding.user_username
            target_full_name = binding.user_full_name

    # 检查白名单（管理员、群组白名单、全局白名单）
    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()
        if not group:
            return await update.message.reply_text("群组未初始化")

        from app.config.settings import settings

        statement = select(GroupAdmin).where(
            GroupAdmin.group_id == group.id,
            GroupAdmin.user_id == target_user_id,
            GroupAdmin.is_active == True,
        )
        if session.exec(statement).first():
            return await update.message.reply_text("❌ 无法踢出管理员")

        if (
            target_user_id in group.whitelist
            or target_user_id in settings.global_whitelist_ids
        ):
            return await update.message.reply_text("❌ 该用户在白名单中，无法踢出")

    try:
        # 先封禁再解封，相当于踢出
        await context.bot.ban_chat_member(
            chat_id=update.effective_chat.id, user_id=target_user_id
        )
        await context.bot.unban_chat_member(
            chat_id=update.effective_chat.id, user_id=target_user_id
        )
        return await update.message.reply_text(
            f"已踢出用户 {target_full_name} ({target_user_id})"
        )
    except Exception as e:
        return await update.message.reply_text(f"踢出失败: {str(e)}")


@auto_delete_message(delay=30, custom_delays={"stats": 120, "inactive": 240})
async def setadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /setadmin [用户ID/@用户名/回复消息]
    设置用户为管理员（需要超级管理员权限）
    支持用户或频道身份执行
    """
    # 判断执行者是用户还是频道
    if update.message.sender_chat:
        executor_id = update.message.sender_chat.id
    elif update.effective_user:
        executor_id = update.effective_user.id
    else:
        return await update.message.reply_text("无法识别执行者")

    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()
        if not group:
            return await update.message.reply_text("群组未初始化")

        # 检查是否是超级管理员
        statement = select(GroupAdmin).where(
            GroupAdmin.group_id == group.id,
            GroupAdmin.user_id == executor_id,
            GroupAdmin.permission_level == 1,
            GroupAdmin.is_active == True,
        )
        super_admin = session.exec(statement).first()

        if not super_admin:
            return None

        # 解析目标用户
        user_info = UserResolver.resolve(update, context.args, session, group.id)
        if not user_info:
            return await update.message.reply_text("无法识别目标用户")

        target_user_id, target_username, target_full_name = user_info

        # 从数据库获取完整用户信息
        if not target_full_name:
            statement = select(GroupMember).where(
                GroupMember.group_id == group.id, GroupMember.user_id == target_user_id
            )
            member = session.exec(statement).first()
            if member:
                target_username = member.username
                target_full_name = member.full_name

        # 检查是否已经是管理员
        statement = select(GroupAdmin).where(
            GroupAdmin.group_id == group.id,
            GroupAdmin.user_id == target_user_id,
            GroupAdmin.is_active == True,
        )
        existing_admin = session.exec(statement).first()

        if existing_admin:
            # 判断是频道还是用户
            if target_user_id < 0:
                user_mention = (
                    f"@{target_username}" if target_username else target_full_name
                )
            else:
                user_mention = f"[{target_full_name}](tg://user?id={target_user_id})"
            return await update.message.reply_text(
                f"{user_mention} 已经是管理员", parse_mode="Markdown"
            )

        # 创建管理员
        new_admin = GroupAdmin(
            group_id=group.id,
            user_id=target_user_id,
            username=target_username,
            full_name=target_full_name or "Unknown",
            permission_level=2,  # 普通管理员
            appointed_by_user_id=executor_id,
        )
        session.add(new_admin)
        session.commit()

        # 判断是频道还是用户
        if target_user_id < 0:
            user_mention = (
                f"@{target_username}" if target_username else target_full_name
            )
        else:
            user_mention = f"[{target_full_name}](tg://user?id={target_user_id})"

        return await update.message.reply_text(
            f"✅ 已将 {user_mention} 设置为管理员", parse_mode="Markdown"
        )


@auto_delete_message(delay=30, custom_delays={"stats": 120, "inactive": 240})
async def admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admins
    查看当前群组的管理员列表
    """
    if not await is_admin(update):
        return None
    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()

        if not group:
            return await update.message.reply_text("群组未初始化")

        # 查询所有激活的管理员
        statement = (
            select(GroupAdmin)
            .where(GroupAdmin.group_id == group.id, GroupAdmin.is_active == True)
            .order_by(GroupAdmin.permission_level)
        )

        admins = session.exec(statement).all()

        if not admins:
            return await update.message.reply_text("当前群组没有管理员")

        # 格式化输出
        message = "👮 群组管理员列表\n\n"

        super_admins = [a for a in admins if a.permission_level == 1]
        normal_admins = [a for a in admins if a.permission_level == 2]

        if super_admins:
            message += "🔴 超级管理员：\n"
            for admin in super_admins:
                # 判断是频道还是用户
                if admin.user_id < 0:
                    user_mention = (
                        f"@{admin.username}" if admin.username else admin.full_name
                    )
                else:
                    user_mention = f"[{admin.full_name}](tg://user?id={admin.user_id})"
                message += f"• {user_mention}\n"
            message += "\n"

        if normal_admins:
            message += "🟢 普通管理员：\n"
            for admin in normal_admins:
                # 判断是频道还是用户
                if admin.user_id < 0:
                    user_mention = (
                        f"@{admin.username}" if admin.username else admin.full_name
                    )
                else:
                    user_mention = f"[{admin.full_name}](tg://user?id={admin.user_id})"
                message += f"• {user_mention}\n"

        return await update.message.reply_text(message, parse_mode="Markdown")


@auto_delete_message(delay=30, custom_delays={"stats": 120, "inactive": 240})
async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /id [用户ID/@用户名/回复消息]
    查询用户的详细信息
    """
    if not await is_admin(update):
        return None
    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()

        if not group:
            return await update.message.reply_text("群组未初始化")

        # 如果没有指定用户参数，直接查询自己（用户或频道）
        if not context.args and not update.message.reply_to_message:
            if update.message.sender_chat:
                # 频道查询自己
                target_user_id = update.message.sender_chat.id
                target_username = update.message.sender_chat.username
                target_full_name = update.message.sender_chat.title or "Unknown Channel"
            elif update.effective_user:
                # 用户查询自己
                target_user_id = update.effective_user.id
                target_username = update.effective_user.username
                target_full_name = update.effective_user.full_name or "Unknown"
            else:
                return await update.message.reply_text("无法识别目标用户")
        else:
            # 有参数或回复消息，解析目标用户
            user_info = UserResolver.resolve(update, context.args, session, group.id)
            if not user_info:
                return await update.message.reply_text("无法识别目标用户")
            target_user_id, target_username, target_full_name = user_info

        # 查询用户成员信息
        statement = select(GroupMember).where(
            GroupMember.group_id == group.id, GroupMember.user_id == target_user_id
        )
        member = session.exec(statement).first()

        if not member:
            # 用户不在群组中或从未发言
            escaped_name = escape_markdown(target_full_name, version=2)
            # 判断是频道还是用户
            if target_user_id < 0:
                # 频道
                user_mention = (
                    f"@{escape_markdown(target_username, version=2)}"
                    if target_username
                    else escaped_name
                )
            else:
                # 用户
                user_mention = f"[{escaped_name}](tg://user?id={target_user_id})"

            message = f"👤 用户信息\n\n"
            message += f"用户: {user_mention}\n"
            message += f"用户ID: `{target_user_id}`\n"
            if target_username and target_user_id > 0:
                escaped_username = escape_markdown(target_username, version=2)
                message += f"用户名: @{escaped_username}\n"
            message += f"\n⚠️ 该用户未在本群组发言过或已离开"
            return await update.message.reply_text(message, parse_mode="MarkdownV2")

        # 查询用户是否是管理员
        statement = select(GroupAdmin).where(
            GroupAdmin.group_id == group.id,
            GroupAdmin.user_id == target_user_id,
            GroupAdmin.is_active == True,
        )
        admin = session.exec(statement).first()

        # 查询用户的封禁记录
        statement = select(BanRecord).where(
            BanRecord.group_id == group.id,
            BanRecord.user_id == target_user_id,
            BanRecord.is_active == True,
        )
        ban = session.exec(statement).first()

        # 格式化输出
        escaped_name = escape_markdown(member.full_name, version=2)
        # 判断是频道还是用户
        if member.user_id < 0:
            # 频道
            user_mention = (
                f"@{escape_markdown(member.username, version=2)}"
                if member.username
                else escaped_name
            )
        else:
            # 用户
            user_mention = f"[{escaped_name}](tg://user?id={member.user_id})"

        message = f"👤 用户信息\n\n"
        message += f"用户: {user_mention}\n"
        message += f"用户ID: `{member.user_id}`\n"

        if member.username and member.user_id > 0:
            escaped_username = escape_markdown(member.username, version=2)
            message += f"用户名: @{escaped_username}\n"

        # 管理员状态
        if admin:
            if admin.permission_level == 1:
                message += f"身份: 🔴 超级管理员\n"
            else:
                message += f"身份: 🟢 普通管理员\n"
        else:
            message += f"身份: 👥 普通成员\n"

        # 成员状态
        if member.is_active:
            message += f"状态: ✅ 在群组中\n"
        else:
            message += f"状态: ❌ 已离开\n"
            if member.left_at:
                # 转换为东八区时间
                left_time_local = member.left_at.replace(tzinfo=UTC).astimezone(
                    timezone(timedelta(hours=8))
                )
                left_time = escape_markdown(
                    left_time_local.strftime("%Y-%m-%d %H:%M"), version=2
                )
                message += f"离开时间: {left_time}\n"

        # 加入信息
        message += f"\n📅 时间信息\n"
        # 转换为东八区时间
        joined_time_local = member.joined_at.replace(tzinfo=UTC).astimezone(
            timezone(timedelta(hours=8))
        )
        joined_time = escape_markdown(
            joined_time_local.strftime("%Y-%m-%d %H:%M"), version=2
        )
        message += f"加入时间: {joined_time}\n"

        if member.last_message_at:
            # 转换为东八区时间
            last_msg_time_local = member.last_message_at.replace(tzinfo=UTC).astimezone(
                timezone(timedelta(hours=8))
            )
            last_msg_time = escape_markdown(
                last_msg_time_local.strftime("%Y-%m-%d %H:%M"), version=2
            )
            message += f"最后发言: {last_msg_time}\n"
        else:
            message += f"最后发言: 从未发言\n"

        # 统计信息
        message += f"\n📊 统计信息\n"
        message += f"发言次数: {member.message_count}\n"
        message += f"警告次数: {member.warning_count}\n"

        # 封禁信息
        if ban:
            message += f"\n⚠️ 封禁状态\n"
            # 转换为东八区时间
            ban_time_local = ban.banned_at.replace(tzinfo=UTC).astimezone(
                timezone(timedelta(hours=8))
            )
            ban_time = escape_markdown(
                ban_time_local.strftime("%Y-%m-%d %H:%M"), version=2
            )
            message += f"封禁时间: {ban_time}\n"
            if ban.ban_days:
                message += f"封禁天数: {ban.ban_days}天\n"
            else:
                message += f"封禁类型: 永久封禁\n"
            if ban.reason:
                reason = escape_markdown(ban.reason, version=2)
                message += f"封禁原因: {reason}\n"

        return await update.message.reply_text(message, parse_mode="MarkdownV2")


@auto_delete_message(delay=30, custom_delays={"stats": 120, "inactive": 240})
async def whitelist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /whitelist [用户ID/@用户名/回复消息]
    添加用户到白名单（踢人时豁免）
    """

    if not await is_admin(update):
        return None

    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()
        if not group:
            return await update.message.reply_text("群组未初始化")

        # 解析目标用户
        user_info = UserResolver.resolve(update, context.args, session, group.id)
        if not user_info:
            return await update.message.reply_text("无法识别目标用户")

        target_user_id, target_username, target_full_name = user_info

        # 检查是否已在白名单
        if target_user_id in group.whitelist:
            if target_user_id < 0:
                user_mention = (
                    f"@{target_username}" if target_username else target_full_name
                )
            else:
                user_mention = f"[{target_full_name}](tg://user?id={target_user_id})"
            return await update.message.reply_text(
                f"{user_mention} 已经在白名单中", parse_mode="Markdown"
            )

        # 添加到白名单
        new_whitelist = group.whitelist.copy()
        new_whitelist.append(target_user_id)
        group.whitelist = new_whitelist
        group.updated_at = datetime.now(UTC)
        session.add(group)
        session.commit()

        # 清除该群组的配置缓存
        from app.utils.channel_cache import group_config_cache

        group_config_cache.invalidate(update.effective_chat.id)

        if target_user_id < 0:
            user_mention = (
                f"@{target_username}" if target_username else target_full_name
            )
        else:
            user_mention = f"[{target_full_name}](tg://user?id={target_user_id})"

        return await update.message.reply_text(
            f"✅ 已将 {user_mention} 添加到白名单", parse_mode="Markdown"
        )


@auto_delete_message(delay=30, custom_delays={"stats": 120, "inactive": 240})
async def unwhitelist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /unwhitelist [用户ID/@用户名/回复消息]
    从白名单移除用户
    """

    if not await is_admin(update):
        return None

    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()
        if not group:
            return await update.message.reply_text("群组未初始化")

        # 解析目标用户
        user_info = UserResolver.resolve(update, context.args, session, group.id)
        if not user_info:
            return await update.message.reply_text("无法识别目标用户")

        target_user_id, target_username, target_full_name = user_info

        # 检查是否在白名单
        if target_user_id not in group.whitelist:
            return await update.message.reply_text("该用户不在白名单中")

        # 从白名单移除
        new_whitelist = group.whitelist.copy()
        new_whitelist.remove(target_user_id)
        group.whitelist = new_whitelist
        group.updated_at = datetime.now(UTC)
        session.add(group)
        session.commit()

        # 清除该群组的配置缓存
        from app.utils.channel_cache import group_config_cache

        group_config_cache.invalidate(update.effective_chat.id)

        if target_user_id < 0:
            user_mention = (
                f"@{target_username}" if target_username else target_full_name
            )
        else:
            user_mention = f"[{target_full_name}](tg://user?id={target_user_id})"

        return await update.message.reply_text(
            f"✅ 已将 {user_mention} 从白名单移除", parse_mode="Markdown"
        )


@auto_delete_message(delay=30, custom_delays={"stats": 120, "inactive": 240})
async def whitelists_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /whitelists
    查看白名单列表
    """
    if not await is_admin(update):
        return None
    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()

        if not group:
            return await update.message.reply_text("群组未初始化")

        from app.config.settings import settings

        message = "📋 白名单列表\n\n"

        # 群组白名单
        if group.whitelist:
            message += "🏠 本群白名单：\n"
            for uid in group.whitelist:
                statement = select(GroupMember).where(
                    GroupMember.group_id == group.id, GroupMember.user_id == uid
                )
                member = session.exec(statement).first()
                if member:
                    if uid < 0:
                        user_mention = (
                            f"@{member.username}"
                            if member.username
                            else member.full_name
                        )
                    else:
                        user_mention = f"[{member.full_name}](tg://user?id={uid})"
                    message += f"• {user_mention}\n"
                else:
                    message += f"• ID: {uid}\n"
        else:
            message += "暂无白名单用户"

        return await update.message.reply_text(message, parse_mode="Markdown")


@auto_delete_message(delay=30, custom_delays={"stats": 120, "inactive": 240})
async def removeadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /removeadmin [用户ID/@用户名/回复消息]
    移除管理员（需要超级管理员权限）
    """

    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()
        if not group:
            return await update.message.reply_text("群组未初始化")

        # 检查是否是超级管理员
        if update.message.sender_chat:
            check_id = update.message.sender_chat.id
        elif update.effective_user:
            check_id = update.effective_user.id
        else:
            return await update.message.reply_text("无法识别操作者")

        statement = select(GroupAdmin).where(
            GroupAdmin.group_id == group.id,
            GroupAdmin.user_id == check_id,
            GroupAdmin.permission_level == 1,
            GroupAdmin.is_active == True,
        )
        super_admin = session.exec(statement).first()

        if not super_admin:
            return None

        # 解析目标用户
        user_info = UserResolver.resolve(update, context.args, session, group.id)
        if not user_info:
            return await update.message.reply_text("无法识别目标用户")

        target_user_id, target_username, target_full_name = user_info

        # 不能移除自己的管理员权限
        if target_user_id == check_id:
            return await update.message.reply_text("❌ 不能移除自己的管理员权限")

        # 检查是否是管理员
        statement = select(GroupAdmin).where(
            GroupAdmin.group_id == group.id,
            GroupAdmin.user_id == target_user_id,
            GroupAdmin.is_active == True,
        )
        admin = session.exec(statement).first()

        if not admin:
            return await update.message.reply_text("该用户不是管理员")

        # 不能移除超级管理员权限
        if admin.permission_level == 1:
            return await update.message.reply_text("❌ 不能移除超级管理员权限")

        # 移除管理员（软删除）
        admin.is_active = False
        session.add(admin)
        session.commit()

        if target_user_id < 0:
            user_mention = (
                f"@{target_username}" if target_username else target_full_name
            )
        else:
            user_mention = f"[{target_full_name}](tg://user?id={target_user_id})"

        return await update.message.reply_text(
            f"✅ 已移除 {user_mention} 的管理员权限", parse_mode="Markdown"
        )
