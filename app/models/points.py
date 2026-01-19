from datetime import datetime, UTC, date
from typing import Optional
from sqlmodel import Field, SQLModel, Relationship, Column, BigInteger, DATE


class UserPoints(SQLModel, table=True):
    """用户积分表"""

    __tablename__ = "user_points"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))

    # 积分统计
    total_points: int = Field(default=0, index=True)  # 总积分

    # 每日消息积分限制（防刷分）
    message_points_today: int = Field(default=0)  # 今日通过消息获得的积分
    last_message_date: Optional[date] = Field(
        default=None, sa_column=Column(DATE, nullable=True)
    )

    # 时间戳
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # 关系
    # group: "GroupConfig" = Relationship(back_populates="user_points")


class CheckIn(SQLModel, table=True):
    """签到记录表"""

    __tablename__ = "check_ins"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group_configs.id", index=True)
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    username: Optional[str] = None
    full_name: Optional[str] = None

    # 签到信息
    check_in_date: date = Field(sa_column=Column(DATE, nullable=False, index=True))
    streak_days: int = Field(default=1)  # 连续签到天数
    points_earned: int = Field(default=5)  # 本次签到获得的积分

    # 统计
    total_check_ins: int = Field(default=1)  # 历史总签到次数

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # 关系
    # group: "GroupConfig" = Relationship(back_populates="check_ins")


class PointsTransaction(SQLModel, table=True):
    """积分交易记录表（用于追踪积分变化）"""

    __tablename__ = "points_transactions"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))

    # 交易信息
    points_change: int  # 正数表示增加，负数表示减少
    transaction_type: str = Field(max_length=50)  # message, upload, checkin, rating等
    description: Optional[str] = None

    # 关联资源（如果是上传或评分）
    resource_id: Optional[int] = Field(default=None, foreign_key="resources.id")

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # 关系
    # group: "GroupConfig" = Relationship(back_populates="points_transactions")
