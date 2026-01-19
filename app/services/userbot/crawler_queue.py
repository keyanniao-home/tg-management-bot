"""
异步爬虫队列系统

管理用户信息和频道爬取任务的异步执行
"""

import asyncio
from typing import Optional
from datetime import datetime, UTC
from loguru import logger
from sqlmodel import Session, select
from telegram import Bot

from app.database.connection import engine
from app.models import CrawlTask, CrawlTaskStatus, GroupMember, GroupConfig
from app.services.userbot.client import userbot_client
from app.services.userbot.user_crawler import UserCrawler
from app.services.userbot.channel_crawler import ChannelCrawler


class CrawlerQueue:
    """爬虫队列单例"""

    _instance: Optional['CrawlerQueue'] = None
    _task: Optional[asyncio.Task] = None
    _running: bool = False
    _current_task_id: Optional[int] = None
    _status_message_id: Optional[int] = None
    _status_chat_id: Optional[int] = None
    _bot: Optional[Bot] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化队列"""
        self.user_crawler = UserCrawler(userbot_client)
        self.channel_crawler = ChannelCrawler(userbot_client)

    def set_bot(self, bot: Bot):
        """设置Bot实例用于发送状态更新"""
        self._bot = bot

    def start(self):
        """启动队列处理"""
        if self._running:
            logger.warning("爬虫队列已经在运行")
            return

        self._running = True
        self._task = asyncio.create_task(self._process_queue())
        logger.info("爬虫队列已启动")

    async def stop(self):
        """停止队列处理"""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("爬虫队列已停止")

    async def add_task(
        self,
        group_id: int,
        crawl_channels: bool,
        channel_depth: int,
        created_by_user_id: int,
        created_by_username: Optional[str],
        status_chat_id: int,
        status_message_id: int
    ) -> CrawlTask:
        """
        添加爬取任务

        Args:
            group_id: 群组数据库ID
            crawl_channels: 是否爬取频道
            channel_depth: 频道消息深度
            created_by_user_id: 创建者用户ID
            created_by_username: 创建者用户名
            status_chat_id: 状态消息所在聊天ID
            status_message_id: 状态消息ID

        Returns:
            创建的任务
        """
        with Session(engine) as session:
            # 计算总用户数
            statement = select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.is_active == True
            )
            members = session.exec(statement).all()
            total_users = len(members)

            # 创建任务
            task = CrawlTask(
                group_id=group_id,
                crawl_channels=crawl_channels,
                channel_depth=channel_depth,
                total_users=total_users,
                created_by_user_id=created_by_user_id,
                created_by_username=created_by_username,
                status_chat_id=status_chat_id,
                status_message_id=status_message_id
            )
            session.add(task)
            session.commit()
            session.refresh(task)

            logger.info(f"✅ 创建爬取任务 #{task.id}，共 {total_users} 个用户")
            return task

    async def _process_queue(self):
        """处理队列中的任务"""
        while self._running:
            try:
                # 获取待处理的任务
                with Session(engine) as session:
                    statement = select(CrawlTask).where(
                        CrawlTask.status == CrawlTaskStatus.PENDING
                    ).order_by(CrawlTask.created_at)
                    task = session.exec(statement).first()

                    if task:
                        await self._execute_task(task.id)

                # 等待一段时间再检查
                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"处理队列时出错: {e}")
                await asyncio.sleep(10)

    async def _execute_task(self, task_id: int):
        """
        执行爬取任务

        Args:
            task_id: 任务ID
        """
        self._current_task_id = task_id

        with Session(engine) as session:
            task = session.get(CrawlTask, task_id)
            if not task:
                return

            # 更新任务状态为运行中
            task.status = CrawlTaskStatus.RUNNING
            task.started_at = datetime.now(UTC)
            task.updated_at = datetime.now(UTC)
            session.add(task)
            session.commit()

            logger.info(f"开始执行爬取任务 #{task_id}")

        try:
            # 获取群组成员和总数
            with Session(engine) as session:
                task_ref = session.get(CrawlTask, task_id)
                group_id = task_ref.group_id
                total_users = task_ref.total_users
                crawl_channels_flag = task_ref.crawl_channels
                channel_depth_value = task_ref.channel_depth

                statement = select(GroupMember).where(
                    GroupMember.group_id == group_id,
                    GroupMember.is_active == True
                )
                members = session.exec(statement).all()

            # 逐个爬取用户
            for i, member in enumerate(members, 1):
                if not self._running:
                    break

                try:
                    # 更新当前进度
                    with Session(engine) as session:
                        task_obj = session.get(CrawlTask, task_id)
                        if task_obj:
                            task_obj.current_user_id = member.user_id
                            task_obj.processed_users = i
                            task_obj.progress_message = f"正在爬取用户 {i}/{total_users}"
                            task_obj.updated_at = datetime.now(UTC)
                            session.add(task_obj)
                            session.commit()

                    # 发送进度更新（每个用户都更新）
                    await self._send_progress_update(task_id)

                    # 爬取用户信息
                    profile = await self.user_crawler.crawl_user_with_delay(member.user_id)

                    # 如果需要爬取频道
                    if crawl_channels_flag and profile and profile.has_personal_channel:
                        await self.channel_crawler.crawl_user_channels(
                            member.user_id,
                            crawl_messages=True,
                            message_depth=channel_depth_value
                        )

                except Exception as e:
                    logger.error(f"爬取用户 {member.user_id} 失败: {e}")
                    with Session(engine) as session:
                        task_obj = session.get(CrawlTask, task_id)
                        if task_obj:
                            task_obj.failed_users += 1
                            session.add(task_obj)
                            session.commit()

            # 任务完成
            with Session(engine) as session:
                task_obj = session.get(CrawlTask, task_id)
                if task_obj:
                    task_obj.status = CrawlTaskStatus.COMPLETED
                    task_obj.completed_at = datetime.now(UTC)
                    task_obj.updated_at = datetime.now(UTC)
                    task_obj.progress_message = "爬取完成"
                    session.add(task_obj)
                    session.commit()

            logger.info(f"✅ 爬取任务 #{task_id} 完成")
            await self._send_completion_message(task_id)

        except Exception as e:
            logger.error(f"执行任务 #{task_id} 失败: {e}")
            with Session(engine) as session:
                task_obj = session.get(CrawlTask, task_id)
                if task_obj:
                    task_obj.status = CrawlTaskStatus.FAILED
                    task_obj.error_message = str(e)
                    task_obj.updated_at = datetime.now(UTC)
                    session.add(task_obj)
                    session.commit()

        finally:
            self._current_task_id = None

    async def _send_progress_update(self, task_id: int):
        """发送进度更新消息（带防抖）"""
        if not self._bot:
            return

        try:
            with Session(engine) as session:
                task = session.get(CrawlTask, task_id)
                if not task or not task.status_chat_id or not task.status_message_id:
                    return

                percent = (task.processed_users / task.total_users * 100) if task.total_users > 0 else 0

                message_text = (
                    f"🔄 爬取进度\n\n"
                    f"进度: {task.processed_users}/{task.total_users} ({percent:.1f}%)\n"
                    f"失败: {task.failed_users}\n"
                    f"状态: {task.progress_message or '进行中'}"
                )

                await self._bot.edit_message_text(
                    chat_id=task.status_chat_id,
                    message_id=task.status_message_id,
                    text=message_text
                )

        except Exception as e:
            # 忽略消息未修改错误（内容相同时 Telegram 会报错）
            if "message is not modified" not in str(e).lower():
                logger.error(f"发送进度更新失败: {e}")

    async def _send_completion_message(self, task_id: int):
        """发送完成消息"""
        if not self._bot:
            return

        try:
            with Session(engine) as session:
                task = session.get(CrawlTask, task_id)
                if not task or not task.status_chat_id or not task.status_message_id:
                    return

                message_text = (
                    f"✅ 爬取完成！\n\n"
                    f"总用户数: {task.total_users}\n"
                    f"成功: {task.processed_users - task.failed_users}\n"
                    f"失败: {task.failed_users}"
                )

                await self._bot.edit_message_text(
                    chat_id=task.status_chat_id,
                    message_id=task.status_message_id,
                    text=message_text
                )

        except Exception as e:
            logger.error(f"发送完成消息失败: {e}")


# 全局单例实例
crawler_queue = CrawlerQueue()
