"""
每日推送配置数据模型
"""
from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


class DigestConfig(SQLModel, table=True):
    """每日推送配置"""
    __tablename__ = "digest_config"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(index=True, unique=True, description="群组ID")
    
    is_enabled: bool = Field(default=True, description="是否启用推送")
    push_hour: int = Field(default=9, description="推送小时(0-23)")
    push_minute: int = Field(default=0, description="推送分钟(0-59)")
    
    include_summary: bool = Field(default=True, description="包含消息总结")
    include_stats: bool = Field(default=True, description="包含活跃统计")
    include_hot_topics: bool = Field(default=False, description="包含热门话题")
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
