from datetime import datetime, UTC
from typing import Optional
from sqlmodel import Field, SQLModel, Relationship, Column, BigInteger


class GroupMember(SQLModel, table=True):
    __tablename__ = "group_members"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group_configs.id", index=True)
    user_id: int = Field(sa_column=Column(BigInteger, index=True))
    username: Optional[str] = None
    full_name: str

    # 成员统计
    message_count: int = Field(default=0)
    last_message_at: Optional[datetime] = None

    # 警告次数
    warning_count: int = Field(default=0)

    # 加入信息
    joined_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    invited_by_user_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))

    # 软删除
    is_active: bool = True
    left_at: Optional[datetime] = None

    # 时间戳
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # 关系
    group: "GroupConfig" = Relationship(back_populates="members")
    messages: list["Message"] = Relationship(back_populates="member")
