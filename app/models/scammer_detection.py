"""
号商检测结果模型
存储号商检测的历史记录和缓存
"""

from datetime import datetime, UTC
from typing import Optional
from sqlmodel import Field, SQLModel, Column, BigInteger, Text, JSON
from sqlalchemy import Index


class ScammerDetectionRecord(SQLModel, table=True):
    """号商检测记录"""
    __tablename__ = "scammer_detection_records"

    id: Optional[int] = Field(default=None, primary_key=True)

    # 检测目标
    group_id: int = Field(sa_column=Column(BigInteger, index=True))
    user_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True, index=True))

    # 检测类型: 'single' 单用户, 'group' 全群
    detection_type: str = Field(index=True)

    # 检测结果
    is_scammer: bool
    confidence: float  # 0-1
    evidence: str = Field(sa_column=Column(Text))

    # 用户信息快照（用于展示）
    user_snapshot: dict = Field(sa_column=Column(JSON))  # {user_id: {username, full_name, ...}}

    # 爬虫任务ID（如果是全群检测）
    crawl_task_id: Optional[int] = None

    # 执行信息
    detected_by_user_id: int = Field(sa_column=Column(BigInteger))  # 执行检测的管理员
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)

    # 处理状态
    is_kicked: bool = Field(default=False)
    kicked_at: Optional[datetime] = None
    kicked_by_user_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))

    # 缓存过期时间（仅用于全群检测）
    expires_at: Optional[datetime] = Field(default=None, index=True)

    # 时间戳
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    __table_args__ = (
        # 组合索引：按群组和过期时间查询有效缓存
        Index('ix_group_expires', 'group_id', 'expires_at'),
        # 组合索引：按群组、用户和检测时间查询单用户历史
        Index('ix_group_user_detected', 'group_id', 'user_id', 'detected_at'),
    )
