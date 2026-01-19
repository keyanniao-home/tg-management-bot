"""
使用 Telethon User Bot 拉取群组成员并导入数据库

功能：
1. 使用用户账号（非Bot）连接 Telegram
2. 获取指定群组的所有成员
3. 导入到数据库的 group_members 表
4. 支持增量更新（已存在的成员会更新信息）
5. 配置缓存功能：首次输入后保存到文件，下次自动读取

使用方法：
1. 安装依赖: uv pip install telethon
2. 运行脚本: python import_members.py
3. 首次运行按提示输入 API_ID、API_HASH、手机号码
4. 配置会保存到 .importer_config.json，下次自动读取
5. 如需重新配置，删除配置文件即可
"""

import asyncio
import json
from datetime import datetime, UTC
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
from sqlmodel import Session, select
from app.database.connection import engine
from app.models import GroupConfig, GroupMember
from loguru import logger


# ============ 配置区域 ============
# Session 文件名（保存登录状态）
SESSION_NAME = 'member_importer'

# 配置文件路径
CONFIG_FILE = Path('.importer_config.json')

# 批量查询参数
BATCH_SIZE = 200  # 每次获取的成员数量
# ==================================


def load_config() -> dict:
    """从配置文件加载配置"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.info(f"✅ 已从 {CONFIG_FILE} 加载配置")
                return config
        except Exception as e:
            logger.warning(f"⚠️ 读取配置文件失败: {e}")
    return {}


def save_config(config: dict):
    """保存配置到文件"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info(f"✅ 配置已保存到 {CONFIG_FILE}")
    except Exception as e:
        logger.error(f"❌ 保存配置文件失败: {e}")


def get_input_with_default(prompt: str, default: str = None) -> str:
    """获取用户输入，如果有默认值则显示"""
    if default:
        user_input = input(f"{prompt} (默认: {default}): ").strip()
        return user_input if user_input else default
    else:
        return input(f"{prompt}: ").strip()


def convert_to_bot_api_id(telethon_id: int) -> int:
    """
    将 Telethon (MTProto) 格式的 ID 转换为 Bot API 格式

    Telethon: 3588609693
    Bot API: -1003588609693

    转换规则：
    - 对于超级群组/频道，Bot API ID = -100 + Telethon ID (作为字符串拼接)
    """
    # 如果已经是负数，说明已经是 Bot API 格式，直接返回
    if telethon_id < 0:
        return telethon_id

    # 对于正数的超级群组ID，转换为 Bot API 格式
    # Bot API 格式: -100 前缀 + Telethon ID
    return int(f"-100{telethon_id}")


async def get_group_config(group_id: int) -> GroupConfig:
    """获取或创建群组配置"""
    with Session(engine) as session:
        statement = select(GroupConfig).where(GroupConfig.group_id == group_id)
        group = session.exec(statement).first()

        if not group:
            logger.warning(f"群组 {group_id} 未在数据库中初始化，正在创建...")
            group = GroupConfig(
                group_id=group_id,
                group_name="Imported Group",
                is_initialized=False
            )
            session.add(group)
            session.commit()
            session.refresh(group)
            logger.info(f"已创建群组记录，数据库ID: {group.id}")

        return group


def import_member_sync(session: Session, group_db_id: int, participant, index: int, total: int) -> str:
    """
    导入单个成员并返回状态信息

    Returns:
        str: 状态标识 - "added", "updated", "skipped"
    """
    user = participant

    # 跳过已删除的账号
    if user.deleted:
        print(f"[{index}/{total}] ⏭️  跳过已删除账号 (ID: {user.id})")
        return "skipped"

    # 跳过 bot 账号
    if user.bot:
        print(f"[{index}/{total}] 🤖 跳过机器人账号 (ID: {user.id})")
        return "skipped"

    user_id = user.id
    username = user.username or ""

    # 构建全名
    full_name_parts = []
    if user.first_name:
        full_name_parts.append(user.first_name)
    if user.last_name:
        full_name_parts.append(user.last_name)
    full_name = ' '.join(full_name_parts) if full_name_parts else f"User{user_id}"

    # 显示用户信息
    username_display = f"@{username}" if username else "(无用户名)"

    # 查询是否已存在
    statement = select(GroupMember).where(
        GroupMember.group_id == group_db_id,
        GroupMember.user_id == user_id
    )
    member = session.exec(statement).first()

    if member:
        # 更新现有成员
        member.username = username
        member.full_name = full_name
        member.is_active = True
        member.left_at = None
        member.updated_at = datetime.now(UTC)
        session.add(member)
        print(f"[{index}/{total}] 🔄 更新: {full_name} {username_display} (ID: {user_id})")
        return "updated"
    else:
        # 新增成员
        new_member = GroupMember(
            group_id=group_db_id,
            user_id=user_id,
            username=username,
            full_name=full_name,
            is_active=True,
            joined_at=datetime.now(UTC)
        )
        session.add(new_member)
        print(f"[{index}/{total}] ✅ 新增: {full_name} {username_display} (ID: {user_id})")
        return "added"


async def fetch_all_members(client: TelegramClient, group_entity):
    """
    获取群组的所有成员
    """
    all_participants = []
    offset = 0

    logger.info("开始拉取成员...")

    while True:
        try:
            participants = await client(GetParticipantsRequest(
                channel=group_entity,
                filter=ChannelParticipantsSearch(''),
                offset=offset,
                limit=BATCH_SIZE,
                hash=0
            ))

            if not participants.users:
                break

            all_participants.extend(participants.users)
            offset += len(participants.users)

            logger.info(f"已拉取 {len(all_participants)} 个成员...")

            if len(participants.users) < BATCH_SIZE:
                break

            await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"拉取成员时出错: {e}")
            break

    logger.info(f"✅ 总共拉取到 {len(all_participants)} 个成员")
    return all_participants


async def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("Telegram 群组成员导入工具")
    logger.info("=" * 60)

    # 加载现有配置
    config = load_config()

    print("\n请输入以下信息（直接回车使用已保存的配置）：")
    print("（提示：从 https://my.telegram.org/apps 获取 API_ID 和 API_HASH）\n")

    # 获取 API_ID（支持默认值）
    api_id = get_input_with_default("API_ID", config.get("api_id"))
    if not api_id:
        logger.error("❌ API_ID 不能为空")
        return

    # 获取 API_HASH（支持默认值）
    api_hash = get_input_with_default("API_HASH", config.get("api_hash"))
    if not api_hash:
        logger.error("❌ API_HASH 不能为空")
        return

    # 获取手机号（支持默认值）
    phone_number = get_input_with_default(
        "手机号码（国际格式，如 +8613812345678）",
        config.get("phone_number")
    )
    if not phone_number:
        logger.error("❌ 手机号码不能为空")
        return

    # 保存配置（不保存群组ID，因为每次可能不同）
    new_config = {
        "api_id": api_id,
        "api_hash": api_hash,
        "phone_number": phone_number
    }
    if new_config != config:
        save_config(new_config)

    # 获取目标群组（每次都需要输入）
    target_group = input("\n目标群组ID（数字ID或 @username）: ").strip()
    if not target_group:
        logger.error("❌ 群组ID不能为空")
        return

    logger.info(f"\n连接到 Telegram...")
    client = TelegramClient(SESSION_NAME, int(api_id), api_hash)

    try:
        await client.start(phone=phone_number)
        logger.info("✅ 已连接到 Telegram")

        logger.info(f"正在获取群组信息: {target_group}")
        try:
            if target_group.startswith('@'):
                group_entity = await client.get_entity(target_group)
            else:
                group_id = int(target_group)
                group_entity = await client.get_entity(group_id)

            # 转换为 Bot API 格式的 ID
            bot_api_group_id = convert_to_bot_api_id(group_entity.id)

            logger.info(f"✅ 找到群组: {group_entity.title}")
            logger.info(f"   Telethon ID: {group_entity.id}")
            logger.info(f"   Bot API ID: {bot_api_group_id}")
            logger.info(f"   成员数: {getattr(group_entity, 'participants_count', '未知')}")

        except ValueError as e:
            logger.error(f"❌ 无效的群组ID: {target_group}")
            logger.error(f"   错误: {e}")
            return
        except Exception as e:
            logger.error(f"❌ 获取群组失败: {e}")
            return

        confirm = input(f"\n是否继续导入该群组的成员？(y/n): ").strip().lower()
        if confirm != 'y':
            logger.info("已取消操作")
            return

        # 使用转换后的 Bot API ID 查询数据库
        group_config = await get_group_config(bot_api_group_id)
        participants = await fetch_all_members(client, group_entity)

        if not participants:
            logger.warning("⚠️ 未获取到任何成员")
            return

        logger.info(f"开始导入到数据库...")
        print("-" * 60)

        added_count = 0
        updated_count = 0
        skipped_count = 0
        error_count = 0
        total = len(participants)

        with Session(engine) as session:
            for i, participant in enumerate(participants, 1):
                try:
                    status = import_member_sync(session, group_config.id, participant, i, total)
                    if status == "added":
                        added_count += 1
                    elif status == "updated":
                        updated_count += 1
                    else:
                        skipped_count += 1

                    # 每100个提交一次
                    if i % 100 == 0:
                        session.commit()
                        print(f"--- 已提交 {i} 条记录 ---")

                except Exception as e:
                    error_count += 1
                    print(f"[{i}/{total}] ❌ 错误: {participant.id} - {e}")

            session.commit()

        print("-" * 60)
        logger.info("✅ 导入完成！")
        logger.info(f"   总成员数: {total}")
        logger.info(f"   新增: {added_count}")
        logger.info(f"   更新: {updated_count}")
        logger.info(f"   跳过: {skipped_count}")
        if error_count > 0:
            logger.warning(f"   错误: {error_count}")

    except Exception as e:
        logger.error(f"❌ 发生错误: {e}")
        import traceback
        logger.error(traceback.format_exc())

    finally:
        await client.disconnect()
        logger.info("已断开连接")


if __name__ == "__main__":
    asyncio.run(main())
