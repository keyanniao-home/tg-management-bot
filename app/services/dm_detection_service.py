"""
DM 检测服务
检测消息中的 dm/pm 关键词并记录统计
"""
import re
from datetime import datetime, UTC
from typing import Optional, List, Tuple
from sqlmodel import Session, select, and_
from sqlalchemy import func
from app.models.dm_detection import DMDetection, DMDetectionLog
from loguru import logger

# DM/PM 检测正则表达式
# 匹配 dm 或 pm，两边不能是字母或数字
DM_PATTERN = re.compile(r'(?<![a-zA-Z0-9])(dm|pm)(?![a-zA-Z0-9])', re.IGNORECASE)


class DMDetectionService:
    """DM 检测服务"""
    
    @staticmethod
    def check_message(text: str) -> List[str]:
        """
        检测消息中是否包含 dm/pm 关键词
        
        Args:
            text: 消息文本
            
        Returns:
            检测到的关键词列表（小写）
        """
        if not text:
            return []
        
        matches = DM_PATTERN.findall(text)
        return [m.lower() for m in matches]
    
    @staticmethod
    def record_detection(
        session: Session,
        group_id: int,
        user_id: int,
        username: Optional[str],
        full_name: Optional[str],
        message_id: int,
        keyword: str,
        message_text: Optional[str] = None
    ) -> DMDetection:
        """
        记录一次 DM 检测
        
        Args:
            session: 数据库会话
            group_id: 群组ID
            user_id: 用户ID
            username: 用户名
            full_name: 用户全名
            message_id: 消息ID
            keyword: 检测到的关键词
            message_text: 消息文本（可选）
            
        Returns:
            更新后的 DMDetection 记录
        """
        now = datetime.now(UTC)
        
        # 查找或创建用户统计记录
        statement = select(DMDetection).where(
            and_(
                DMDetection.group_id == group_id,
                DMDetection.user_id == user_id
            )
        )
        detection = session.exec(statement).first()
        
        if not detection:
            detection = DMDetection(
                group_id=group_id,
                user_id=user_id,
                username=username,
                full_name=full_name,
                dm_count=0,
                created_at=now
            )
            session.add(detection)
        
        # 更新统计
        detection.dm_count += 1
        detection.last_dm_at = now
        detection.updated_at = now
        if username:
            detection.username = username
        if full_name:
            detection.full_name = full_name
        
        session.add(detection)
        
        # 记录日志
        log = DMDetectionLog(
            group_id=group_id,
            user_id=user_id,
            message_id=message_id,
            keyword=keyword,
            message_text=message_text[:500] if message_text else None,
            created_at=now
        )
        session.add(log)
        
        session.commit()
        session.refresh(detection)
        
        logger.debug(f"DM detection recorded: user={user_id}, keyword={keyword}, total={detection.dm_count}")
        
        return detection
    
    @staticmethod
    def get_ranking(
        session: Session,
        group_id: int,
        limit: int = 10,
        offset: int = 0
    ) -> Tuple[List[DMDetection], int]:
        """
        获取 DM 榜单
        
        Args:
            session: 数据库会话
            group_id: 群组ID
            limit: 每页数量
            offset: 偏移量
            
        Returns:
            (排名列表, 总数)
        """
        # 查询总数
        count_stmt = select(func.count()).select_from(DMDetection).where(
            and_(
                DMDetection.group_id == group_id,
                DMDetection.dm_count > 0
            )
        )
        total = session.exec(count_stmt).one()
        
        # 查询排名
        statement = (
            select(DMDetection)
            .where(
                and_(
                    DMDetection.group_id == group_id,
                    DMDetection.dm_count > 0
                )
            )
            .order_by(DMDetection.dm_count.desc())
            .offset(offset)
            .limit(limit)
        )
        results = list(session.exec(statement).all())
        
        return results, total

