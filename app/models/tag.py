"""
标签模型
用于为资源添加标签，支持多标签
"""
from typing import Optional
from datetime import datetime
from sqlmodel import Field, SQLModel, Column, BigInteger


class Tag(SQLModel, table=True):
    """标签表"""
    __tablename__ = "tags"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, index=True),
        description="群组ID（BIGINT类型）"
    )
    name: str = Field(max_length=50, description="标签名称")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")

