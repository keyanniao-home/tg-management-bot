from datetime import datetime, UTC
from typing import Optional
from sqlmodel import Field, SQLModel, Relationship, Column, JSON, BigInteger


class GroupConfig(SQLModel, table=True):
    __tablename__ = "group_configs"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(sa_column=Column(BigInteger, unique=True, index=True))
    group_name: str

    # 群组配置 (JSON格式，通过 /config 命令修改)
    # 可配置项:
    # - stats_display_mode: 统计显示模式, "mention" (默认, @或高亮), "name_id" (名字+ID), "name" (只显示名字)
    # - inactive_display_mode: 不活跃用户显示模式, "mention" (默认, @或高亮), "name_id" (名字+ID), "name" (只显示名字)
    # - image_detection: 图像识别配置
    #   - min_confidence: 最小置信度阈值 (0.1-0.99, 默认 0.1)
    config: dict = Field(default_factory=dict, sa_column=Column(JSON))

    # 白名单用户 ID 列表（踢人时豁免）
    whitelist: list[int] = Field(default_factory=list, sa_column=Column(JSON))

    # 是否已初始化（通过 /init 命令）
    is_initialized: bool = Field(default=False)
    initialized_by_user_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))

    # 时间戳
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # 关系
    admins: list["GroupAdmin"] = Relationship(back_populates="group")
    members: list["GroupMember"] = Relationship(back_populates="group")
    messages: list["Message"] = Relationship(back_populates="group")
    bans: list["BanRecord"] = Relationship(back_populates="group")
    # New relationships
    # resources: list["Resource"] = Relationship(back_populates="group")
    # summaries: list["MessageSummary"] = Relationship(back_populates="group")
    # user_points: list["UserPoints"] = Relationship(back_populates="group")
    # check_ins: list["CheckIn"] = Relationship(back_populates="group")
    # points_transactions: list["PointsTransaction"] = Relationship(back_populates="group")
    # dm_relays: list["DMRelay"] = Relationship(back_populates="group")


class GroupAdmin(SQLModel, table=True):
    __tablename__ = "group_admins"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group_configs.id", index=True)
    user_id: int = Field(sa_column=Column(BigInteger, index=True))
    username: Optional[str] = None
    full_name: str

    # 权限等级: 1=超级管理员(群主/拉人进群者), 2=普通管理员
    permission_level: int = Field(default=2)

    # 谁任命的这个管理员
    appointed_by_user_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))

    # 时间戳
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_active: bool = True

    # 关系
    group: GroupConfig = Relationship(back_populates="admins")


class BanRecord(SQLModel, table=True):
    __tablename__ = "ban_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group_configs.id", index=True)
    user_id: int = Field(sa_column=Column(BigInteger, index=True))
    username: Optional[str] = None
    full_name: str

    # 封禁信息
    ban_days: Optional[int] = None  # None表示永久封禁
    reason: Optional[str] = None
    banned_by_admin_id: int = Field(sa_column=Column(BigInteger))

    # 时间戳
    banned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    unbanned_at: Optional[datetime] = None
    is_active: bool = True  # True=当前封禁中, False=已解封

    # 关系
    group: GroupConfig = Relationship(back_populates="bans")

