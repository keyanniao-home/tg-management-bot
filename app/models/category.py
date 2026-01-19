"""
资源分类模型

用于管理上传文件的分类系统

字段说明：
    - id: 主键，自增ID
    - group_id: 群组ID（BIGINT 类型，支持大数值的 Telegram 群组 ID）
    - name: 分类名称，最大50字符
    - description: 分类描述，可选
    - topic_id: 关联的话题ID（Forum模式），用于自动同步功能
    - created_at: 创建时间

话题自动同步：
    当 topic_id 不为空时，表示该分类是从 Forum Topic 自动同步创建的
    Bot 会在用户发送话题消息时自动创建对应的分类
    
注意事项：
    - group_id 必须使用 BigInteger 类型，因为 Telegram 群组 ID 可能超出 INTEGER 范围
    - topic_id 也使用 BigInteger 类型以保持一致性
"""
from typing import Optional
from datetime import datetime
from sqlmodel import Field, SQLModel, Column, BigInteger


class Category(SQLModel, table=True):
    """资源分类表 - 用于文件分类管理和话题自动同步"""
    __tablename__ = "categories"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, index=True),
        description="群组ID（BIGINT类型，支持大数值）"
    )
    name: str = Field(max_length=50, description="分类名称")
    description: Optional[str] = Field(default=None, description="分类描述")
    topic_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True, index=True),
        description="关联的话题ID（Forum模式，用于自动同步）"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")

