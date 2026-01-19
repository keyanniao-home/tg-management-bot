from datetime import datetime, UTC
from typing import Optional
from sqlmodel import Field, SQLModel, Relationship, Column, TEXT, BigInteger


class MessageSummary(SQLModel, table=True):
    """消息总结表"""
    __tablename__ = "message_summaries"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group_configs.id", index=True)
    
    # 总结内容
    summary_text: str = Field(sa_column=Column(TEXT))
    summary_type: str = Field(max_length=50, default="manual")  # manual, daily, weekly
    
    # 时间范围
    time_range_start: datetime
    time_range_end: datetime
    
    # 话题ID（如果是针对特定话题的总结）
    topic_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    topic_name: Optional[str] = None
    
    # 消息统计
    message_count: int = Field(default=0)
    participant_count: int = Field(default=0)
    
    # 生成信息
    generated_by_user_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    
    # LLM使用信息（可选）
    llm_model: Optional[str] = None
    tokens_used: Optional[int] = None

    # 关系
    # group: "GroupConfig" = Relationship(back_populates="summaries")
