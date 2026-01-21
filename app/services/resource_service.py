"""
资源管理服务层

提供资源、分类、标签的数据库操作服务

服务类说明：
    - ResourceService: 资源的 CRUD 操作
    - CategoryService: 分类管理，支持话题自动同步
    - TagService: 标签管理

核心功能：
    1. 资源创建和搜索
    2. 分类的创建、查询和话题自动同步
    3. 标签的创建和查询

话题自动同步：
    通过 CategoryService.get_or_create_by_topic() 方法
    当检测到话题消息时，自动创建或获取对应的分类
    分类 topic_id 字段用于关联 Telegram Forum Topic
"""
from typing import Optional, List, Tuple
from sqlmodel import Session, select, or_, func, and_
from sqlalchemy import desc
from app.models import Resource, Category, Tag, ResourceTag, ResourceEdit
from loguru import logger


class ResourceService:
    """资源管理服务"""
    
    @staticmethod
    def create_resource(
        session: Session,
        group_id: int,
        message_id: int,
        message_thread_id: Optional[int],
        uploader_id: int,
        uploader_username: Optional[str],
        uploader_first_name: Optional[str],
        category_id: Optional[int],
        title: Optional[str],
        description: Optional[str],
        file_type: Optional[str],
        file_id: Optional[str],
        file_unique_id: Optional[str],
        file_name: Optional[str],
        file_size: Optional[int],
    ) -> Resource:
        """创建资源"""
        resource = Resource(
            group_id=group_id,
            message_id=message_id,
            message_thread_id=message_thread_id,
            uploader_id=uploader_id,
            uploader_username=uploader_username,
            uploader_first_name=uploader_first_name,
            category_id=category_id,
            title=title,
            description=description,
            file_type=file_type,
            file_id=file_id,
            file_unique_id=file_unique_id,
            file_name=file_name,
            file_size=file_size,
        )
        session.add(resource)
        session.commit()
        session.refresh(resource)
        
        return resource
    
    @staticmethod
    def add_tags_to_resource(
        session: Session,
        resource_id: int,
        tag_ids: List[int],
        added_by: int
    ):
        """给资源添加标签"""
        for tag_id in tag_ids:
            resource_tag = ResourceTag(
                resource_id=resource_id,
                tag_id=tag_id,
                added_by=added_by
            )
            session.add(resource_tag)
        session.commit()
    
    @staticmethod
    def search_resources(
        session: Session,
        group_id: int,
        keyword: Optional[str] = None,
        message_thread_id: Optional[int] = None,
        limit: int = 20
    ) -> Tuple[List[Resource], int]:
        """
        搜索资源
        
        Returns:
            (资源列表, 总数)
        """
        statement = select(Resource).where(Resource.group_id == group_id)
        count_statement = select(func.count(Resource.id)).where(Resource.group_id == group_id)
        
        # 话题过滤 - 已移除，使资源全群共享
        # if message_thread_id is not None:
        #     statement = statement.where(Resource.message_thread_id == message_thread_id)
        #     count_statement = count_statement.where(Resource.message_thread_id == message_thread_id)
        
        # 关键词搜索
        if keyword:
            keyword_filter = or_(
                Resource.title.ilike(f"%{keyword}%"),
                Resource.description.ilike(f"%{keyword}%"),
                Resource.file_name.ilike(f"%{keyword}%")
            )
            statement = statement.where(keyword_filter)
            count_statement = count_statement.where(keyword_filter)
        
        # 排序
        statement = statement.order_by(desc(Resource.created_at)).limit(limit)
        
        resources = list(session.exec(statement).all())
        total = session.exec(count_statement).one()
        
        return list(resources), total
    
    @staticmethod
    def list_resources(
        session: Session,
        group_id: int,
        category_id: Optional[int] = None,
        tag_ids: Optional[List[int]] = None,
        message_thread_id: Optional[int] = None,
        limit: int = 5,
        offset: int = 0
    ) -> Tuple[List[Resource], int]:
        """
        列出资源（支持筛选和分页）
        
        Args:
            session: 数据库会话
            group_id: 群组ID  
            category_id: 分类ID筛选（可选）
            tag_ids: 标签ID列表筛选（可选）
            message_thread_id: 话题ID筛选（可选）
            limit: 每页数量
            offset: 偏移量
            
        Returns:
            (资源列表, 总数)
        """
        # 构建基础查询
        statement = select(Resource).where(Resource.group_id == group_id)
        
        # 分类筛选
        if category_id:
            statement = statement.where(Resource.category_id == category_id)
        
        # 话题筛选 - 已移除，使资源全群共享
        # if message_thread_id:
        #     statement = statement.where(Resource.message_thread_id == message_thread_id)
        
        # 标签筛选
        if tag_ids:
            statement = (
                statement
                .join(ResourceTag, Resource.id == ResourceTag.resource_id)
                .where(ResourceTag.tag_id.in_(tag_ids))
                .distinct()
            )
        
        # 计算总数
        count_statement = select(func.count()).select_from(statement.subquery())
        total = session.exec(count_statement).one()
        
        # 分页和排序
        statement = statement.order_by(desc(Resource.created_at)).offset(offset).limit(limit)
        resources = list(session.exec(statement).all())
        
        return resources, total
    
    @staticmethod
    def delete_resource(
        session: Session,
        resource_id: int,
        user_id: int,
        is_admin: bool = False
    ) -> Tuple[bool, str]:
        """
        删除资源（软删除）
        
        Args:
            session: 数据库会话
            resource_id: 资源ID
            user_id: 执行删除的用户ID
            is_admin: 是否是管理员
            
        Returns:
            (成功标志, 消息)
        """
        from datetime import datetime, UTC
        
        resource = session.get(Resource, resource_id)
        
        if not resource:
            return False, "资源不存在"
        
        # 检查权限
        if not ResourceService.can_delete_resource(resource, user_id, is_admin):
            return False, "无权限删除此资源"
        
        # 软删除
        resource.deleted_at = datetime.now(UTC)
        session.add(resource)
        session.commit()
        
        logger.info(f"Resource {resource_id} deleted by user {user_id}")
        return True, "资源已删除"
    
    @staticmethod
    def can_delete_resource(resource: Resource, user_id: int, is_admin: bool = False) -> bool:
        """
        检查用户是否有权限删除资源
        
        Args:
            resource: 资源对象
            user_id: 用户ID
            is_admin: 是否是管理员
            
        Returns:
            是否有权限
        """
        # 管理员可以删除任何资源
        if is_admin:
            return True
        
        # 上传者可以删除自己的资源
        if resource.uploader_id == user_id:
            return True
        
        return False


class CategoryService:
    """分类服务"""
    
    @staticmethod
    def create_category(
        session: Session,
        group_id: int,
        name: str,
        description: Optional[str] = None,
        topic_id: Optional[int] = None
    ) -> Optional[Category]:
        """创建分类（如果已存在则返回None）"""
        # 检查是否已存在
        statement = select(Category).where(
            Category.group_id == group_id,
            Category.name == name
        )
        existing = session.exec(statement).first()
        if existing:
            return None
        
        category = Category(
            group_id=group_id,
            name=name,
            description=description,
            topic_id=topic_id
        )
        session.add(category)
        session.commit()
        session.refresh(category)
        return category
    
    @staticmethod
    def get_categories(session: Session, group_id: int) -> List[Category]:
        """获取所有分类"""
        return list(session.exec(select(Category).where(Category.group_id == group_id)).all())
    
    @staticmethod
    def get_or_create_by_topic(
        session: Session,
        group_id: int,
        topic_id: int,
        topic_name: str
    ) -> Category:
        """通过话题ID获取或创建分类（用于自动同步）"""
        # 优先通过topic_id查找
        statement = select(Category).where(
            Category.group_id == group_id,
            Category.topic_id == topic_id
        )
        category = session.exec(statement).first()
        
        if category:
            return category
        
        # 不存在，创建新分类
        category = Category(
            group_id=group_id,
            name=f"话题-{topic_name}" if topic_name else f"话题{topic_id}",
            description=f"自动同步自话题",
            topic_id=topic_id
        )
        session.add(category)
        session.commit()
        session.refresh(category)
        
        logger.info(f"自动创建分类: {category.name} (group_id={group_id}, topic_id={topic_id})")
        return category


class TagService:
    """标签服务"""
    
    @staticmethod
    def create_tag(session: Session, group_id: int, name: str) -> Optional[Tag]:
        """创建标签"""
        # 检查是否已存在
        existing = session.exec(
            select(Tag).where(and_(Tag.group_id == group_id, Tag.name == name))
        ).first()
        
        if existing:
            return None
        
        tag = Tag(group_id=group_id, name=name)
        session.add(tag)
        session.commit()
        session.refresh(tag)
        return tag
    
    @staticmethod
    def get_tags(session: Session, group_id: int) -> List[Tag]:
        """获取所有标签"""
        return list(session.exec(select(Tag).where(Tag.group_id == group_id)).all())
