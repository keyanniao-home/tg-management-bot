from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlmodel import Session, select
from app.database.connection import engine
from app.models import GroupConfig, ChannelBinding, GroupMember
from app.handlers.stats import LRUCache
from app.utils.auto_delete import auto_delete_message
import uuid


# 全局绑定缓存实例: {uuid: (user_id, group_id, group_db_id)}
bind_cache = LRUCache(capacity=100)


@auto_delete_message(delay=30)
async def bd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /bd - 用户或频道执行：生成绑定链接
    /bd <uuid> - 频道身份执行：完成绑定
    """
    if not update.message:
        return

    # 检查是否在群组中
    chat_id = update.effective_chat.id
    if chat_id > 0:
        await update.message.reply_text("此命令只能在群组中使用")
        return

    args = context.args

    # 如果提供了参数但不是频道身份，报错
    if args and len(args) == 1 and not update.message.sender_chat:
        return await update.message.reply_text(
            "❌ 完成绑定需要使用频道身份\n\n"
            "请以频道身份在群组中执行命令"
        )

    # 情况1: 频道身份执行 /bd <uuid>（完成绑定）
    if update.message.sender_chat and args and len(args) == 1:
        binding_uuid = args[0]
        channel = update.message.sender_chat
        channel_id = channel.id

        # 立即删除群消息，保持匿名
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=update.message.message_id
            )
        except:
            pass

        # 检查是否为频道（频道ID是负数）
        if channel_id > 0:
            return

        # 从缓存获取绑定信息
        bind_info = bind_cache.get(binding_uuid)

        if bind_info is None:
            return None

        user_id, requester_id, requester_type, bind_chat_id, group_db_id = bind_info

        # 验证链接是否已被点击（user_id必须有值）
        if user_id is None:
            return None

        # 验证是否在同一个群组
        if bind_chat_id != chat_id:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="⚠️ 绑定失败：请在正确的群组中执行绑定"
                )
            except:
                pass
            return

        # 验证频道是否匹配（如果是频道发起的）
        if requester_type == 'channel' and channel_id != requester_id:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="⚠️ 绑定失败：频道不匹配，请使用发起绑定的频道执行命令"
                )
            except:
                pass
            return

        with Session(engine) as session:
            # 检查频道是否已绑定
            statement = select(ChannelBinding).where(ChannelBinding.channel_id == channel_id)
            existing = session.exec(statement).first()

            if existing:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="⚠️ 该频道已绑定，无法重复绑定"
                    )
                except:
                    pass
                return

            # 验证用户是否在群内（必须是活跃成员）
            statement = select(GroupMember).where(
                GroupMember.group_id == group_db_id,
                GroupMember.user_id == user_id,
                GroupMember.is_active == True
            )
            member = session.exec(statement).first()

            if not member:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="⚠️ 绑定失败：该用户不在群内或已退出群组\n\n"
                             "只能将频道绑定到当前群内的成员"
                    )
                except:
                    pass
                return

            # 获取用户信息
            try:
                user = await context.bot.get_chat(user_id)
                user_full_name = user.full_name or f"User{user_id}"
                user_username = user.username
            except:
                user_full_name = f"User{user_id}"
                user_username = None

            # 创建绑定记录（全局共享，不关联特定群组）
            binding = ChannelBinding(
                channel_id=channel_id,
                user_id=user_id,
                channel_username=channel.username,
                channel_title=channel.title,
                user_username=user_username,
                user_full_name=user_full_name
            )

            session.add(binding)
            session.commit()

            # 从绑定缓存中移除（链接作废）
            bind_cache.cache.pop(binding_uuid, None)

            # 清除该频道的权限缓存，以便下次发言时重新验证
            from app.utils.channel_cache import channel_permission_cache
            channel_permission_cache.invalidate_channel(channel_id, group_db_id)

            # 私聊通知用户绑定成功
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"✅ 绑定成功！\n\n"
                         f"频道: {channel.title or channel.username or channel_id}\n"
                         f"用户: {user_full_name}"
                )
            except:
                pass
        return

    # 情况2: 用户或频道执行 /bd（生成绑定链接）
    requester_id = None
    requester_type = None  # 'user' or 'channel'

    if update.message.sender_chat:
        # 频道执行
        requester_id = update.message.sender_chat.id
        requester_type = 'channel'
    elif update.effective_user:
        # 用户执行（也要通过链接验证）
        requester_id = update.effective_user.id
        requester_type = 'user'
    else:
        return

    with Session(engine) as session:
        # 获取群组配置
        statement = select(GroupConfig).where(GroupConfig.group_id == chat_id)
        group = session.exec(statement).first()

        if not group:
            await update.message.reply_text("群组未初始化")


        # 生成UUID
        binding_uuid = str(uuid.uuid4())

        # 存入缓存: uuid -> (None, requester_id, requester_type, chat_id, group_db_id)
        # user_id初始为None，点击链接后更新
        bind_cache.put(binding_uuid, (None, requester_id, requester_type, chat_id, group.id))

        # 获取bot的username
        bot = context.bot
        bot_username = (await bot.get_me()).username

        # 创建deep link
        deep_link = f"https://t.me/{bot_username}?start=bind_{binding_uuid}"

        # 创建按钮
        keyboard = [[InlineKeyboardButton("🔗 开始绑定频道", url=deep_link)]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        return await update.message.reply_text(
            "点击下方按钮，在私聊中完成频道绑定：",
            reply_markup=reply_markup
        )


async def handle_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理 /start 命令，支持 deep link 参数
    格式: /start bind_<uuid>
    处理 /start 命令
    - 私聊：DM功能激活说明
    - 群组：频道绑定流程（如有参数）
    """
    if not update.message or not update.effective_user:
        return

    # 如果是私聊
    if update.effective_chat.type == "private":
        # 检查是否有绑定参数
        if not context.args:
            await update.message.reply_text(
                "👋 你好！\n\n"
                "✅ 你已激活DM功能！\n\n"
                "现在可以在群组中使用 /dm 命令向你发送私信了。\n\n"
                "📝 使用方法：\n"
                "1. 其他成员在群组中执行 /dm <你的用户ID> <消息内容>\n"
                "2. Bot会将消息转发到你的私聊\n"
                "3. 你也可以使用 /my_dms 查看收到的私信\n\n"
                "💡 提示：你的用户ID可以在群组中通过 /id 命令查看"
            )
            return
    
    # 频道绑定流程（群组中或有参数）
    if not context.args:
        await update.message.reply_text(
            "👋 你好！\n\n"
            "请在群组中使用 /bd 命令来绑定频道。\n\n"
            "使用方法：\n"
            "1. 在群组中执行 /bd 命令\n"
            "2. 点击按钮跳转到私聊获取UUID\n"
            "3. 以频道身份在群组中执行 /bd <UUID> 完成绑定"
        )
        return
    
    arg = context.args[0]
    if not arg.startswith("bind_"):
        await update.message.reply_text("👋 你好！请在群组中使用 /bd 命令来绑定频道。")
        return
    
    binding_uuid = arg[5:]  # 去掉 "bind_" 前缀
    bind_cache = context.bot_data.setdefault("bind_cache", {})
    bind_info = bind_cache.get(binding_uuid)
    
    if bind_info is None:
        await update.message.reply_text("⚠️ 绑定链接无效或已过期，请重新在群组中执行 /bd 命令")
        return
    
    user_id, requester_id, requester_type, chat_id, group_db_id = bind_info
    # 如果已经有user_id了，说明链接已被使用
    if user_id is not None:
        await update.message.reply_text("⚠️ 此绑定链接已被使用，请重新在群组中执行 /bd 命令")
        return
    
    # 记录点击链接的用户ID，更新缓存
    bind_cache[binding_uuid] = (update.effective_user.id, requester_id, requester_type, chat_id, group_db_id)
    
    await update.message.reply_text(
        f"✅ 验证成功！\n\n"
        f"📝 下一步：请以**频道身份**在群组中发送以下命令完成绑定：\n\n"
        f"`/bd {binding_uuid}`\n\n"
        f"💡 提示：\n"
        f"1. 确保频道已加入群组\n"
        f"2. 在群组聊天框输入命令时，点击频道头像切换为频道身份\n"
        f"3. 以频道身份发送上述命令即可完成绑定\n"
        f"4. 频道将绑定到你的账号\n"
        f"5. 绑定成功后会收到私聊通知",
        parse_mode="Markdown"
    )
