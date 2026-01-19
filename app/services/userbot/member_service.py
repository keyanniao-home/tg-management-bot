"""
成员导入服务

使用 User Bot 拉取群组成员并导入数据库
这是 Bot API 无法实现的功能，需要使用用户账号进行操作
"""

import asyncio
from datetime import datetime, UTC
from typing import Optional

from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
from sqlmodel import Session, select
from loguru import logger

from app.models import GroupConfig, GroupMember
from app.database.connection import engine
from app.services.userbot.client import UserBotClient


class MemberImportService:
    """成员导入服务"""

    def __init__(self, batch_size: int = 200):
        """
        初始化成员导入服务

        Args:
            batch_size: 每次拉取的成员数量
        """
        self.batch_size = batch_size

    async def fetch_all_members(self, group_entity, userbot_client: UserBotClient) -> list:
        """
        拉取群组的所有成员

        Args:
            group_entity: 群组实体对象
            userbot_client: User Bot 客户端

        Returns:
            成员列表
        """
        if not userbot_client.is_connected():
            raise RuntimeError("User Bot 客户端未连接")

        all_participants = []
        offset = 0

        logger.info(f"开始拉取群组成员...")

        while True:
            try:
                participants = await userbot_client.client(GetParticipantsRequest(
                    channel=group_entity,
                    filter=ChannelParticipantsSearch(''),
                    offset=offset,
                    limit=self.batch_size,
                    hash=0
                ))

                if not participants.users:
                    break

                all_participants.extend(participants.users)
                offset += len(participants.users)

                logger.info(f"已拉取 {len(all_participants)} 个成员...")

                if len(participants.users) < self.batch_size:
                    break

                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"拉取成员时出错: {e}")
                break

        logger.info(f"✅ 总共拉取到 {len(all_participants)} 个成员")
        return all_participants

    async def get_or_create_group_config(self, group_id: int, group_name: str = None) -> GroupConfig:
        """
        获取或创建群组配置

        Args:
            group_id: 群组ID（Bot API 格式）
            group_name: 群组名称（可选）

        Returns:
            群组配置对象
        """
        with Session(engine) as session:
            statement = select(GroupConfig).where(GroupConfig.group_id == group_id)
            group = session.exec(statement).first()

            if not group:
                logger.info(f"群组 {group_id} 未在数据库中初始化，正在创建...")
                group = GroupConfig(
                    group_id=group_id,
                    group_name=group_name or "Imported Group",
                    is_initialized=False
                )
                session.add(group)
                session.commit()
                session.refresh(group)
                logger.info(f"已创建群组记录，数据库ID: {group.id}")

            return group

    def import_member_to_db(
        self,
        session: Session,
        group_db_id: int,
        participant,
        index: int,
        total: int
    ) -> str:
        """
        导入单个成员到数据库

        Args:
            session: 数据库会话
            group_db_id: 群组数据库ID
            participant: 成员对象
            index: 当前索引
            total: 总数

        Returns:
            状态标识 - "added", "updated", "skipped"
        """
        user = participant

        # 跳过已删除的账号
        if user.deleted:
            logger.debug(f"[{index}/{total}] ⏭️  跳过已删除账号 (ID: {user.id})")
            return "skipped"

        # 跳过 bot 账号
        if user.bot:
            logger.debug(f"[{index}/{total}] 🤖 跳过机器人账号 (ID: {user.id})")
            return "skipped"

        user_id = user.id
        username = user.username or ""

        # 构建全名
        full_name_parts = []
        if user.first_name:
            full_name_parts.append(user.first_name)
        if user.last_name:
            full_name_parts.append(user.last_name)
        full_name = ' '.join(full_name_parts) if full_name_parts else f"User{user_id}"

        # 查询是否已存在
        statement = select(GroupMember).where(
            GroupMember.group_id == group_db_id,
            GroupMember.user_id == user_id
        )
        member = session.exec(statement).first()

        username_display = f"@{username}" if username else "(无用户名)"

        if member:
            # 更新现有成员
            member.username = username
            member.full_name = full_name
            member.is_active = True
            member.left_at = None
            member.updated_at = datetime.now(UTC)
            session.add(member)
            logger.info(f"[{index}/{total}] 🔄 更新: {full_name} {username_display} (ID: {user_id})")
            return "updated"
        else:
            # 新增成员
            new_member = GroupMember(
                group_id=group_db_id,
                user_id=user_id,
                username=username,
                full_name=full_name,
                is_active=True,
                joined_at=datetime.now(UTC)
            )
            session.add(new_member)
            logger.info(f"[{index}/{total}] ✅ 新增: {full_name} {username_display} (ID: {user_id})")
            return "added"

    async def import_members(
        self,
        group_identifier: str | int,
        userbot_client: UserBotClient,
        progress_callback: Optional[callable] = None
    ) -> dict:
        """
        拉取并导入群组成员

        Args:
            group_identifier: 群组标识（可以是数字ID或 @username）
            userbot_client: User Bot 客户端
            progress_callback: 进度回调函数（可选）

        Returns:
            导入结果统计
        """
        if not userbot_client.is_connected():
            raise RuntimeError("User Bot 客户端未连接，请先启动客户端")

        # 获取群组实体
        try:
            group_entity = await userbot_client.get_entity(group_identifier)
        except Exception as e:
            logger.error(f"获取群组失败: {e}")
            raise

        # 转换为 Bot API 格式的 ID
        bot_api_group_id = UserBotClient.convert_to_bot_api_id(group_entity.id)

        logger.info(f"✅ 找到群组: {group_entity.title}")
        logger.info(f"   Telethon ID: {group_entity.id}")
        logger.info(f"   Bot API ID: {bot_api_group_id}")
        logger.info(f"   成员数: {getattr(group_entity, 'participants_count', '未知')}")

        # 获取或创建群组配置
        group_config = await self.get_or_create_group_config(
            bot_api_group_id,
            group_entity.title
        )

        # 拉取所有成员
        participants = await self.fetch_all_members(group_entity, userbot_client)

        if not participants:
            logger.warning("⚠️ 未获取到任何成员")
            return {
                "total": 0,
                "added": 0,
                "updated": 0,
                "skipped": 0,
                "error": 0
            }

        # 导入到数据库
        logger.info(f"开始导入 {len(participants)} 个成员到数据库...")

        added_count = 0
        updated_count = 0
        skipped_count = 0
        error_count = 0
        total = len(participants)

        with Session(engine) as session:
            for i, participant in enumerate(participants, 1):
                try:
                    status = self.import_member_to_db(
                        session,
                        group_config.id,
                        participant,
                        i,
                        total
                    )

                    if status == "added":
                        added_count += 1
                    elif status == "updated":
                        updated_count += 1
                    else:
                        skipped_count += 1

                    # 每100个提交一次
                    if i % 100 == 0:
                        session.commit()
                        logger.info(f"--- 已提交 {i} 条记录 ---")

                    # 调用进度回调
                    if progress_callback:
                        await progress_callback(i, total)

                except Exception as e:
                    error_count += 1
                    logger.error(f"[{i}/{total}] ❌ 错误: {participant.id} - {e}")

            session.commit()

        result = {
            "total": total,
            "added": added_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "error": error_count,
            "group_id": bot_api_group_id,
            "group_name": group_entity.title
        }

        logger.info("=" * 60)
        logger.info("✅ 导入完成！")
        logger.info(f"   总成员数: {total}")
        logger.info(f"   新增: {added_count}")
        logger.info(f"   更新: {updated_count}")
        logger.info(f"   跳过: {skipped_count}")
        if error_count > 0:
            logger.warning(f"   错误: {error_count}")
        logger.info("=" * 60)

        return result
