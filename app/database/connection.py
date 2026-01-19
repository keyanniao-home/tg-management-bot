from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import text
from app.config.settings import settings
from app.database.views import CREATE_MESSAGE_STATS_MATERIALIZED_VIEW

engine = create_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)


def create_db_and_tables():
    """创建数据库表和视图"""
    from loguru import logger

    # 导入所有模型以确保SQLModel能创建表
    from app.models.group import GroupConfig
    from app.models.member import GroupMember
    from app.models.message import Message
    from app.models.points import UserPoints, CheckIn, PointsTransaction
    from app.models.user_profile import UserProfile, UserChannel, ChannelMessage
    from app.models.channel_binding import ChannelBinding
    from app.models.scammer_detection import ScammerDetectionRecord
    from app.models.crawl_task import CrawlTask
    from app.models.summary import MessageSummary
    from app.models.db_version import DBVersion

    # 导入新增的资源管理模型
    from app.models.category import Category
    from app.models.tag import Tag
    from app.models.resource import Resource, ResourceTag, ResourceEdit
    from app.models.dm_relay import DMRelay, DMReadReceipt
    from app.models.dm_detection import DMDetection, DMDetectionLog

    logger.info("开始创建数据库表...")

    # 创建表
    SQLModel.metadata.create_all(engine)

    # 执行数据库迁移
    logger.info("检查数据库迁移...")
    try:
        from app.database.migrations import run_migrations

        run_migrations()
    except Exception as e:
        logger.error(f"数据库迁移失败: {e}")
        raise

    # 创建物化视图
    with Session(engine) as session:
        try:
            session.exec(text(CREATE_MESSAGE_STATS_MATERIALIZED_VIEW))
            session.commit()
            logger.info("物化视图创建成功")
        except Exception as e:
            # 如果视图已存在，忽略错误
            logger.debug(f"创建物化视图时出现警告: {e}")
            session.rollback()


def get_session():
    """获取数据库会话"""
    with Session(engine) as session:
        yield session


def refresh_message_stats():
    """刷新消息统计物化视图"""
    from app.database.views import REFRESH_MESSAGE_STATS_MATERIALIZED_VIEW

    with Session(engine) as session:
        session.exec(text(REFRESH_MESSAGE_STATS_MATERIALIZED_VIEW))
        session.commit()
