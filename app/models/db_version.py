from datetime import datetime, UTC
from typing import Optional
from sqlmodel import Field, SQLModel


class DBVersion(SQLModel, table=True):
    """数据库版本管理表

    记录数据库结构版本和迁移历史
    """
    __tablename__ = "db_versions"

    id: Optional[int] = Field(default=None, primary_key=True)

    # 版本号
    version: int = Field(unique=True, index=True)

    # 版本描述
    description: str

    # 迁移脚本名称
    migration_script: str

    # 是否已应用
    is_applied: bool = Field(default=False)

    # 应用时间
    applied_at: Optional[datetime] = None

    # 创建时间
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
