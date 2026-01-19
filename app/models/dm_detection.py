"""
DM 检测记录模型
记录成员在群组中使用 dm/pm 等关键词的次数
"""
from datetime import datetime, UTC
from typing import Optional
from sqlmodel import Field, SQLModel, Column, BigInteger


class DMDetection(SQLModel, table=True):
    """DM 检测统计表"""
    __tablename__ = "dm_detections"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    username: Optional[str] = Field(default=None, max_length=100)
    full_name: Optional[str] = Field(default=None, max_length=200)
    
    # DM 次数统计
    dm_count: int = Field(default=0, index=True)
    
    # 最后一次 DM 时间
    last_dm_at: Optional[datetime] = Field(default=None)
    
    # 时间戳
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DMDetectionLog(SQLModel, table=True):
    """DM 检测日志表（记录每次检测到的详情）"""
    __tablename__ = "dm_detection_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    message_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    
    # 检测到的关键词
    keyword: str = Field(max_length=10)  # dm 或 pm
    
    # 消息文本（可选，用于审计）
    message_text: Optional[str] = Field(default=None, max_length=500)
    
    # 时间戳
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

