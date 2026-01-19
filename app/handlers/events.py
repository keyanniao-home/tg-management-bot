from datetime import datetime, timedelta, UTC

from loguru import logger
from telegram import Update
from telegram.ext import ContextTypes, ApplicationHandlerStop
from sqlmodel import Session, select
from sqlalchemy import text
from sqlalchemy.orm.attributes import flag_modified
from app.database.connection import engine
from app.models import GroupConfig, GroupMember, Message, GroupAdmin, ChannelBinding
from app.database.views import QUERY_INACTIVE_USERS
from app.handlers.commands import is_admin
from app.services.image_queue import image_queue
import asyncio


# 频道提示消息限流字典: {(channel_id, group_id): last_tip_time}
# 同一频道在同一群组60秒内只发送一次提示
channel_tip_rate_limit = {}


async def _ensure_group_owner_as_admin(bot, group: GroupConfig, session: Session):
    """确保群组所有者是超级管理员"""
    try:
        # 获取群组管理员列表
        admins = await bot.get_chat_administrators(group.group_id)

        for admin in admins:
            # 找到群组所有者 (creator)
            if admin.status == "creator":
                owner_user = admin.user

                # 检查所有者是否已经是管理员
                statement = select(GroupAdmin).where(
                    GroupAdmin.group_id == group.id, GroupAdmin.user_id == owner_user.id
                )
                existing_admin = session.exec(statement).first()

                if not existing_admin:
                    # 添加所有者为超级管理员
                    owner_admin = GroupAdmin(
                        group_id=group.id,
                        user_id=owner_user.id,
                        username=owner_user.username,
                        full_name=owner_user.full_name
                        or owner_user.first_name
                        or "Owner",
                        permission_level=1,  # 超级管理员
                        appointed_by_user_id=None,  # 系统自动设置
                    )
                    session.add(owner_admin)
                    session.commit()
                elif existing_admin.permission_level != 1:
                    # 如果已存在但不是超级管理员，升级为超级管理员
                    existing_admin.permission_level = 1
                    session.add(existing_admin)
                    session.commit()

                break
    except Exception as e:
        # 如果获取失败（比如bot没有权限），忽略错误
        pass


async def on_chat_member_updated(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    监听群组成员状态变化（加入、离开、被踢等）
    使用 chat_member 更新，比 new_chat_members 更可靠
    """
    if not update.chat_member:
        return

    chat_member_update = update.chat_member
    old_status = chat_member_update.old_chat_member.status
    new_status = chat_member_update.new_chat_member.status
    user = chat_member_update.new_chat_member.user

    logger.debug(f"用户状态变化: {user.id} ({old_status} -> {new_status})")

    with Session(engine) as session:
        # 获取群组配置
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()

        # 如果群组不存在或未初始化，忽略
        if not group or not group.is_initialized:
            return

        # 检查成员是否已存在
        statement = select(GroupMember).where(
            GroupMember.group_id == group.id, GroupMember.user_id == user.id
        )
        member = session.exec(statement).first()

        # 判断当前状态
        # 离开状态: left, kicked, banned
        # 成员状态: member, administrator, creator, restricted (受限但仍在群内)
        left_statuses = ["left", "kicked", "banned"]
        member_statuses = ["member", "administrator", "creator", "restricted"]

        # 用户在群内（新状态是成员状态）
        if new_status in member_statuses:
            logger.debug(f"用户状态更新: {user.id} ({old_status} -> {new_status})")
            inviter_id = (
                chat_member_update.from_user.id
                if chat_member_update.from_user
                else None
            )

            if member:
                # 更新现有成员信息
                member.is_active = True
                if not member.joined_at or old_status in left_statuses:
                    # 如果是首次加入或从离开状态回来，更新加入时间
                    member.joined_at = datetime.now(UTC)
                member.left_at = None
                if old_status in left_statuses:
                    # 从离开状态回来，记录邀请人
                    member.invited_by_user_id = inviter_id
                # 总是更新用户信息
                member.username = user.username
                member.full_name = user.full_name or user.first_name or "Unknown"
            else:
                # 新成员
                member = GroupMember(
                    group_id=group.id,
                    user_id=user.id,
                    username=user.username,
                    full_name=user.full_name or user.first_name or "Unknown",
                    invited_by_user_id=inviter_id,
                )

            session.add(member)
            session.commit()

        # 用户离开群组（新状态是离开状态）
        elif new_status in left_statuses:
            logger.debug(f"用户离开: {user.id} ({old_status} -> {new_status})")

            if member:
                # 软删除
                member.is_active = False
                member.left_at = datetime.now(UTC)
                session.add(member)
                session.commit()

                # 清除该用户在此群组的频道权限缓存
                from app.utils.channel_cache import channel_permission_cache

                channel_permission_cache.invalidate_user(user.id, group.id)


async def check_unbound_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    检查未绑定频道消息并删除
    优先级最高，只豁免 /bd 命令
    使用缓存减少数据库查询（1小时过期）
    """
    if not update.message:
        return

    # 只处理频道消息
    if not update.message.sender_chat:
        return
    logger.debug("频道发言")

    sender_chat = update.message.sender_chat
    sender_chat_id = sender_chat.id

    # 豁免 /bd 命令
    if update.message.text and update.message.text.startswith("/bd"):
        return

    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()

        # 如果群组不存在或未初始化，忽略
        if not group or not group.is_initialized:
            return

        # 检查是否开启了自动删除未绑定频道消息
        auto_delete_unbound_channel = group.config.get(
            "auto_delete_unbound_channel", False
        )

        if not auto_delete_unbound_channel:
            return

        # 先查缓存
        from app.utils.channel_cache import channel_permission_cache

        cached_result = channel_permission_cache.get(sender_chat_id, group.id)

        if cached_result is not None:
            # 缓存命中
            if not cached_result:
                # 缓存显示不允许发言，删除消息
                await _delete_channel_message(update, context, sender_chat)
                raise ApplicationHandlerStop
            else:
                # 允许发言，直接返回
                return

        # 缓存未命中，查询数据库
        # 检查频道是否已绑定（全局共享，不过滤 group_id）
        statement = select(ChannelBinding).where(
            ChannelBinding.channel_id == sender_chat_id
        )
        binding = session.exec(statement).first()

        if not binding:
            # 频道未绑定，缓存结果并删除消息
            channel_permission_cache.put(sender_chat_id, group.id, False)
            await _delete_channel_message(update, context, sender_chat)
            raise ApplicationHandlerStop

        # 频道已绑定（全局），检查绑定的用户是否在当前群内
        statement = select(GroupMember).where(
            GroupMember.group_id == group.id,
            GroupMember.user_id == binding.user_id,
            GroupMember.is_active == True,
        )
        bound_user = session.exec(statement).first()

        if not bound_user:
            # 绑定的用户不在群内，不允许发言
            channel_permission_cache.put(sender_chat_id, group.id, False)
            await _delete_channel_message(update, context, sender_chat)
            raise ApplicationHandlerStop

        # 绑定的用户在群内，允许发言
        channel_permission_cache.put(sender_chat_id, group.id, True)


async def _delete_channel_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, sender_chat
):
    """删除频道消息并发送提示（异步，不阻塞主流程，带限流）"""
    try:
        # 删除原消息
        await context.bot.delete_message(
            chat_id=update.effective_chat.id, message_id=update.message.message_id
        )

        # 限流检查：60秒内同一频道只发送一次提示
        channel_id = sender_chat.id
        chat_id = update.effective_chat.id
        rate_limit_key = (channel_id, chat_id)
        current_time = datetime.now(UTC)

        # 检查是否在限流期内
        if rate_limit_key in channel_tip_rate_limit:
            last_tip_time = channel_tip_rate_limit[rate_limit_key]
            if current_time - last_tip_time < timedelta(seconds=60):
                # 在限流期内，不发送提示消息
                return

        # 更新最后提示时间
        channel_tip_rate_limit[rate_limit_key] = current_time

        # 清理过期的限流记录（超过120秒的）
        expired_keys = [
            key
            for key, last_time in channel_tip_rate_limit.items()
            if current_time - last_time > timedelta(seconds=120)
        ]
        for key in expired_keys:
            del channel_tip_rate_limit[key]

        # 发送提示消息
        channel_name = sender_chat.title or sender_chat.username or "频道"
        tip_msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"⚠️ 频道 {channel_name} 未绑定或绑定用户不在群内\n\n"
            f"请在群组中执行 /bd 命令完成频道绑定",
        )

        # 创建后台任务，10秒后删除提示消息（不阻塞主流程）
        async def delete_tip_later():
            await asyncio.sleep(10)
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id, message_id=tip_msg.message_id
                )
            except:
                pass

        # 启动后台任务（不等待完成）
        asyncio.create_task(delete_tip_later())

    except ApplicationHandlerStop:
        raise
    except Exception:
        # 删除失败也要停止传播
        pass


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收到消息事件"""
    if not update.message:
        return

    logger.debug("新消息")

    # 检查是否是回复确认消息（只有文本消息且用户可以确认）
    if (
        update.effective_user
        and update.message.reply_to_message
        and update.message.text
        and update.message.text in ["确认", "确定", "confirm"]
    ):
        await _handle_confirm_reply(update, context)
        return

    # 跳过命令消息（只有文本消息才可能是命令）
    if update.message.text and update.message.text.startswith("/"):
        return

    with Session(engine) as session:
        statement = select(GroupConfig).where(
            GroupConfig.group_id == update.effective_chat.id
        )
        group = session.exec(statement).first()

        # 如果群组不存在或未初始化，忽略
        if not group or not group.is_initialized:
            return

        # 判断是频道消息还是用户消息
        is_channel = update.message.sender_chat is not None
        member_id = None
        user_id = None
        sender_chat_id = None
        sender_chat_title = None
        sender_chat_username = None

        if is_channel:
            # 频道消息 - 把频道也当作成员处理
            sender_chat = update.message.sender_chat
            sender_chat_id = sender_chat.id
            sender_chat_title = sender_chat.title
            sender_chat_username = sender_chat.username

            # 获取或创建频道成员记录
            statement = select(GroupMember).where(
                GroupMember.group_id == group.id, GroupMember.user_id == sender_chat_id
            )
            member = session.exec(statement).first()

            if not member:
                member = GroupMember(
                    group_id=group.id,
                    user_id=sender_chat_id,
                    username=sender_chat_username,
                    full_name=sender_chat_title or "Unknown Channel",
                )
                session.add(member)
                session.commit()
                session.refresh(member)
            else:
                # 更新频道名称（如果有变化）
                if sender_chat_title and member.full_name != sender_chat_title:
                    member.full_name = sender_chat_title
                if sender_chat_username and member.username != sender_chat_username:
                    member.username = sender_chat_username

            # 更新频道统计
            member.message_count += 1
            member.last_message_at = datetime.now(UTC)
            member.updated_at = datetime.now(UTC)
            session.add(member)

            member_id = member.id
        else:
            # 用户消息
            if not update.effective_user:
                return

            user_id = update.effective_user.id

            # 获取或创建成员
            statement = select(GroupMember).where(
                GroupMember.group_id == group.id, GroupMember.user_id == user_id
            )
            member = session.exec(statement).first()

            if not member:
                member = GroupMember(
                    group_id=group.id,
                    user_id=user_id,
                    username=update.effective_user.username,
                    full_name=update.effective_user.full_name or "Unknown",
                )
                session.add(member)
                session.commit()
                session.refresh(member)
            else:
                # 更新用户名称（如果有变化）
                current_full_name = update.effective_user.full_name or "Unknown"
                if member.full_name != current_full_name:
                    member.full_name = current_full_name
                if (
                    update.effective_user.username
                    and member.username != update.effective_user.username
                ):
                    member.username = update.effective_user.username

            # 更新成员统计
            member.message_count += 1
            member.last_message_at = datetime.now(UTC)
            member.updated_at = datetime.now(UTC)
            session.add(member)

            member_id = member.id

        # 检测消息类型
        message_type = "text"
        message_text = None

        if update.message.text:
            message_type = "text"
            message_text = update.message.text
        elif update.message.photo:
            message_type = "photo"
            message_text = update.message.caption
        elif update.message.video:
            message_type = "video"
            message_text = update.message.caption
        elif update.message.audio:
            message_type = "audio"
        elif update.message.voice:
            message_type = "voice"
        elif update.message.document:
            message_type = "document"
            message_text = update.message.caption
        elif update.message.sticker:
            message_type = "sticker"
        elif update.message.animation:
            message_type = "animation"
            message_text = update.message.caption
        elif update.message.video_note:
            message_type = "video_note"
        elif update.message.location:
            message_type = "location"
        elif update.message.poll:
            message_type = "poll"

        # 检测话题信息（for Forum groups）
        topic_id = None
        is_topic_message = False
        if (
            hasattr(update.message, "message_thread_id")
            and update.message.message_thread_id
        ):
            topic_id = update.message.message_thread_id
            is_topic_message = True

        # 记录消息
        message = Message(
            message_id=update.message.message_id,
            group_id=group.id,
            member_id=member_id,
            user_id=user_id,
            sender_chat_id=sender_chat_id,
            sender_chat_title=sender_chat_title,
            sender_chat_username=sender_chat_username,
            is_channel_message=is_channel,
            topic_id=topic_id,
            is_topic_message=is_topic_message,
            message_type=message_type,
            text=message_text,
            reply_to_message_id=update.message.reply_to_message.message_id
            if update.message.reply_to_message
            else None,
        )
        session.add(message)
        session.commit()
        session.refresh(message)

        # 话题自动同步：如果是话题消息，自动创建对应分类
        if is_topic_message and topic_id:
            try:
                from app.services.resource_service import CategoryService

                # 尝试获取话题的名称（Telegram Bot API限制，无法直接获取，使用ID作为名称）
                topic_name = str(topic_id)
                CategoryService.get_or_create_by_topic(
                    session=session,
                    group_id=update.effective_chat.id,  # 使用Telegram群组ID
                    topic_id=topic_id,
                    topic_name=topic_name,
                )
            except Exception as e:
                logger.error(f"自动同步话题分类失败: {e}")

        # 积分系统：用户消息加分（非频道消息）
        if not is_channel and user_id:
            from app.services.points_service import points_service

            if points_service.is_enabled():
                points_service.add_points(
                    session,
                    group.id,
                    user_id,
                    points_service.POINTS_MESSAGE,
                    "message",
                    "发送消息",
                )

        # 图片检测：如果消息包含图片，检测是否有目标对象
        if message_type == "photo":
            await _detect_and_react_to_image(update, context, message, session)

        # DM 检测：检测消息中的 dm/pm 关键词
        if message_text and not is_channel and user_id:
            from app.services.dm_detection_service import DMDetectionService

            keywords = DMDetectionService.check_message(message_text)
            if keywords:
                for keyword in keywords:
                    DMDetectionService.record_detection(
                        session=session,
                        group_id=update.effective_chat.id,
                        user_id=user_id,
                        username=update.effective_user.username
                        if update.effective_user
                        else None,
                        full_name=update.effective_user.full_name
                        if update.effective_user
                        else None,
                        message_id=update.message.message_id,
                        keyword=keyword,
                        message_text=message_text,
                    )
                logger.debug(f"DM detected: user={user_id}, keywords={keywords}")


async def _batch_kick_users(
    bot, group_id: int, users_to_kick: list, status_message, status_chat_id: int
):
    """后台异步批量踢出用户"""
    kicked_count = 0
    failed_count = 0
    total = len(users_to_kick)

    for idx, (user_id, username, full_name) in enumerate(users_to_kick, 1):
        try:
            await bot.ban_chat_member(chat_id=group_id, user_id=user_id)
            await bot.unban_chat_member(chat_id=group_id, user_id=user_id)
            logger.debug(f"踢出 {full_name} : {user_id} 成功")
            kicked_count += 1

            # 每踢出10人或完成时更新进度
            if idx % 10 == 0 or idx == total:
                try:
                    await bot.edit_message_text(
                        chat_id=status_chat_id,
                        message_id=status_message.message_id,
                        text=f"⏳ 正在批量踢出... ({idx}/{total})\n"
                        f"成功: {kicked_count}\n"
                        f"失败: {failed_count}",
                    )
                except Exception:
                    pass  # 忽略编辑消息失败

        except Exception as e:
            failed_count += 1
            logger.debug(f"踢出用户 {user_id} 失败: {e}")

    # 最终结果
    try:
        await bot.edit_message_text(
            chat_id=status_chat_id,
            message_id=status_message.message_id,
            text=f"✅ 批量踢出完成\n成功: {kicked_count}人\n失败: {failed_count}人",
        )
    except Exception:
        pass


async def _handle_confirm_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理确认回复（用于批量踢出未发言用户和号商）"""
    from app.handlers.ai import handle_scammer_confirmation

    # 检查是否是管理员
    if not await is_admin(update):
        await update.message.reply_text("你不是管理员，无权执行此操作")
        return

    # 检查回复的消息是否在pending_kick中（不活跃用户）
    reply_to_msg_id = update.message.reply_to_message.message_id

    if (
        "pending_kick" in context.bot_data
        and reply_to_msg_id in context.bot_data["pending_kick"]
    ):
        # 获取待踢出的信息
        kick_info = context.bot_data["pending_kick"][reply_to_msg_id]
        group_id = kick_info["group_id"]
        users_to_kick = kick_info["users"]

        # 删除pending操作（立即删除，避免重复执行）
        del context.bot_data["pending_kick"][reply_to_msg_id]

        # 发送状态消息
        status_message = await update.message.reply_text(
            f"⏳ 开始批量踢出 {len(users_to_kick)} 人...\n"
            f"此操作将在后台执行，不会阻塞 Bot"
        )

        # 创建后台任务（不等待完成）
        asyncio.create_task(
            _batch_kick_users(
                context.bot,
                group_id,
                users_to_kick,
                status_message,
                update.effective_chat.id,
            )
        )
        return

    # 尝试处理号商检测确认
    await handle_scammer_confirmation(update, context)


async def _detect_and_react_to_image(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    message: Message,
    session: Session,
):
    """
    将图片检测任务加入异步队列

    Args:
        update: Telegram更新对象
        context: Bot上下文
        message: 数据库中的消息对象
        session: 数据库会话
    """
    from app.services.image_detector import image_detector

    # 检查图片检测器是否可用
    if not image_detector.is_available():
        logger.debug("Image detector not available, skipping detection")
        return

    # 跳过转发的消息
    if update.message.forward_origin is not None:
        logger.debug(f"Skipping forwarded message {message.message_id}")
        return

    # 获取用户ID，检查是否在黑名单中（避免下载）
    user_id = message.user_id if message.user_id else message.sender_chat_id
    if user_id and user_id in image_queue.image_blacklist:
        blacklist_until = image_queue.image_blacklist[user_id]
        import time

        if time.time() < blacklist_until:
            remaining = int(blacklist_until - time.time())
            logger.debug(
                f"Skipping image from blacklisted user {user_id} (message {message.message_id}, {remaining}s remaining)"
            )
            return

    try:
        # 获取最大的图片（Telegram会发送多个尺寸）
        photo = update.message.photo[-1]

        # 下载图片到内存
        logger.debug(f"Downloading image from message {message.message_id}...")
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()

        # 将任务加入队列（非阻塞）
        enqueued = await image_queue.enqueue(
            update, context, message, bytes(image_bytes)
        )
        if enqueued:
            logger.debug(
                f"Image detection task enqueued for message {message.message_id}"
            )
        else:
            logger.debug(
                f"Image task skipped for message {message.message_id} (duplicate/rate-limited)"
            )

    except Exception as e:
        logger.error(
            f"Error enqueuing image detection for message {message.message_id}: {e}"
        )


async def on_forum_topic_created(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    监听话题创建事件

    当群组中创建新话题时，自动创建对应的分类并使用真实的话题名称
    这样比在消息事件中自动同步更好，因为能获取到话题的真实名称
    """
    if not update.message or not update.effective_chat:
        return

    # 检查是否是话题创建事件
    if not update.message.forum_topic_created:
        return

    topic = update.message.forum_topic_created
    topic_id = update.message.message_thread_id
    topic_name = topic.name

    logger.info(f"检测到话题创建: {topic_name} (ID: {topic_id})")

    # 自动创建分类
    try:
        with Session(engine) as session:
            from app.services.resource_service import CategoryService

            # 使用话题的真实名称
            category = CategoryService.get_or_create_by_topic(
                session=session,
                group_id=update.effective_chat.id,
                topic_id=topic_id,
                topic_name=topic_name,  # 使用真实的话题名称
            )

            logger.info(f"自动创建分类成功: {category.name} (topic_id={topic_id})")
    except Exception as e:
        logger.error(f"话题创建事件处理失败: {e}")
