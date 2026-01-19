"""
User Bot 登录脚本

用于登录 Telegram User Bot，生成 session 文件
只需要运行一次，之后 Bot 会自动使用已登录的 session

使用方法：
1. 在 .env 文件中配置 USERBOT_API_ID 和 USERBOT_API_HASH
2. 运行此脚本: python userbot_login.py
3. 输入手机号码并完成验证
4. 在 .env 中设置 USERBOT_ENABLED=true 启用 User Bot 功能
"""

import asyncio
from pathlib import Path
from loguru import logger
from telethon import TelegramClient
from app.config.settings import settings


async def login():
    """执行 User Bot 登录"""
    logger.info("=" * 60)
    logger.info("Telegram User Bot 登录工具")
    logger.info("=" * 60)

    # 检查配置
    if not settings.userbot_api_id or not settings.userbot_api_hash:
        logger.error("❌ 请先在 .env 文件中配置 USERBOT_API_ID 和 USERBOT_API_HASH")
        logger.info("提示: 从 https://my.telegram.org/apps 获取")
        return

    logger.info(f"API ID: {settings.userbot_api_id}")
    logger.info(f"Session 名称: {settings.userbot_session_name}")

    # 确保 sessions 目录存在
    sessions_dir = Path("sessions")
    sessions_dir.mkdir(exist_ok=True)

    # 检查 session 文件是否已存在
    session_file = Path(f"{settings.userbot_session_path}.session")
    if session_file.exists():
        logger.warning(f"⚠️  Session 文件已存在: {session_file}")
        choice = input("是否要重新登录？这会覆盖现有 session (y/n): ").strip().lower()
        if choice != 'y':
            logger.info("已取消操作")
            return
        session_file.unlink()
        logger.info("已删除旧的 session 文件")

    print("\n请输入手机号码（国际格式，如 +8613812345678）：")
    phone = input("手机号码: ").strip()

    if not phone:
        logger.error("❌ 手机号码不能为空")
        return

    logger.info("\n正在连接到 Telegram...")
    client = TelegramClient(
        settings.userbot_session_path,
        settings.userbot_api_id,
        settings.userbot_api_hash
    )

    try:
        await client.start(phone=phone)
        logger.info("✅ 登录成功！")

        # 获取当前用户信息
        me = await client.get_me()
        logger.info(f"当前账号: {me.first_name} (@{me.username or '无用户名'})")
        logger.info(f"用户ID: {me.id}")

        # 检查配置
        if not settings.userbot_enabled:
            logger.warning("\n⚠️  User Bot 功能未启用")
            logger.info("请在 .env 文件中设置 USERBOT_ENABLED=true 以启用功能")

        logger.info("\n✅ Session 文件已保存!")
        logger.info(f"   文件位置: {session_file.absolute()}")
        logger.info("\n现在可以在 Bot 中使用 User Bot 功能了")
        logger.info("例如: /kobe_import_members 命令来导入群组成员")

    except Exception as e:
        logger.error(f"❌ 登录失败: {e}")
        import traceback
        logger.error(traceback.format_exc())

    finally:
        await client.disconnect()
        logger.info("\n已断开连接")


def main():
    """主函数"""
    try:
        asyncio.run(login())
    except KeyboardInterrupt:
        logger.info("\n\n已取消操作")
    except Exception as e:
        logger.error(f"发生错误: {e}")


if __name__ == "__main__":
    main()
