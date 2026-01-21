"""
资源模型
用于存储上传的文件资源及其元数据
支持话题功能：通过message_thread_id标识资源所属话题
"""
from typing import Optional
from datetime import datetime
from sqlmodel import Field, SQLModel, Column, BigInteger


class Resource(SQLModel, table=True):
    """资源表 - 存储文件及其元数据"""
    __tablename__ = "resources"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, index=True),
        description="群组ID（BIGINT类型）"
    )
    message_id: int = Field(description="消息ID")
    message_thread_id: Optional[int] = Field(default=None, index=True, description="话题ID（Forum模式）")
    
    # 上传者信息
    uploader_id: int = Field(description="上传者用户ID")
    uploader_username: Optional[str] = Field(default=None, max_length=100, description="上传者用户名")
    uploader_first_name: Optional[str] = Field(default=None, max_length=100, description="上传者名字")
    
    # 分类和标题
    category_id: Optional[int] = Field(default=None, foreign_key="categories.id", description="分类ID")
    title: Optional[str] = Field(default=None, max_length=200, description="资源标题")
    description: Optional[str] = Field(default=None, description="资源描述/备注")
    
    # 文件信息
    file_type: Optional[str] = Field(default=None, max_length=50, description="文件类型")
    file_id: Optional[str] = Field(default=None, max_length=200, description="Telegram文件ID")
    file_unique_id: Optional[str] = Field(default=None, max_length=200, description="Telegram唯一文件ID")
    file_name: Optional[str] = Field(default=None, max_length=200, description="文件名")
    file_size: Optional[int] = Field(default=None, description="文件大小（字节）")
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")
    deleted_at: Optional[datetime] = Field(default=None, description="软删除时间戳")


class ResourceTag(SQLModel, table=True):
    """资源-标签关联表 - 多对多关系"""
    __tablename__ = "resource_tags"
    
    resource_id: int = Field(foreign_key="resources.id", primary_key=True, description="资源ID")
    tag_id: int = Field(foreign_key="tags.id", primary_key=True, description="标签ID")
    added_by: Optional[int] = Field(default=None, description="添加者用户ID（协作编辑）")
    added_at: datetime = Field(default_factory=datetime.utcnow, description="添加时间")


class ResourceEdit(SQLModel, table=True):
    """资源编辑记录 - 协作编辑历史"""
    __tablename__ = "resource_edits"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    resource_id: int = Field(foreign_key="resources.id", index=True, description="资源ID")
    editor_id: int = Field(description="编辑者用户ID")
    edit_type: str = Field(max_length=50, description="编辑类型：category/tag_add/tag_remove/description")
    old_value: Optional[str] = Field(default=None, description="旧值")
    new_value: Optional[str] = Field(default=None, description="新值")
    edited_at: datetime = Field(default_factory=datetime.utcnow, description="编辑时间")
