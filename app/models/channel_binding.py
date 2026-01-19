from datetime import datetime, UTC
from typing import Optional
from sqlmodel import Field, SQLModel, Column, BigInteger


class ChannelBinding(SQLModel, table=True):
    """频道与用户绑定表

    一个频道只能和一个用户绑定（全局共享）
    一个用户可以绑定多个频道
    绑定后无法重复绑定，无法切换绑定其他用户，无法解绑
    绑定记录在所有群组中共享，但发言时需验证用户是否在该群
    """
    __tablename__ = "channel_bindings"

    id: Optional[int] = Field(default=None, primary_key=True)

    # 频道ID（负数）
    channel_id: int = Field(sa_column=Column(BigInteger, unique=True, index=True))

    # 绑定的用户ID
    user_id: int = Field(sa_column=Column(BigInteger, index=True))

    # 频道和用户信息
    channel_username: Optional[str] = None
    channel_title: Optional[str] = None
    user_username: Optional[str] = None
    user_full_name: str

    # 时间戳
    bound_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
