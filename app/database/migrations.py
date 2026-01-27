"""
数据库迁移系统

自动检测并执行数据库结构变更
"""
from datetime import datetime, UTC
from loguru import logger
from sqlalchemy import text, inspect
from sqlmodel import Session, select
from app.database.connection import engine


class Migration:
    """单个迁移定义"""

    def __init__(self, version: int, description: str):
        self.version = version
        self.description = description

    def check(self, session: Session) -> bool:
        """检查是否需要执行迁移（返回True表示需要执行）"""
        raise NotImplementedError

    def execute(self, session: Session):
        """执行迁移"""
        raise NotImplementedError

    def rollback(self, session: Session):
        """回滚迁移（可选）"""
        raise NotImplementedError


class Migration001_RemoveChannelBindingGroupId(Migration):
    """
    迁移001: 删除 channel_bindings 表的 group_id 字段

    变更内容:
    - 删除外键约束 channel_bindings_group_id_fkey
    - 删除字段 group_id
    - 改为全局共享绑定
    """

    def __init__(self):
        super().__init__(
            version=1,
            description="Remove group_id from channel_bindings table (global shared binding)"
        )

    def check(self, session: Session) -> bool:
        """检查 channel_bindings 表是否存在 group_id 字段"""
        try:
            inspector = inspect(engine)

            # 检查表是否存在
            if 'channel_bindings' not in inspector.get_table_names():
                logger.info("channel_bindings 表不存在，跳过迁移")
                return False

            # 检查 group_id 字段是否存在
            columns = inspector.get_columns('channel_bindings')
            column_names = [col['name'] for col in columns]

            if 'group_id' in column_names:
                logger.warning(f"检测到旧版本数据库结构: channel_bindings 表存在 group_id 字段")
                return True
            else:
                logger.info("channel_bindings 表已是最新结构")
                return False

        except Exception as e:
            logger.error(f"检查迁移状态失败: {e}")
            return False

    def execute(self, session: Session):
        """执行迁移"""
        logger.info("=" * 80)
        logger.info(f"开始执行迁移 #{self.version}: {self.description}")
        logger.info("=" * 80)

        try:
            # 1. 删除外键约束
            logger.info("Step 1/3: 删除外键约束...")
            session.exec(text("""
                ALTER TABLE channel_bindings
                DROP CONSTRAINT IF EXISTS channel_bindings_group_id_fkey;
            """))
            session.commit()  # DDL 需要立即提交
            logger.info("✅ 外键约束已删除")

            # 2. 处理重复数据（如果同一频道在多个群组绑定，保留最新的）
            logger.info("Step 2/3: 检查并处理重复数据...")
            duplicates = session.exec(text("""
                SELECT channel_id, COUNT(*) as cnt
                FROM channel_bindings
                GROUP BY channel_id
                HAVING COUNT(*) > 1
            """)).fetchall()

            if duplicates:
                logger.warning(f"发现 {len(duplicates)} 个频道存在多次绑定，保留最新记录...")
                before_count = session.exec(text("SELECT COUNT(*) FROM channel_bindings")).first()[0]
                session.exec(text("""
                    DELETE FROM channel_bindings
                    WHERE id NOT IN (
                        SELECT MAX(id)
                        FROM channel_bindings
                        GROUP BY channel_id
                    )
                """))
                session.commit()  # DML 也立即提交
                after_count = session.exec(text("SELECT COUNT(*) FROM channel_bindings")).first()[0]
                deleted_count = before_count - after_count
                logger.info(f"✅ 已删除 {deleted_count} 条重复记录")
            else:
                logger.info("✅ 未发现重复数据")

            # 3. 删除 group_id 字段
            logger.info("Step 3/3: 删除 group_id 字段...")
            session.exec(text("""
                ALTER TABLE channel_bindings
                DROP COLUMN IF EXISTS group_id;
            """))
            session.commit()  # DDL 需要立即提交
            logger.info("✅ group_id 字段已删除")

            # 验证
            logger.info("验证迁移结果...")
            inspector = inspect(engine)
            columns = inspector.get_columns('channel_bindings')
            column_names = [col['name'] for col in columns]

            if 'group_id' not in column_names:
                current_count = session.exec(text("SELECT COUNT(*) FROM channel_bindings")).first()[0]
                logger.info(f"✅ 验证通过，当前记录数: {current_count}")
            else:
                raise Exception("验证失败: group_id 字段仍然存在")

            logger.info("=" * 80)
            logger.success(f"🎉 迁移 #{self.version} 执行成功！")
            logger.info("=" * 80)

        except Exception as e:
            logger.error(f"❌ 迁移失败: {e}")
            session.rollback()
            logger.error("⚠️ 事务已回滚")
            logger.error("⚠️ 如需恢复数据，请使用您的备份！")
            raise

    def rollback(self, session: Session):
        """
        回滚迁移（需要手动提供备份）

        注意：此方法假设你已经有数据库备份
        回滚前请确保已经恢复备份到数据库
        """
        logger.warning("⚠️ 回滚功能需要手动操作：")
        logger.warning("1. 从备份恢复数据库")
        logger.warning("2. 或者手动执行以下 SQL：")
        logger.warning("   ALTER TABLE channel_bindings ADD COLUMN group_id BIGINT;")
        logger.warning("   ALTER TABLE channel_bindings ADD CONSTRAINT channel_bindings_group_id_fkey FOREIGN KEY (group_id) REFERENCES group_configs(id);")
        logger.warning("   CREATE INDEX ix_channel_bindings_group_id ON channel_bindings(group_id);")
        raise NotImplementedError("回滚需要手动操作，请联系 DBA")


class Migration002_AddMessageMetadata(Migration):
    """
    迁移002: 为 messages 表添加 extra_data 字段

    变更内容:
    - 添加 extra_data JSONB 字段（可空）
    - 用于存储扩展信息，如图片检测结果等
    """

    def __init__(self):
        super().__init__(
            version=2,
            description="Add extra_data JSONB field to messages table"
        )

    def check(self, session: Session) -> bool:
        """检查 messages 表是否缺少 extra_data 字段"""
        try:
            inspector = inspect(engine)

            # 检查表是否存在
            if 'messages' not in inspector.get_table_names():
                logger.info("messages 表不存在，跳过迁移")
                return False

            # 检查 extra_data 字段是否存在
            columns = inspector.get_columns('messages')
            column_names = [col['name'] for col in columns]

            if 'extra_data' not in column_names:
                logger.warning(f"检测到旧版本数据库结构: messages 表缺少 extra_data 字段")
                return True
            else:
                logger.info("messages 表已包含 extra_data 字段")
                return False

        except Exception as e:
            logger.error(f"检查迁移状态失败: {e}")
            return False

    def execute(self, session: Session):
        """执行迁移"""
        logger.info("=" * 80)
        logger.info(f"开始执行迁移 #{self.version}: {self.description}")
        logger.info("=" * 80)

        try:
            # 添加 extra_data 字段
            logger.info("Step 1/1: 添加 extra_data 字段...")
            session.exec(text("""
                ALTER TABLE messages
                ADD COLUMN IF NOT EXISTS extra_data JSONB;
            """))
            session.commit()
            logger.info("✅ extra_data 字段已添加")

            # 验证
            logger.info("验证迁移结果...")
            inspector = inspect(engine)
            columns = inspector.get_columns('messages')
            column_names = [col['name'] for col in columns]

            if 'extra_data' in column_names:
                logger.info("✅ 验证通过")
            else:
                raise Exception("验证失败: extra_data 字段不存在")

            logger.info("=" * 80)
            logger.success(f"🎉 迁移 #{self.version} 执行成功！")
            logger.info("=" * 80)

        except Exception as e:
            logger.error(f"❌ 迁移失败: {e}")
            session.rollback()
            logger.error("⚠️ 事务已回滚")
            raise

    def rollback(self, session: Session):
        """回滚迁移"""
        logger.info("回滚迁移002: 删除 extra_data 字段")
        session.exec(text("ALTER TABLE messages DROP COLUMN IF EXISTS extra_data;"))
        session.commit()
        logger.info("✅ 回滚完成")


class Migration003_AddUserProfileTables(Migration):
    """
    迁移003: 添加用户资料和频道爬取相关表

    变更内容:
    - 创建 user_profiles 表（用户详细资料）
    - 创建 user_channels 表（用户关联的频道）
    - 创建 channel_messages 表（频道消息）
    - 创建 crawl_tasks 表（爬虫任务队列）
    """

    def __init__(self):
        super().__init__(
            version=3,
            description="Add user_profiles, user_channels, channel_messages, and crawl_tasks tables"
        )

    def check(self, session: Session) -> bool:
        """检查表是否需要创建"""
        try:
            inspector = inspect(engine)
            tables = inspector.get_table_names()

            # 只要有一个表不存在就需要执行迁移
            required_tables = ['user_profiles', 'user_channels', 'channel_messages', 'crawl_tasks']
            missing_tables = [t for t in required_tables if t not in tables]

            if missing_tables:
                logger.warning(f"检测到缺失的表: {', '.join(missing_tables)}")
                return True
            else:
                logger.info("用户资料和频道爬取相关表已存在")
                return False

        except Exception as e:
            logger.error(f"检查迁移状态失败: {e}")
            return False

    def execute(self, session: Session):
        """执行迁移"""
        logger.info("=" * 80)
        logger.info(f"开始执行迁移 #{self.version}: {self.description}")
        logger.info("=" * 80)

        try:
            # 1. 创建 user_profiles 表
            logger.info("Step 1/4: 创建 user_profiles 表...")
            session.exec(text("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT UNIQUE NOT NULL,
                    username VARCHAR,
                    first_name VARCHAR,
                    last_name VARCHAR,
                    phone VARCHAR,
                    bio TEXT,
                    is_bot BOOLEAN DEFAULT FALSE,
                    is_verified BOOLEAN DEFAULT FALSE,
                    is_restricted BOOLEAN DEFAULT FALSE,
                    is_scam BOOLEAN DEFAULT FALSE,
                    is_fake BOOLEAN DEFAULT FALSE,
                    is_premium BOOLEAN DEFAULT FALSE,
                    has_personal_channel BOOLEAN DEFAULT FALSE,
                    personal_channel_id BIGINT,
                    personal_channel_username VARCHAR,
                    last_crawled_at TIMESTAMP,
                    crawl_error TEXT,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                );

                CREATE INDEX IF NOT EXISTS ix_user_profiles_user_id ON user_profiles(user_id);
                CREATE INDEX IF NOT EXISTS ix_user_profiles_username ON user_profiles(username);
            """))
            session.commit()
            logger.info("✅ user_profiles 表已创建")

            # 2. 创建 user_channels 表
            logger.info("Step 2/4: 创建 user_channels 表...")
            session.exec(text("""
                CREATE TABLE IF NOT EXISTS user_channels (
                    id SERIAL PRIMARY KEY,
                    user_profile_id INTEGER NOT NULL REFERENCES user_profiles(id),
                    channel_id BIGINT NOT NULL,
                    channel_username VARCHAR,
                    channel_title VARCHAR,
                    channel_about TEXT,
                    subscribers_count INTEGER DEFAULT 0,
                    is_personal_channel BOOLEAN DEFAULT FALSE,
                    is_crawled BOOLEAN DEFAULT FALSE,
                    last_crawled_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                );

                CREATE INDEX IF NOT EXISTS ix_user_channels_user_profile_id ON user_channels(user_profile_id);
                CREATE INDEX IF NOT EXISTS ix_user_channels_channel_id ON user_channels(channel_id);
                CREATE INDEX IF NOT EXISTS ix_user_channels_channel_username ON user_channels(channel_username);
            """))
            session.commit()
            logger.info("✅ user_channels 表已创建")

            # 3. 创建 channel_messages 表
            logger.info("Step 3/4: 创建 channel_messages 表...")
            session.exec(text("""
                CREATE TABLE IF NOT EXISTS channel_messages (
                    id SERIAL PRIMARY KEY,
                    channel_id INTEGER NOT NULL REFERENCES user_channels(id),
                    message_id BIGINT NOT NULL,
                    text TEXT,
                    has_media BOOLEAN DEFAULT FALSE,
                    media_type VARCHAR,
                    is_pinned BOOLEAN DEFAULT FALSE,
                    views INTEGER DEFAULT 0,
                    forwards INTEGER DEFAULT 0,
                    posted_at TIMESTAMP NOT NULL,
                    edited_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL
                );

                CREATE INDEX IF NOT EXISTS ix_channel_messages_channel_id ON channel_messages(channel_id);
                CREATE INDEX IF NOT EXISTS ix_channel_messages_message_id ON channel_messages(message_id);
            """))
            session.commit()
            logger.info("✅ channel_messages 表已创建")

            # 4. 创建 crawl_tasks 表
            logger.info("Step 4/4: 创建 crawl_tasks 表...")
            session.exec(text("""
                CREATE TABLE IF NOT EXISTS crawl_tasks (
                    id SERIAL PRIMARY KEY,
                    group_id INTEGER NOT NULL REFERENCES group_configs(id),
                    crawl_channels BOOLEAN DEFAULT FALSE,
                    channel_depth INTEGER DEFAULT 10,
                    status VARCHAR NOT NULL DEFAULT 'pending',
                    total_users INTEGER DEFAULT 0,
                    processed_users INTEGER DEFAULT 0,
                    failed_users INTEGER DEFAULT 0,
                    current_user_id BIGINT,
                    progress_message TEXT,
                    error_message TEXT,
                    created_by_user_id BIGINT NOT NULL,
                    created_by_username VARCHAR,
                    created_at TIMESTAMP NOT NULL,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL
                );

                CREATE INDEX IF NOT EXISTS ix_crawl_tasks_group_id ON crawl_tasks(group_id);
                CREATE INDEX IF NOT EXISTS ix_crawl_tasks_status ON crawl_tasks(status);
            """))
            session.commit()
            logger.info("✅ crawl_tasks 表已创建")

            # 验证
            logger.info("验证迁移结果...")
            inspector = inspect(engine)
            tables = inspector.get_table_names()

            required_tables = ['user_profiles', 'user_channels', 'channel_messages', 'crawl_tasks']
            if all(t in tables for t in required_tables):
                logger.info("✅ 验证通过，所有表已创建")
            else:
                raise Exception("验证失败: 部分表未创建成功")

            logger.info("=" * 80)
            logger.success(f"🎉 迁移 #{self.version} 执行成功！")
            logger.info("=" * 80)

        except Exception as e:
            logger.error(f"❌ 迁移失败: {e}")
            session.rollback()
            logger.error("⚠️ 事务已回滚")
            raise

    def rollback(self, session: Session):
        """回滚迁移"""
        logger.info("回滚迁移003: 删除用户资料和频道爬取相关表")
        session.exec(text("""
            DROP TABLE IF EXISTS channel_messages CASCADE;
            DROP TABLE IF EXISTS user_channels CASCADE;
            DROP TABLE IF EXISTS crawl_tasks CASCADE;
            DROP TABLE IF EXISTS user_profiles CASCADE;
        """))
        session.commit()
        logger.info("✅ 回滚完成")


class Migration004_AddScammerDetectionRecords(Migration):
    """
    迁移004: 添加号商检测记录表

    变更内容:
    - 创建 scammer_detection_records 表
    - 用于存储号商检测结果和缓存
    """

    def __init__(self):
        super().__init__(
            version=4,
            description="Add scammer_detection_records table"
        )

    def check(self, session: Session) -> bool:
        """检查 scammer_detection_records 表是否存在"""
        try:
            inspector = inspect(engine)
            tables = inspector.get_table_names()

            if 'scammer_detection_records' not in tables:
                logger.warning("检测到需要添加 scammer_detection_records 表")
                return True
            else:
                logger.info("scammer_detection_records 表已存在")
                return False

        except Exception as e:
            logger.error(f"检查迁移状态失败: {e}")
            return False

    def execute(self, session: Session):
        """执行迁移"""
        logger.info("=" * 80)
        logger.info(f"开始执行迁移 #{self.version}: {self.description}")
        logger.info("=" * 80)

        try:
            # 创建 scammer_detection_records 表
            logger.info("创建 scammer_detection_records 表...")
            session.exec(text("""
                CREATE TABLE IF NOT EXISTS scammer_detection_records (
                    id SERIAL PRIMARY KEY,
                    group_id BIGINT NOT NULL,
                    user_id BIGINT,
                    detection_type VARCHAR NOT NULL,
                    is_scammer BOOLEAN NOT NULL,
                    confidence FLOAT NOT NULL,
                    evidence TEXT NOT NULL,
                    user_snapshot JSON NOT NULL,
                    crawl_task_id INTEGER,
                    detected_by_user_id BIGINT NOT NULL,
                    detected_at TIMESTAMP NOT NULL,
                    is_kicked BOOLEAN NOT NULL DEFAULT FALSE,
                    kicked_at TIMESTAMP,
                    kicked_by_user_id BIGINT,
                    expires_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                );

                CREATE INDEX IF NOT EXISTS ix_scammer_detection_records_group_id
                    ON scammer_detection_records(group_id);
                CREATE INDEX IF NOT EXISTS ix_scammer_detection_records_user_id
                    ON scammer_detection_records(user_id);
                CREATE INDEX IF NOT EXISTS ix_scammer_detection_records_detection_type
                    ON scammer_detection_records(detection_type);
                CREATE INDEX IF NOT EXISTS ix_scammer_detection_records_detected_at
                    ON scammer_detection_records(detected_at);
                CREATE INDEX IF NOT EXISTS ix_scammer_detection_records_expires_at
                    ON scammer_detection_records(expires_at);
                CREATE INDEX IF NOT EXISTS ix_group_expires
                    ON scammer_detection_records(group_id, expires_at);
                CREATE INDEX IF NOT EXISTS ix_group_user_detected
                    ON scammer_detection_records(group_id, user_id, detected_at);
            """))
            session.commit()
            logger.info("✅ scammer_detection_records 表已创建")

            # 验证
            logger.info("验证迁移结果...")
            inspector = inspect(engine)
            tables = inspector.get_table_names()

            if 'scammer_detection_records' in tables:
                logger.info("✅ 验证通过，表已创建")
            else:
                raise Exception("验证失败: scammer_detection_records 表未创建成功")

            logger.info("=" * 80)
            logger.success(f"🎉 迁移 #{self.version} 执行成功！")
            logger.info("=" * 80)

        except Exception as e:
            logger.error(f"❌ 迁移失败: {e}")
            session.rollback()
            logger.error("⚠️ 事务已回滚")
            raise

    def rollback(self, session: Session):
        """回滚迁移"""
        logger.info("回滚迁移004: 删除 scammer_detection_records 表")
        session.exec(text("""
            DROP TABLE IF EXISTS scammer_detection_records CASCADE;
        """))
        session.commit()
        logger.info("✅ 回滚完成")


class Migration005_AddCrawlTaskStatusFields(Migration):
    """
    迁移005: 添加爬虫任务状态消息字段

    变更内容:
    - 在 crawl_tasks 表中添加 status_chat_id 和 status_message_id 字段
    - 用于在爬取过程中更新进度和发送完成消息
    """

    def __init__(self):
        super().__init__(
            version=5,
            description="Add status_chat_id and status_message_id to crawl_tasks"
        )

    def check(self, session: Session) -> bool:
        """检查 crawl_tasks 表是否缺少状态消息字段"""
        try:
            inspector = inspect(engine)

            # 检查表是否存在
            if 'crawl_tasks' not in inspector.get_table_names():
                logger.info("crawl_tasks 表不存在，跳过迁移")
                return False

            # 检查字段是否存在
            columns = inspector.get_columns('crawl_tasks')
            column_names = [col['name'] for col in columns]

            if 'status_chat_id' not in column_names or 'status_message_id' not in column_names:
                logger.warning("检测到 crawl_tasks 表缺少状态消息字段")
                return True
            else:
                logger.info("crawl_tasks 表已包含状态消息字段")
                return False

        except Exception as e:
            logger.error(f"检查迁移状态失败: {e}")
            return False

    def execute(self, session: Session):
        """执行迁移"""
        logger.info("=" * 80)
        logger.info(f"开始执行迁移 #{self.version}: {self.description}")
        logger.info("=" * 80)

        try:
            # 检查字段是否已存在
            inspector = inspect(engine)
            columns = inspector.get_columns('crawl_tasks')
            column_names = [col['name'] for col in columns]

            # 添加 status_chat_id 字段
            if 'status_chat_id' not in column_names:
                logger.info("添加 status_chat_id 字段...")
                session.exec(text("""
                    ALTER TABLE crawl_tasks
                    ADD COLUMN status_chat_id BIGINT;
                """))
                session.commit()
                logger.info("✅ status_chat_id 字段已添加")
            else:
                logger.info("status_chat_id 字段已存在，跳过")

            # 添加 status_message_id 字段
            if 'status_message_id' not in column_names:
                logger.info("添加 status_message_id 字段...")
                session.exec(text("""
                    ALTER TABLE crawl_tasks
                    ADD COLUMN status_message_id BIGINT;
                """))
                session.commit()
                logger.info("✅ status_message_id 字段已添加")
            else:
                logger.info("status_message_id 字段已存在，跳过")

            # 验证
            logger.info("验证迁移结果...")
            inspector = inspect(engine)
            columns = inspector.get_columns('crawl_tasks')
            column_names = [col['name'] for col in columns]

            if 'status_chat_id' in column_names and 'status_message_id' in column_names:
                logger.info("✅ 验证通过，字段已添加")
            else:
                raise Exception("验证失败: 字段未添加成功")

            logger.info("=" * 80)
            logger.success(f"🎉 迁移 #{self.version} 执行成功！")
            logger.info("=" * 80)

        except Exception as e:
            logger.error(f"❌ 迁移失败: {e}")
            session.rollback()
            logger.error("⚠️ 事务已回滚")
            raise

    def rollback(self, session: Session):
        """回滚迁移"""
        logger.info("回滚迁移005: 删除 crawl_tasks 的状态消息字段")
        session.exec(text("""
            ALTER TABLE crawl_tasks
            DROP COLUMN IF EXISTS status_chat_id,
            DROP COLUMN IF EXISTS status_message_id;
        """))
        session.commit()
        logger.info("✅ 回滚完成")



class Migration006_FixDMRelayBigInt(Migration):
    """
    迁移006: 修复 DM 转达表的整型溢出问题
    
    变更内容:
    - 将 dm_relays 表的 group_id, from_user_id, to_user_id 从 INTEGER 转换为 BIGINT
    - 将 dm_read_receipts 表的 read_by 从 INTEGER 转换为 BIGINT
    - 用于支持更大的 Telegram ID 值
    """
    
    def __init__(self):
        super().__init__(
            version=6,
            description="Fix DM relay tables to use BIGINT for Telegram IDs"
        )
    
    def check(self, session: Session) -> bool:
        """检查 dm_relays 表的 ID 字段是否需要转换为 BIGINT"""
        try:
            inspector = inspect(engine)
            
            # 检查表是否存在
            if 'dm_relays' not in inspector.get_table_names():
                logger.info("dm_relays 表不存在，跳过迁移")
                return False
            
            # 检查字段类型
            columns = inspector.get_columns('dm_relays')
            
            # 检查是否有字段需要转换（INTEGER -> BIGINT）
            needs_migration = False
            for col in columns:
                if col['name'] in ['group_id', 'from_user_id', 'to_user_id']:
                    # 检查类型名称，可能是 'INTEGER' 或 'INT'
                    col_type = str(col['type']).upper()
                    if 'BIGINT' not in col_type and ('INTEGER' in col_type or col_type == 'INT'):
                        logger.warning(f"检测到 {col['name']} 字段类型为 {col_type}，需要转换为 BIGINT")
                        needs_migration = True
            
            if needs_migration:
                logger.warning("检测到需要修复 DM 转达表的整型溢出问题")
                return True
            else:
                logger.info("dm_relays 表已使用 BIGINT 类型")
                return False
                
        except Exception as e:
            logger.error(f"检查迁移状态失败: {e}")
            return False
    
    def execute(self, session: Session):
        """执行迁移"""
        logger.info("=" * 80)
        logger.info(f"开始执行迁移 #{self.version}: {self.description}")
        logger.info("=" * 80)
        
        try:
            # 1. 修复 dm_relays 表
            logger.info("Step 1/2: 转换 dm_relays 表的 ID 字段为 BIGINT...")
            session.exec(text("""
                ALTER TABLE dm_relays 
                    ALTER COLUMN group_id TYPE BIGINT,
                    ALTER COLUMN from_user_id TYPE BIGINT,
                    ALTER COLUMN to_user_id TYPE BIGINT;
            """))
            session.commit()
            logger.info("✅ dm_relays 表字段已转换")
            
            # 2. 修复 dm_read_receipts 表（如果存在）
            inspector = inspect(engine)
            if 'dm_read_receipts' in inspector.get_table_names():
                logger.info("Step 2/2: 转换 dm_read_receipts 表的 ID 字段为 BIGINT...")
                session.exec(text("""
                    ALTER TABLE dm_read_receipts 
                        ALTER COLUMN read_by TYPE BIGINT;
                """))
                session.commit()
                logger.info("✅ dm_read_receipts 表字段已转换")
            else:
                logger.info("Step 2/2: dm_read_receipts 表不存在，跳过")
            
            # 验证
            logger.info("验证迁移结果...")
            inspector = inspect(engine)
            columns = inspector.get_columns('dm_relays')
            
            for col in columns:
                if col['name'] in ['group_id', 'from_user_id', 'to_user_id']:
                    col_type = str(col['type']).upper()
                    if 'BIGINT' not in col_type:
                        raise Exception(f"验证失败: {col['name']} 字段类型仍为 {col_type}")
            
            logger.info("✅ 验证通过，所有字段已转换为 BIGINT")
            logger.info("=" * 80)
            logger.success(f"🎉 迁移 #{self.version} 执行成功！")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"❌ 迁移失败: {e}")
            session.rollback()
            logger.error("⚠️ 事务已回滚")
            raise
    
    def rollback(self, session: Session):
        """回滚迁移（不建议，因为可能导致数据溢出）"""
        logger.warning("⚠️ 回滚此迁移可能导致整型溢出问题重新出现")
        logger.warning("如果确实需要回滚，请手动执行以下 SQL：")
        logger.warning("   ALTER TABLE dm_relays ALTER COLUMN group_id TYPE INTEGER;")
        logger.warning("   ALTER TABLE dm_relays ALTER COLUMN from_user_id TYPE INTEGER;")
        logger.warning("   ALTER TABLE dm_relays ALTER COLUMN to_user_id TYPE INTEGER;")
        logger.warning("   ALTER TABLE dm_read_receipts ALTER COLUMN read_by TYPE INTEGER;")
        raise NotImplementedError("不建议回滚此迁移")


class Migration007_AddBinManagementTables(Migration):
    """
    迁移007: 添加BIN管理系统相关表

    变更内容:
    - 创建 bin_configs 表（BIN监听配置）
    - 创建 bin_cards 表（BIN卡信息）
    - 创建 bin_sites 表（BIN对应的网站信息）
    """

    def __init__(self):
        super().__init__(
            version=7,
            description="Add BIN management system tables (bin_configs, bin_cards, bin_sites)"
        )

    def check(self, session: Session) -> bool:
        """检查BIN管理表是否需要创建"""
        try:
            inspector = inspect(engine)
            tables = inspector.get_table_names()

            # 只要有一个表不存在就需要执行迁移
            required_tables = ['bin_configs', 'bin_cards', 'bin_sites']
            missing_tables = [t for t in required_tables if t not in tables]

            if missing_tables:
                logger.warning(f"检测到缺失的BIN管理表: {', '.join(missing_tables)}")
                return True
            else:
                logger.info("BIN管理相关表已存在")
                return False

        except Exception as e:
            logger.error(f"检查迁移状态失败: {e}")
            return False

    def execute(self, session: Session):
        """执行迁移"""
        logger.info("=" * 80)
        logger.info(f"开始执行迁移 #{self.version}: {self.description}")
        logger.info("=" * 80)

        try:
            # 1. 创建 bin_configs 表
            logger.info("Step 1/3: 创建 bin_configs 表...")
            session.exec(text("""
                CREATE TABLE IF NOT EXISTS bin_configs (
                    id SERIAL PRIMARY KEY,
                    group_id INTEGER NOT NULL REFERENCES group_configs(id),
                    topic_id BIGINT NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    ai_prompt TEXT,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                );

                CREATE INDEX IF NOT EXISTS ix_bin_configs_group_id ON bin_configs(group_id);
                CREATE INDEX IF NOT EXISTS ix_bin_configs_topic_id ON bin_configs(topic_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_bin_config_group_topic
                    ON bin_configs(group_id, topic_id);
            """))
            session.commit()
            logger.info("✅ bin_configs 表已创建")

            # 2. 创建 bin_cards 表
            logger.info("Step 2/3: 创建 bin_cards 表...")
            session.exec(text("""
                CREATE TABLE IF NOT EXISTS bin_cards (
                    id SERIAL PRIMARY KEY,
                    group_id INTEGER NOT NULL REFERENCES group_configs(id),
                    topic_id BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    sender_user_id BIGINT,
                    sender_username VARCHAR(100),
                    sender_chat_id BIGINT,
                    rule VARCHAR(50) NOT NULL,
                    rule_prefix VARCHAR(8) NOT NULL,
                    ip_requirement VARCHAR(100),
                    credits VARCHAR(100),
                    notes TEXT,
                    original_text TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL
                );

                CREATE INDEX IF NOT EXISTS ix_bin_cards_group_id ON bin_cards(group_id);
                CREATE INDEX IF NOT EXISTS ix_bin_cards_topic_id ON bin_cards(topic_id);
                CREATE INDEX IF NOT EXISTS ix_bin_cards_sender_user_id ON bin_cards(sender_user_id);
                CREATE INDEX IF NOT EXISTS ix_bin_cards_sender_username ON bin_cards(sender_username);
                CREATE INDEX IF NOT EXISTS ix_bin_cards_rule ON bin_cards(rule);
                CREATE INDEX IF NOT EXISTS ix_bin_cards_rule_prefix ON bin_cards(rule_prefix);
                CREATE INDEX IF NOT EXISTS idx_bin_card_group_rule ON bin_cards(group_id, rule);
                CREATE INDEX IF NOT EXISTS idx_bin_card_group_prefix ON bin_cards(group_id, rule_prefix);
            """))
            session.commit()
            logger.info("✅ bin_cards 表已创建")

            # 3. 创建 bin_sites 表
            logger.info("Step 3/3: 创建 bin_sites 表...")
            session.exec(text("""
                CREATE TABLE IF NOT EXISTS bin_sites (
                    id SERIAL PRIMARY KEY,
                    bin_card_id INTEGER NOT NULL REFERENCES bin_cards(id) ON DELETE CASCADE,
                    site_name VARCHAR(100) NOT NULL,
                    site_domain VARCHAR(200) NOT NULL
                );

                CREATE INDEX IF NOT EXISTS ix_bin_sites_bin_card_id ON bin_sites(bin_card_id);
                CREATE INDEX IF NOT EXISTS ix_bin_sites_site_name ON bin_sites(site_name);
                CREATE INDEX IF NOT EXISTS ix_bin_sites_site_domain ON bin_sites(site_domain);
                CREATE INDEX IF NOT EXISTS idx_bin_site_card_domain ON bin_sites(bin_card_id, site_domain);
            """))
            session.commit()
            logger.info("✅ bin_sites 表已创建")

            # 验证
            logger.info("验证迁移结果...")
            inspector = inspect(engine)
            tables = inspector.get_table_names()

            required_tables = ['bin_configs', 'bin_cards', 'bin_sites']
            if all(t in tables for t in required_tables):
                logger.info("✅ 验证通过，所有BIN管理表已创建")
            else:
                raise Exception("验证失败: 部分BIN管理表未创建成功")

            logger.info("=" * 80)
            logger.success(f"🎉 迁移 #{self.version} 执行成功！")
            logger.info("=" * 80)

        except Exception as e:
            logger.error(f"❌ 迁移失败: {e}")
            session.rollback()
            logger.error("⚠️ 事务已回滚")
            raise

    def rollback(self, session: Session):
        """回滚迁移"""
        logger.info("回滚迁移007: 删除BIN管理相关表")
        session.exec(text("""
            DROP TABLE IF EXISTS bin_sites CASCADE;
            DROP TABLE IF EXISTS bin_cards CASCADE;
            DROP TABLE IF EXISTS bin_configs CASCADE;
        """))
        session.commit()
        logger.info("✅ 回滚完成")


class Migration008_AddBinInfoFields(Migration):
    """
    迁移008: 为 bin_cards 表添加 BIN 信息字段

    变更内容:
    - 添加 bin_scheme (卡组织)
    - 添加 bin_type (卡类型)
    - 添加 bin_brand (卡品牌)
    - 添加 bin_country (发卡国家)
    - 添加 bin_country_emoji (国家旗帜emoji)
    - 添加 bin_bank (发卡银行)
    """

    def __init__(self):
        super().__init__(
            version=8,
            description="Add BIN information fields to bin_cards table"
        )

    def check(self, session: Session) -> bool:
        """检查 bin_cards 表是否缺少 BIN 信息字段"""
        try:
            inspector = inspect(engine)

            # 检查表是否存在
            if 'bin_cards' not in inspector.get_table_names():
                logger.info("bin_cards 表不存在，跳过迁移")
                return False

            # 检查字段是否存在
            columns = inspector.get_columns('bin_cards')
            column_names = [col['name'] for col in columns]

            required_fields = ['bin_scheme', 'bin_type', 'bin_brand', 'bin_country', 'bin_country_emoji', 'bin_bank']
            missing_fields = [f for f in required_fields if f not in column_names]

            if missing_fields:
                logger.warning(f"检测到 bin_cards 表缺少 BIN 信息字段: {', '.join(missing_fields)}")
                return True
            else:
                logger.info("bin_cards 表已包含所有 BIN 信息字段")
                return False

        except Exception as e:
            logger.error(f"检查迁移状态失败: {e}")
            return False

    def execute(self, session: Session):
        """执行迁移"""
        logger.info("=" * 80)
        logger.info(f"开始执行迁移 #{self.version}: {self.description}")
        logger.info("=" * 80)

        try:
            # 添加 BIN 信息字段
            logger.info("添加 BIN 信息字段...")
            session.exec(text("""
                ALTER TABLE bin_cards
                ADD COLUMN IF NOT EXISTS bin_scheme VARCHAR(50),
                ADD COLUMN IF NOT EXISTS bin_type VARCHAR(50),
                ADD COLUMN IF NOT EXISTS bin_brand VARCHAR(100),
                ADD COLUMN IF NOT EXISTS bin_country VARCHAR(100),
                ADD COLUMN IF NOT EXISTS bin_country_emoji VARCHAR(10),
                ADD COLUMN IF NOT EXISTS bin_bank VARCHAR(200);
            """))
            session.commit()
            logger.info("✅ BIN 信息字段已添加")

            # 验证
            logger.info("验证迁移结果...")
            inspector = inspect(engine)
            columns = inspector.get_columns('bin_cards')
            column_names = [col['name'] for col in columns]

            required_fields = ['bin_scheme', 'bin_type', 'bin_brand', 'bin_country', 'bin_country_emoji', 'bin_bank']
            if all(f in column_names for f in required_fields):
                logger.info("✅ 验证通过，所有 BIN 信息字段已添加")
            else:
                raise Exception("验证失败: 部分 BIN 信息字段未添加成功")

            logger.info("=" * 80)
            logger.success(f"🎉 迁移 #{self.version} 执行成功！")
            logger.info("=" * 80)

        except Exception as e:
            logger.error(f"❌ 迁移失败: {e}")
            session.rollback()
            logger.error("⚠️ 事务已回滚")
            raise

    def rollback(self, session: Session):
        """回滚迁移"""
        logger.info("回滚迁移008: 删除 bin_cards 表的 BIN 信息字段")
        session.exec(text("""
            ALTER TABLE bin_cards
            DROP COLUMN IF EXISTS bin_scheme,
            DROP COLUMN IF EXISTS bin_type,
            DROP COLUMN IF EXISTS bin_brand,
            DROP COLUMN IF EXISTS bin_country,
            DROP COLUMN IF EXISTS bin_country_emoji,
            DROP COLUMN IF EXISTS bin_bank;
        """))
        session.commit()
        logger.info("✅ 回滚完成")


# 注册所有迁移
ALL_MIGRATIONS = [
    Migration001_RemoveChannelBindingGroupId(),
    Migration002_AddMessageMetadata(),
    Migration003_AddUserProfileTables(),
    Migration004_AddScammerDetectionRecords(),
    Migration005_AddCrawlTaskStatusFields(),
    Migration006_FixDMRelayBigInt(),
    Migration007_AddBinManagementTables(),
    Migration008_AddBinInfoFields(),
]


def run_migrations():
    """
    自动检测并执行所有待执行的迁移

    返回: (成功数, 跳过数, 失败数)
    """
    logger.info("🔍 开始检查数据库迁移...")

    success_count = 0
    skipped_count = 0
    failed_count = 0

    with Session(engine) as session:
        for migration in ALL_MIGRATIONS:
            try:
                # 检查是否需要执行
                if not migration.check(session):
                    logger.info(f"⏭️  迁移 #{migration.version} 已执行或不需要执行，跳过")
                    skipped_count += 1
                    continue

                # 执行迁移
                migration.execute(session)
                success_count += 1

            except Exception as e:
                logger.error(f"❌ 迁移 #{migration.version} 执行失败: {e}")
                failed_count += 1
                # 继续执行下一个迁移（可选：改为 break 中断）
                continue

    # 输出总结
    logger.info("=" * 80)
    logger.info(f"📊 迁移执行完成: 成功 {success_count}, 跳过 {skipped_count}, 失败 {failed_count}")
    logger.info("=" * 80)

    if failed_count > 0:
        logger.error("⚠️ 部分迁移失败，请检查日志并手动修复")
        raise Exception(f"{failed_count} 个迁移失败")

    return success_count, skipped_count, failed_count


def check_migrations() -> bool:
    """
    检查是否有待执行的迁移

    返回: True 表示有待执行的迁移
    """
    with Session(engine) as session:
        for migration in ALL_MIGRATIONS:
            try:
                if migration.check(session):
                    return True
            except Exception as e:
                logger.error(f"检查迁移 #{migration.version} 时出错: {e}")

    return False
