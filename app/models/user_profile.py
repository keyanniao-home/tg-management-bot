"""
用户详细信息模型
存储通过 User Bot 爬取的用户完整信息
"""

from datetime import datetime, UTC
from typing import Optional
from sqlmodel import Field, SQLModel, Relationship, Column, BigInteger, Text


class UserProfile(SQLModel, table=True):
    """用户详细资料"""
    __tablename__ = "user_profiles"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(sa_column=Column(BigInteger, unique=True, index=True))

    # 基本信息
    username: Optional[str] = Field(default=None, index=True)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None

    # 详细信息
    bio: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 账号状态
    is_bot: bool = Field(default=False)
    is_verified: bool = Field(default=False)
    is_restricted: bool = Field(default=False)
    is_scam: bool = Field(default=False)
    is_fake: bool = Field(default=False)
    is_premium: bool = Field(default=False)

    # 关联频道
    has_personal_channel: bool = Field(default=False)
    personal_channel_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    personal_channel_username: Optional[str] = None

    # 爬取信息
    last_crawled_at: Optional[datetime] = None
    crawl_error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 时间戳
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # 关系
    channels: list["UserChannel"] = Relationship(back_populates="user_profile")


class UserChannel(SQLModel, table=True):
    """用户关联的频道"""
    __tablename__ = "user_channels"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_profile_id: int = Field(foreign_key="user_profiles.id", index=True)
    channel_id: int = Field(sa_column=Column(BigInteger, index=True))

    # 频道信息
    channel_username: Optional[str] = Field(default=None, index=True)
    channel_title: Optional[str] = None
    channel_about: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 频道统计
    subscribers_count: int = Field(default=0)

    # 是否是个人频道
    is_personal_channel: bool = Field(default=False)

    # 爬取状态
    is_crawled: bool = Field(default=False)
    last_crawled_at: Optional[datetime] = None

    # 时间戳
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # 关系
    user_profile: UserProfile = Relationship(back_populates="channels")
    messages: list["ChannelMessage"] = Relationship(back_populates="channel")


class ChannelMessage(SQLModel, table=True):
    """频道消息"""
    __tablename__ = "channel_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    channel_id: int = Field(foreign_key="user_channels.id", index=True)
    message_id: int = Field(sa_column=Column(BigInteger, index=True))

    # 消息内容
    text: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 消息类型
    has_media: bool = Field(default=False)
    media_type: Optional[str] = None  # photo, video, document, etc.

    # 消息状态
    is_pinned: bool = Field(default=False)
    views: int = Field(default=0)
    forwards: int = Field(default=0)

    # 消息时间
    posted_at: datetime
    edited_at: Optional[datetime] = None

    # 时间戳
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # 关系
    channel: UserChannel = Relationship(back_populates="messages")
