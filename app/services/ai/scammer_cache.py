"""
号商检测缓存服务

管理号商检测结果的缓存和批量检测
全群检测：3天TTL，缓存到数据库
单用户检测：无缓存
爬虫缓存：3天TTL
"""

from datetime import datetime, UTC, timedelta
from typing import Optional, List
from sqlmodel import Session, select, and_
from loguru import logger

from app.database.connection import engine
from app.models import ScammerDetectionRecord, GroupMember, UserProfile
from app.services.ai.scammer_detector import scammer_detector, ScammerDetectionResult


class ScammerCacheService:
    """号商检测缓存服务"""

    GROUP_CACHE_TTL_DAYS = 3  # 全群检测缓存3天
    CRAWL_CACHE_TTL_DAYS = 3  # 爬虫缓存3天

    async def detect_single_user(
        self,
        group_telegram_id: int,
        user_id: int,
        detected_by_user_id: int,
        use_cache: bool = True
    ) -> Optional[ScammerDetectionResult]:
        """
        检测单个用户（优先使用缓存）

        Args:
            group_telegram_id: Telegram 群组ID
            user_id: 用户ID
            detected_by_user_id: 执行检测的管理员ID
            use_cache: 是否使用缓存（所有有缓存的优先用缓存）

        Returns:
            检测结果，如果用户数据不足则返回 None
        """
        # 如果启用缓存，先检查数据库中是否有有效的缓存
        if use_cache:
            cached_result = self._get_cached_result(group_telegram_id, user_id)
            if cached_result:
                logger.info(f"使用缓存的检测结果: user_id={user_id}")
                return ScammerDetectionResult(
                    is_scammer=cached_result.is_scammer,
                    confidence=cached_result.confidence,
                    evidence=cached_result.evidence
                )

        # 执行实际检测
        logger.info(f"执行单用户检测: user_id={user_id}")
        result = await scammer_detector.detect_scammer(user_id)

        if result:
            # 单用户检测不设置过期时间（无缓存），但仍然存储到数据库作为历史记录
            self._save_detection_record(
                group_telegram_id=group_telegram_id,
                user_id=user_id,
                detection_type='single',
                result=result,
                detected_by_user_id=detected_by_user_id,
                expires_at=None  # 单用户无缓存
            )

        return result

    async def detect_group_users(
        self,
        group_telegram_id: int,
        detected_by_user_id: int,
        use_cache: bool = True
    ) -> List[dict]:
        """
        检测全群用户（使用缓存）

        Args:
            group_telegram_id: Telegram 群组ID
            detected_by_user_id: 执行检测的管理员ID
            use_cache: 是否使用缓存

        Returns:
            检测结果列表，每项包含 user_id, username, full_name, result
        """
        # 检查是否有有效的全群缓存
        if use_cache:
            cached_results = self._get_group_cached_results(group_telegram_id)
            if cached_results:
                logger.info(f"使用缓存的全群检测结果: {len(cached_results)} 条")
                return cached_results

        # 获取群组数据库ID
        from app.models import GroupConfig
        with Session(engine) as session:
            group_statement = select(GroupConfig).where(GroupConfig.group_id == group_telegram_id)
            group = session.exec(group_statement).first()

            if not group:
                logger.error(f"群组不存在: telegram_id={group_telegram_id}")
                return []

            group_db_id = group.id

        # 获取群组所有活跃成员
        logger.info(f"开始全群检测: telegram_group_id={group_telegram_id}, db_id={group_db_id}")
        with Session(engine) as session:
            statement = (
                select(GroupMember)
                .where(
                    and_(
                        GroupMember.group_id == group_db_id,
                        GroupMember.is_active == True,
                        GroupMember.user_id > 0  # 排除频道
                    )
                )
            )
            members = session.exec(statement).all()

        logger.info(f"找到 {len(members)} 个活跃成员")

        results = []
        expires_at = datetime.now(UTC) + timedelta(days=self.GROUP_CACHE_TTL_DAYS)

        for member in members:
            # 检查用户是否有爬虫数据（3天缓存）
            has_profile = self._check_user_profile_cache(member.user_id)
            if not has_profile:
                logger.warning(f"用户 {member.user_id} 没有爬虫数据，跳过")
                continue

            # 执行检测（优先使用缓存）
            result = await self.detect_single_user(
                group_telegram_id=group_telegram_id,
                user_id=member.user_id,
                detected_by_user_id=detected_by_user_id,
                use_cache=True  # 优先使用缓存
            )

            if result:
                # 保存到数据库并设置过期时间（全群缓存）
                self._save_detection_record(
                    group_telegram_id=group_telegram_id,
                    user_id=member.user_id,
                    detection_type='group',
                    result=result,
                    detected_by_user_id=detected_by_user_id,
                    expires_at=expires_at
                )

                results.append({
                    'user_id': member.user_id,
                    'username': member.username,
                    'full_name': member.full_name,
                    'result': result
                })

        logger.info(f"全群检测完成: {len(results)} 个用户有结果")
        return results

    def _get_cached_result(
        self,
        group_telegram_id: int,
        user_id: int
    ) -> Optional[ScammerDetectionRecord]:
        """
        获取单个用户的缓存结果（未过期的）

        Args:
            group_telegram_id: Telegram 群组ID
            user_id: 用户ID

        Returns:
            缓存的检测记录，如果没有或已过期则返回 None
        """
        with Session(engine) as session:
            now = datetime.now(UTC)
            statement = (
                select(ScammerDetectionRecord)
                .where(
                    and_(
                        ScammerDetectionRecord.group_id == group_telegram_id,
                        ScammerDetectionRecord.user_id == user_id,
                        # 要么没有过期时间（历史记录），要么未过期
                        (ScammerDetectionRecord.expires_at == None) |
                        (ScammerDetectionRecord.expires_at > now)
                    )
                )
                .order_by(ScammerDetectionRecord.detected_at.desc())
            )
            record = session.exec(statement).first()
            return record

    def _get_group_cached_results(self, group_telegram_id: int) -> Optional[List[dict]]:
        """
        获取全群的缓存结果

        Args:
            group_telegram_id: Telegram 群组ID

        Returns:
            缓存的检测结果列表，如果没有有效缓存则返回 None
        """
        with Session(engine) as session:
            now = datetime.now(UTC)
            statement = (
                select(ScammerDetectionRecord)
                .where(
                    and_(
                        ScammerDetectionRecord.group_id == group_telegram_id,
                        ScammerDetectionRecord.detection_type == 'group',
                        ScammerDetectionRecord.expires_at > now
                    )
                )
                .order_by(ScammerDetectionRecord.detected_at.desc())
            )
            records = session.exec(statement).all()

            if not records:
                return None

            # 检查缓存的一致性（所有记录应该来自同一次检测）
            first_detected_at = records[0].detected_at
            # 允许5分钟的时间差（考虑批量检测的时间）
            time_threshold = timedelta(minutes=5)

            valid_records = [
                r for r in records
                if abs((r.detected_at - first_detected_at).total_seconds()) < time_threshold.total_seconds()
            ]

            if not valid_records:
                return None

            # 转换为结果列表
            results = []
            for record in valid_records:
                user_snapshot = record.user_snapshot or {}
                user_info = user_snapshot.get(str(record.user_id), {})

                results.append({
                    'user_id': record.user_id,
                    'username': user_info.get('username'),
                    'full_name': user_info.get('full_name'),
                    'result': ScammerDetectionResult(
                        is_scammer=record.is_scammer,
                        confidence=record.confidence,
                        evidence=record.evidence
                    )
                })

            logger.info(f"找到有效的全群缓存: {len(results)} 条记录")
            return results

    def _check_user_profile_cache(self, user_id: int) -> bool:
        """
        检查用户爬虫数据是否在缓存期内（3天）

        Args:
            user_id: 用户ID

        Returns:
            是否有有效的爬虫数据
        """
        with Session(engine) as session:
            statement = select(UserProfile).where(UserProfile.user_id == user_id)
            profile = session.exec(statement).first()

            if not profile or not profile.last_crawled_at:
                return False

            # 检查爬虫数据是否在3天内
            now = datetime.now(UTC)
            cache_threshold = now - timedelta(days=self.CRAWL_CACHE_TTL_DAYS)

            # 确保 last_crawled_at 有时区信息
            last_crawled = profile.last_crawled_at
            if last_crawled.tzinfo is None:
                # 如果没有时区信息，假设为 UTC
                last_crawled = last_crawled.replace(tzinfo=UTC)

            return last_crawled > cache_threshold

    def _save_detection_record(
        self,
        group_telegram_id: int,
        user_id: int,
        detection_type: str,
        result: ScammerDetectionResult,
        detected_by_user_id: int,
        expires_at: Optional[datetime]
    ) -> None:
        """
        保存检测记录到数据库

        Args:
            group_telegram_id: Telegram 群组ID
            user_id: 用户ID
            detection_type: 检测类型 ('single' 或 'group')
            result: 检测结果
            detected_by_user_id: 执行检测的管理员ID
            expires_at: 过期时间（None表示不缓存）
        """
        from app.models import GroupConfig

        with Session(engine) as session:
            # 获取群组数据库ID
            group_statement = select(GroupConfig).where(GroupConfig.group_id == group_telegram_id)
            group = session.exec(group_statement).first()

            if not group:
                logger.error(f"群组不存在: telegram_id={group_telegram_id}")
                return

            group_db_id = group.id

            # 获取用户信息快照
            member_statement = (
                select(GroupMember)
                .where(
                    and_(
                        GroupMember.group_id == group_db_id,
                        GroupMember.user_id == user_id
                    )
                )
            )
            member = session.exec(member_statement).first()

            user_snapshot = {}
            if member:
                user_snapshot[str(user_id)] = {
                    'username': member.username,
                    'full_name': member.full_name,
                }

            # 创建记录（使用 Telegram 群组ID）
            record = ScammerDetectionRecord(
                group_id=group_telegram_id,
                user_id=user_id,
                detection_type=detection_type,
                is_scammer=result.is_scammer,
                confidence=result.confidence,
                evidence=result.evidence,
                user_snapshot=user_snapshot,
                detected_by_user_id=detected_by_user_id,
                expires_at=expires_at,
                detected_at=datetime.now(UTC)
            )

            session.add(record)
            session.commit()
            logger.debug(f"保存检测记录: user_id={user_id}, type={detection_type}")


# 全局实例
scammer_cache_service = ScammerCacheService()
