#!/usr/bin/env python
"""
手动执行数据库迁移脚本

用法:
    python run_migration.py            # 执行所有待执行的迁移
    python run_migration.py --check    # 仅检查是否有待执行的迁移
"""
import sys
from loguru import logger
from app.database.migrations import run_migrations, check_migrations


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--check':
        # 仅检查
        if check_migrations():
            logger.warning("⚠️ 存在待执行的迁移")
            sys.exit(1)
        else:
            logger.success("✅ 所有迁移已完成")
            sys.exit(0)
    else:
        # 执行迁移
        try:
            success, skipped, failed = run_migrations()
            if failed > 0:
                sys.exit(1)
            else:
                logger.success("✅ 迁移执行完成")
                sys.exit(0)
        except Exception as e:
            logger.error(f"迁移失败: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
