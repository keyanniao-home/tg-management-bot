"""
爬虫任务队列模型
"""

from datetime import datetime, UTC
from typing import Optional
from sqlmodel import Field, SQLModel, Column, BigInteger, Text
from enum import Enum


class CrawlTaskStatus(str, Enum):
    """爬虫任务状态"""
    PENDING = "pending"  # 待处理
    RUNNING = "running"  # 进行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 已取消


class CrawlTask(SQLModel, table=True):
    """爬虫任务"""
    __tablename__ = "crawl_tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group_configs.id", index=True)

    # 任务配置
    crawl_channels: bool = Field(default=False)  # 是否爬取频道
    channel_depth: int = Field(default=10)  # 频道消息爬取深度

    # 任务状态
    status: str = Field(default=CrawlTaskStatus.PENDING, index=True)
    total_users: int = Field(default=0)
    processed_users: int = Field(default=0)
    failed_users: int = Field(default=0)

    # 进度详情
    current_user_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    progress_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 状态消息（用于更新进度）
    status_chat_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    status_message_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))

    # 错误信息
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 创建者
    created_by_user_id: int = Field(sa_column=Column(BigInteger))
    created_by_username: Optional[str] = None

    # 时间信息
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
