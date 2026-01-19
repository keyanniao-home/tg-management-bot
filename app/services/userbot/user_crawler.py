"""
用户信息爬取服务

使用 User Bot 爬取用户的详细信息、个人频道等
"""

import asyncio
from datetime import datetime, UTC
from typing import Optional
from loguru import logger
from telethon.tl.types import User, Channel
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import FloodWaitError, UserPrivacyRestrictedError, ChannelPrivateError
from sqlmodel import Session, select

from app.database.connection import engine
from app.models import UserProfile, UserChannel
from app.services.userbot.client import UserBotClient


class UserCrawler:
    """用户信息爬取器"""

    def __init__(self, userbot_client: UserBotClient, min_delay: int = 15, max_delay: int = 30):
        """
        初始化爬取器

        Args:
            userbot_client: User Bot 客户端
            min_delay: 最小延迟（秒）
            max_delay: 最大延迟（秒）
        """
        self.userbot = userbot_client
        self.min_delay = min_delay
        self.max_delay = max_delay

    async def crawl_user_info(self, user_id: int) -> Optional[UserProfile]:
        """
        爬取单个用户的详细信息

        Args:
            user_id: 用户ID

        Returns:
            UserProfile 或 None（失败时）
        """
        if not self.userbot.is_connected():
            raise RuntimeError("User Bot 客户端未连接")

        try:
            # 获取用户完整信息
            user = await self.userbot.client.get_entity(user_id)

            if not isinstance(user, User):
                logger.warning(f"用户 {user_id} 不是 User 类型")
                return None

            # 创建或更新用户资料
            with Session(engine) as session:
                statement = select(UserProfile).where(UserProfile.user_id == user_id)
                profile = session.exec(statement).first()

                if not profile:
                    profile = UserProfile(user_id=user_id)

                # 更新基本信息
                profile.username = user.username
                profile.first_name = user.first_name
                profile.last_name = user.last_name
                profile.phone = user.phone

                # 获取用户完整信息（包括简介）
                try:
                    full_user_result = await self.userbot.client(GetFullUserRequest(user_id))
                    if full_user_result and hasattr(full_user_result, 'full_user'):
                        full_user = full_user_result.full_user
                        if hasattr(full_user, 'about'):
                            # 无论简介是否为空，都要更新，确保清空的简介也能同步
                            profile.bio = full_user.about if full_user.about else None
                            if full_user.about:
                                logger.debug(f"获取到用户 {user_id} 的简介: {full_user.about[:50]}...")
                            else:
                                logger.debug(f"用户 {user_id} 的简介为空")
                        else:
                            profile.bio = None
                            logger.debug(f"用户 {user_id} 没有简介字段")
                except Exception as e:
                    logger.warning(f"无法获取用户 {user_id} 的完整信息: {e}")

                # 更新账号状态
                profile.is_bot = user.bot
                profile.is_verified = user.verified if hasattr(user, 'verified') else False
                profile.is_restricted = user.restricted if hasattr(user, 'restricted') else False
                profile.is_scam = user.scam if hasattr(user, 'scam') else False
                profile.is_fake = user.fake if hasattr(user, 'fake') else False
                profile.is_premium = user.premium if hasattr(user, 'premium') else False

                # 爬取信息
                profile.last_crawled_at = datetime.now(UTC)
                profile.crawl_error = None
                profile.updated_at = datetime.now(UTC)

                session.add(profile)
                session.commit()
                session.refresh(profile)

                logger.info(f"✅ 已爬取用户信息: {user_id} (@{user.username or '无'})")
                return profile

        except UserPrivacyRestrictedError:
            logger.warning(f"用户 {user_id} 隐私设置限制")
            self._save_error(user_id, "隐私设置限制")
            return None

        except FloodWaitError as e:
            logger.warning(f"触发Flood限制，需等待 {e.seconds} 秒")
            await asyncio.sleep(e.seconds)
            return await self.crawl_user_info(user_id)

        except Exception as e:
            logger.error(f"爬取用户 {user_id} 失败: {e}")
            self._save_error(user_id, str(e))
            return None

    async def find_user_personal_channel(self, user_id: int, profile: UserProfile) -> Optional[int]:
        """
        查找用户的个人频道

        Args:
            user_id: 用户ID
            profile: 用户资料

        Returns:
            频道ID 或 None
        """
        try:
            # 通过 GetFullUserRequest 获取用户完整信息
            full_user_result = await self.userbot.client(GetFullUserRequest(user_id))

            if not full_user_result or not hasattr(full_user_result, 'full_user'):
                return None

            full_user = full_user_result.full_user

            # 检查 personal_channel_id 字段（Telegram API 提供的个人频道ID）
            if hasattr(full_user, 'personal_channel_id') and full_user.personal_channel_id:
                logger.info(f"找到用户 {user_id} 的个人频道ID: {full_user.personal_channel_id}")
                return full_user.personal_channel_id

            logger.debug(f"用户 {user_id} 没有个人频道")
            return None

        except Exception as e:
            logger.warning(f"查找用户 {user_id} 的个人频道失败: {e}")
            return None

    async def crawl_user_with_delay(self, user_id: int) -> Optional[UserProfile]:
        """
        带延迟的爬取用户信息

        Args:
            user_id: 用户ID

        Returns:
            UserProfile 或 None
        """
        # 随机延迟，避免触发风控
        import random
        delay = random.randint(self.min_delay, self.max_delay)
        logger.debug(f"等待 {delay} 秒后爬取用户 {user_id}")
        await asyncio.sleep(delay)

        # 爬取用户信息
        profile = await self.crawl_user_info(user_id)

        if profile:
            # 查找个人频道
            channel_id = await self.find_user_personal_channel(user_id, profile)
            if channel_id:
                with Session(engine) as session:
                    profile_obj = session.get(UserProfile, profile.id)
                    if profile_obj:
                        profile_obj.has_personal_channel = True
                        profile_obj.personal_channel_id = channel_id
                        profile_obj.updated_at = datetime.now(UTC)
                        session.commit()  # session.get() 获取的对象已在 session 中，直接 commit 即可
                        logger.info(f"✅ 找到用户 {user_id} 的个人频道: {channel_id}")

        return profile

    def _save_error(self, user_id: int, error_message: str):
        """保存爬取错误"""
        try:
            with Session(engine) as session:
                statement = select(UserProfile).where(UserProfile.user_id == user_id)
                profile = session.exec(statement).first()

                if not profile:
                    profile = UserProfile(user_id=user_id)

                profile.crawl_error = error_message
                profile.last_crawled_at = datetime.now(UTC)
                profile.updated_at = datetime.now(UTC)

                session.add(profile)
                session.commit()
        except Exception as e:
            logger.error(f"保存错误信息失败: {e}")
