"""
频道爬取服务

使用 User Bot 爬取频道的消息内容
"""

import asyncio
from datetime import datetime, UTC
from typing import Optional, List
from loguru import logger
from telethon.tl.types import Channel, Message, InputMessagesFilterPinned
from telethon.errors import FloodWaitError, ChannelPrivateError
from sqlmodel import Session, select

from app.database.connection import engine
from app.models import UserChannel, ChannelMessage, UserProfile
from app.services.userbot.client import UserBotClient


class ChannelCrawler:
    """频道爬取器"""

    def __init__(self, userbot_client: UserBotClient):
        """
        初始化频道爬取器

        Args:
            userbot_client: User Bot 客户端
        """
        self.userbot = userbot_client

    async def crawl_channel_info(self, channel_id: int, user_profile_id: int, is_personal: bool = False) -> Optional[UserChannel]:
        """
        爬取频道基本信息

        Args:
            channel_id: 频道ID
            user_profile_id: 用户资料ID
            is_personal: 是否是个人频道

        Returns:
            UserChannel 或 None
        """
        if not self.userbot.is_connected():
            raise RuntimeError("User Bot 客户端未连接")

        try:
            # 获取频道实体
            channel_entity = await self.userbot.client.get_entity(channel_id)

            if not isinstance(channel_entity, Channel):
                logger.warning(f"频道 {channel_id} 不是 Channel 类型")
                return None

            # 创建或更新频道记录
            with Session(engine) as session:
                statement = select(UserChannel).where(
                    UserChannel.user_profile_id == user_profile_id,
                    UserChannel.channel_id == channel_id
                )
                user_channel = session.exec(statement).first()

                if not user_channel:
                    user_channel = UserChannel(
                        user_profile_id=user_profile_id,
                        channel_id=channel_id
                    )

                # 更新频道信息
                user_channel.channel_username = channel_entity.username
                user_channel.channel_title = channel_entity.title
                user_channel.subscribers_count = channel_entity.participants_count or 0
                user_channel.is_personal_channel = is_personal

                # 获取频道简介
                try:
                    full_channel = await self.userbot.client.get_entity(channel_entity)
                    if hasattr(full_channel, 'about'):
                        user_channel.channel_about = full_channel.about
                except Exception as e:
                    logger.debug(f"无法获取频道 {channel_id} 的简介: {e}")

                user_channel.updated_at = datetime.now(UTC)

                session.add(user_channel)
                session.commit()
                session.refresh(user_channel)

                logger.info(f"✅ 已爬取频道信息: {channel_id} ({channel_entity.title})")
                return user_channel

        except ChannelPrivateError:
            logger.warning(f"频道 {channel_id} 是私密频道")
            return None

        except FloodWaitError as e:
            logger.warning(f"触发Flood限制，需等待 {e.seconds} 秒")
            await asyncio.sleep(e.seconds)
            return await self.crawl_channel_info(channel_id, user_profile_id, is_personal)

        except Exception as e:
            logger.error(f"爬取频道 {channel_id} 失败: {e}")
            return None

    async def crawl_channel_messages(
        self,
        user_channel: UserChannel,
        depth: int = 10
    ) -> int:
        """
        爬取频道消息

        Args:
            user_channel: 频道记录
            depth: 爬取深度（消息数量）

        Returns:
            爬取的消息数量
        """
        if not self.userbot.is_connected():
            raise RuntimeError("User Bot 客户端未连接")

        try:
            channel_entity = await self.userbot.client.get_entity(user_channel.channel_id)

            # 1. 获取所有置顶消息（使用过滤器）
            pinned_messages = []
            try:
                async for message in self.userbot.client.iter_messages(
                    channel_entity,
                    limit=50,  # 置顶消息通常不会很多
                    filter=InputMessagesFilterPinned()  # 使用过滤器直接获取置顶消息
                ):
                    # 只收集有文本内容的置顶消息
                    if message.text and message.text.strip():
                        pinned_messages.append(message)

                logger.info(f"频道 {user_channel.channel_id} 找到 {len(pinned_messages)} 条置顶消息")
            except Exception as e:
                logger.warning(f"获取频道 {user_channel.channel_id} 的置顶消息失败: {e}")

            # 2. 获取最新的非置顶消息
            latest_messages = []
            remaining_count = max(depth - len(pinned_messages), 0)  # 剩余需要爬取的非置顶消息数量

            if remaining_count > 0:
                try:
                    async for message in self.userbot.client.iter_messages(
                        channel_entity,
                        limit=remaining_count * 3  # 多取一些，因为要过滤掉置顶和空消息
                    ):
                        # 跳过置顶消息和空消息
                        if not message.pinned and message.text and message.text.strip():
                            latest_messages.append(message)
                            if len(latest_messages) >= remaining_count:
                                break

                    logger.info(f"频道 {user_channel.channel_id} 找到 {len(latest_messages)} 条非置顶消息")
                except Exception as e:
                    logger.warning(f"获取频道 {user_channel.channel_id} 的最新消息失败: {e}")

            # 3. 保存消息到数据库（只保存有文本内容的消息）
            saved_count = 0
            all_messages = pinned_messages + latest_messages

            with Session(engine) as session:
                for msg in all_messages:
                    if not isinstance(msg, Message):
                        continue

                    # 只保存有文本内容的消息
                    if not msg.text or not msg.text.strip():
                        continue

                    # 检查消息是否已存在
                    statement = select(ChannelMessage).where(
                        ChannelMessage.channel_id == user_channel.id,
                        ChannelMessage.message_id == msg.id
                    )
                    existing_msg = session.exec(statement).first()

                    if not existing_msg:
                        channel_msg = ChannelMessage(
                            channel_id=user_channel.id,
                            message_id=msg.id,
                            text=msg.text,
                            has_media=msg.media is not None,
                            media_type=msg.media.__class__.__name__ if msg.media else None,
                            is_pinned=msg.pinned,
                            views=msg.views or 0,
                            forwards=msg.forwards or 0,
                            posted_at=msg.date,
                            edited_at=msg.edit_date
                        )
                        session.add(channel_msg)
                        saved_count += 1

                # 更新频道爬取状态
                channel_obj = session.get(UserChannel, user_channel.id)
                if channel_obj:
                    channel_obj.is_crawled = True
                    channel_obj.last_crawled_at = datetime.now(UTC)
                    channel_obj.updated_at = datetime.now(UTC)

                session.commit()

            logger.info(f"✅ 频道 {user_channel.channel_id} 保存了 {saved_count} 条消息（置顶: {len(pinned_messages)}, 最新: {len(latest_messages)}）")
            return saved_count

        except ChannelPrivateError:
            logger.warning(f"频道 {user_channel.channel_id} 是私密频道")
            return 0

        except FloodWaitError as e:
            logger.warning(f"触发Flood限制，需等待 {e.seconds} 秒")
            await asyncio.sleep(e.seconds)
            return await self.crawl_channel_messages(user_channel, depth)

        except Exception as e:
            logger.error(f"爬取频道 {user_channel.channel_id} 的消息失败: {e}")
            return 0

    async def crawl_user_channels(
        self,
        user_id: int,
        crawl_messages: bool = False,
        message_depth: int = 10
    ) -> int:
        """
        爬取用户的所有关联频道

        Args:
            user_id: 用户ID
            crawl_messages: 是否爬取频道消息
            message_depth: 消息爬取深度

        Returns:
            爬取的频道数量
        """
        with Session(engine) as session:
            # 获取用户资料
            statement = select(UserProfile).where(UserProfile.user_id == user_id)
            profile = session.exec(statement).first()

            if not profile:
                logger.warning(f"用户 {user_id} 没有资料记录")
                return 0

            crawled_count = 0

            # 如果有个人频道，爬取个人频道
            if profile.has_personal_channel and profile.personal_channel_id:
                user_channel = await self.crawl_channel_info(
                    profile.personal_channel_id,
                    profile.id,
                    is_personal=True
                )

                if user_channel and crawl_messages:
                    await self.crawl_channel_messages(user_channel, message_depth)

                crawled_count += 1

            return crawled_count
