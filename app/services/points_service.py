"""
积分系统服务
"""
from datetime import datetime, date, UTC
from typing import Optional, Tuple
from sqlmodel import Session, select, and_, func
from sqlalchemy import desc
from app.models import UserPoints, CheckIn, PointsTransaction
from app.config.settings import settings
from loguru import logger


class PointsService:
    """积分系统服务"""
    
    # 积分规则
    POINTS_MESSAGE = 1  # 每条消息
    POINTS_MESSAGE_DAILY_MAX = 5  # 每日消息积分上限
    POINTS_UPLOAD = 10  # 上传文件
    POINTS_RATING = 2  # 评分
    POINTS_CHECKIN_BASE = 5  # 签到基础分
    
    @staticmethod
    def is_enabled() -> bool:
        """检查积分系统是否启用"""
        return settings.points_enabled
    
    @staticmethod
    def get_or_create_user_points(
        session: Session,
        group_id: int,
        user_id: int
    ) -> UserPoints:
        """获取或创建用户积分记录"""
        statement = select(UserPoints).where(
            and_(
                UserPoints.group_id == group_id,
                UserPoints.user_id == user_id
            )
        )
        user_points = session.exec(statement).first()
        
        if not user_points:
            user_points = UserPoints(
                group_id=group_id,
                user_id=user_id
            )
            session.add(user_points)
            session.commit()
            session.refresh(user_points)
        
        return user_points
    
    @staticmethod
    def add_points(
        session: Session,
        group_id: int,
        user_id: int,
        points: int,
        transaction_type: str,
        description: Optional[str] = None,
        resource_id: Optional[int] = None
    ) -> bool:
        """
        添加积分
        
        Args:
            session: 数据库会话
            group_id: 群组ID
            user_id: 用户ID
            points: 积分数（可以是负数表示扣分）
            transaction_type: 交易类型（message, upload, checkin, rating等）
            description: 描述
            resource_id: 关联资源ID
            
        Returns:
            是否成功
        """
        if not PointsService.is_enabled():
            return False
        
        # 获取用户积分记录
        user_points = PointsService.get_or_create_user_points(session, group_id, user_id)
        
        # 特殊处理：消息积分每日上限
        if transaction_type == "message":
            today = date.today()
            if user_points.last_message_date != today:
                # 新的一天，重置
                user_points.message_points_today = 0
                user_points.last_message_date = today
            
            if user_points.message_points_today >= PointsService.POINTS_MESSAGE_DAILY_MAX:
                return False  # 已达上限
            
            user_points.message_points_today += points
        
        # 更新总积分
        user_points.total_points += points
        user_points.updated_at = datetime.now(UTC)
        session.add(user_points)
        
        # 记录交易
        transaction = PointsTransaction(
            group_id=group_id,
            user_id=user_id,
            points_change=points,
            transaction_type=transaction_type,
            description=description,
            resource_id=resource_id
        )
        session.add(transaction)
        session.commit()
        
        return True
    
    @staticmethod
    def check_in(
        session: Session,
        group_id: int,
        user_id: int,
        username: Optional[str],
        full_name: Optional[str]
    ) -> Tuple[bool, str, int]:
        """
        签到
        
        Returns:
            (是否成功, 消息, 获得的积分)
        """
        if not PointsService.is_enabled():
            return False, "积分系统未启用", 0
        
        today = date.today()
        
        # 检查今天是否已签到
        statement = select(CheckIn).where(
            and_(
                CheckIn.group_id == group_id,
                CheckIn.user_id == user_id,
                CheckIn.check_in_date == today
            )
        )
        existing_checkin = session.exec(statement).first()
        
        if existing_checkin:
            return False, "今天已经签到过了！", 0
        
        # 获取最近一次签到记录
        statement = (
            select(CheckIn)
            .where(
                and_(
                    CheckIn.group_id == group_id,
                    CheckIn.user_id == user_id
                )
            )
            .order_by(desc(CheckIn.check_in_date))
            .limit(1)
        )
        last_checkin = session.exec(statement).first()
        
        # 计算连续签到天数
        streak_days = 1
        total_check_ins = 1
        
        if last_checkin:
            total_check_ins = last_checkin.total_check_ins + 1
            yesterday = date.fromordinal(today.toordinal() - 1)
            
            if last_checkin.check_in_date == yesterday:
                # 连续签到
                streak_days = last_checkin.streak_days + 1
            # 否则重置为1
        
        # 计算积分（基础分 + 连续签到加成）
        points_earned = PointsService.POINTS_CHECKIN_BASE + min(streak_days - 1, 10)
        
        # 创建签到记录
        checkin = CheckIn(
            group_id=group_id,
            user_id=user_id,
            username=username,
            full_name=full_name,
            check_in_date=today,
            streak_days=streak_days,
            points_earned=points_earned,
            total_check_ins=total_check_ins
        )
        session.add(checkin)
        session.commit()
        
        # 添加积分
        PointsService.add_points(
            session,
            group_id,
            user_id,
            points_earned,
            "checkin",
            f"签到第{total_check_ins}天，连续{streak_days}天"
        )
        
        message = f"签到成功！获得 {points_earned} 积分\n"
        if streak_days > 1:
            message += f"已连续签到 {streak_days} 天 🎉"
        
        return True, message, points_earned
    
    @staticmethod
    def get_points_rank(
        session: Session,
        group_id: int,
        limit: int = 10
    ) -> list[Tuple[int, int, str]]:
        """
        获取积分排行榜
        
        Returns:
            [(user_id, total_points, 排名), ...]
        """
        statement = (
            select(UserPoints.user_id, UserPoints.total_points)
            .where(UserPoints.group_id == group_id)
            .order_by(desc(UserPoints.total_points))
            .limit(limit)
        )
        
        results = session.exec(statement).all()
        
        # 添加排名
        ranked = [(user_id, points, idx + 1) for idx, (user_id, points) in enumerate(results)]
        
        return ranked


# 全局服务实例
points_service = PointsService()
