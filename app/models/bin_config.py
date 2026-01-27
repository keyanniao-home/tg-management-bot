from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Column, BigInteger, TEXT, Index


class BinConfig(SQLModel, table=True):
    """BIN监听配置表"""
    __tablename__ = "bin_configs"

    id: Optional[int] = Field(default=None, primary_key=True)

    # group_id存储数据库内部ID（GroupConfig.id），非Telegram ID
    group_id: int = Field(foreign_key="group_configs.id", index=True)
    topic_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))

    enabled: bool = Field(default=True, description="是否启用BIN监听")
    ai_prompt: Optional[str] = Field(default=None, sa_column=Column(TEXT))

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index("idx_bin_config_group_topic", "group_id", "topic_id", unique=True),
    )
