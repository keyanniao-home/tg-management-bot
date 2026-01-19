from datetime import datetime, UTC
from typing import Optional
from sqlmodel import Field, SQLModel, Relationship, Column, TEXT, BigInteger, JSON


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    message_id: int = Field(index=True)
    group_id: int = Field(foreign_key="group_configs.id", index=True)
    member_id: Optional[int] = Field(default=None, foreign_key="group_members.id", index=True)

    # 用户ID (如果是用户消息)
    user_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True, index=True))

    # 频道信息 (如果是频道消息)
    sender_chat_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True, index=True))
    sender_chat_title: Optional[str] = None
    sender_chat_username: Optional[str] = Field(default=None, index=True)
    is_channel_message: bool = Field(default=False)

    # 话题信息 (如果群组开启了Forum模式)
    topic_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True, index=True))
    is_topic_message: bool = Field(default=False)

    # 消息内容
    message_type: str = Field(default="text")  # text, photo, video, document, sticker, etc.
    text: Optional[str] = Field(default=None, sa_column=Column(TEXT))

    # 扩展元数据 (JSON格式，用于存储额外信息如图片检测结果等)
    extra_data: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))

    # 回复信息
    reply_to_message_id: Optional[int] = None

    # 是否被删除
    is_deleted: bool = False
    deleted_at: Optional[datetime] = None
    deleted_by_admin_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))

    # 时间戳
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # 关系
    group: "GroupConfig" = Relationship(back_populates="messages")
    member: Optional["GroupMember"] = Relationship(back_populates="messages")
