"""
私信转达模型
支持成员间通过Bot转发私信，并提供阅读回执功能
"""
from typing import Optional
from datetime import datetime
from sqlmodel import Field, SQLModel, Column, BigInteger


class DMRelay(SQLModel, table=True):
    """私信转达表"""
    __tablename__ = "dm_relays"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, index=True),
        description="群组ID（BIGINT类型）"
    )
    
    # 发送者和接收者
    from_user_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, index=True),
        description="发送者用户ID"
    )
    from_username: Optional[str] = Field(default=None, max_length=100, description="发送者用户名")
    to_user_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, index=True),
        description="接收者用户ID"
    )
    to_username: Optional[str] = Field(default=None, max_length=100, description="接收者用户名")
    
    # 消息内容
    message: str = Field(description="消息内容")
    
    # 状态跟踪
    delivered: bool = Field(default=False, description="是否已送达")
    delivered_at: Optional[datetime] = Field(default=None, description="送达时间")
    
    read: bool = Field(default=False, description="是否已读（阅读回执）")
    read_at: Optional[datetime] = Field(default=None, description="已读时间")
    
    # 消息ID（用于追踪）
    bot_message_id: Optional[int] = Field(default=None, description="Bot发送的消息ID")
    notification_message_id: Optional[int] = Field(default=None, description="群组通知消息ID")
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")


class DMReadReceipt(SQLModel, table=True):
    """私信阅读回执"""
    __tablename__ = "dm_read_receipts"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    dm_relay_id: int = Field(foreign_key="dm_relays.id", unique=True, description="私信转达ID")
    read_by: int = Field(
        sa_column=Column(BigInteger, nullable=False),
        description="确认已读的用户ID"
    )
    read_at: datetime = Field(default_factory=datetime.utcnow, description="确认已读时间")
