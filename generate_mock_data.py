"""
生成模拟数据用于测试统计功能
"""
import random
from datetime import datetime, timedelta, UTC
from sqlmodel import Session, select
from app.database.connection import engine
from app.models import GroupConfig, GroupMember, Message

# 模拟用户名和姓名
USERNAMES = [
    "alice", "bob", "charlie", "david", "emma", "frank", "grace", "henry",
    "iris", "jack", "kate", "leo", "mary", "nick", "olivia", "peter",
    "quinn", "rachel", "steve", "tina", "uma", "victor", "wendy", "xavier",
    "yuki", "zack", "anna", "ben", "cathy", "dan"
]

FULL_NAMES = [
    "Alice Wang", "Bob Chen", "Charlie Li", "David Zhang", "Emma Liu",
    "Frank Wu", "Grace Huang", "Henry Lin", "Iris Tang", "Jack Yang",
    "Kate Zhou", "Leo Sun", "Mary Zhao", "Nick Xu", "Olivia Song",
    "Peter Ma", "Quinn Feng", "Rachel Gao", "Steve Qian", "Tina Pan",
    "Uma Shi", "Victor Cao", "Wendy Luo", "Xavier Jiang", "Yuki Xie", "Zack Zhu",
    "Anna Han", "Ben Cheng", "Cathy Shen", "Dan Dong"
]

SAMPLE_MESSAGES = [
    "大家好！", "今天天气不错", "有人在吗？", "明天见", "好的，没问题",
    "谢谢分享", "学到了", "太棒了", "赞同", "我也是这么想的",
    "哈哈哈", "确实如此", "有道理", "支持", "666",
    "收到", "了解", "明白了", "好的好的", "可以的",
    "晚安", "早上好", "中午好", "晚上好", "周末快乐"
]


def generate_mock_data(group_id: int, user_count: int = 30, message_count: int = 200):
    """
    生成模拟数据

    参数:
    - group_id: Telegram 群组ID
    - user_count: 生成的用户数量
    - message_count: 生成的消息数量
    """
    with Session(engine) as session:
        # 检查或创建群组
        statement = select(GroupConfig).where(GroupConfig.group_id == group_id)
        group = session.exec(statement).first()

        if not group:
            print(f"❌ 群组 {group_id} 不存在，请先执行 /init 初始化群组")
            return

        if not group.is_initialized:
            print(f"❌ 群组 {group_id} 未初始化，请先执行 /init 初始化群组")
            return

        print(f"✅ 找到群组: {group.group_name}")

        # 生成用户
        print(f"\n📝 生成 {user_count} 个用户...")
        members = []
        base_user_id = 100000000

        for i in range(user_count):
            user_id = base_user_id + i
            username = USERNAMES[i % len(USERNAMES)] + str(i // len(USERNAMES))
            full_name = FULL_NAMES[i % len(FULL_NAMES)]

            # 检查是否已存在
            statement = select(GroupMember).where(
                GroupMember.group_id == group.id,
                GroupMember.user_id == user_id
            )
            existing_member = session.exec(statement).first()

            if existing_member:
                members.append(existing_member)
                continue

            # 随机加入时间（最近30天内）
            days_ago = random.randint(0, 30)
            joined_at = datetime.now(UTC) - timedelta(days=days_ago)

            member = GroupMember(
                group_id=group.id,
                user_id=user_id,
                username=username,
                full_name=full_name,
                joined_at=joined_at,
                message_count=0
            )
            session.add(member)
            members.append(member)

        session.commit()
        print(f"✅ 用户生成完成！")

        # 生成消息
        print(f"\n📨 生成 {message_count} 条消息...")
        for i in range(message_count):
            # 随机选择一个成员
            member = random.choice(members)

            # 随机消息时间（最近30天内）
            days_ago = random.uniform(0, 30)
            hours_ago = random.uniform(0, 24)
            created_at = datetime.now(UTC) - timedelta(days=days_ago, hours=hours_ago)

            # 确保消息时间在用户加入之后
            if created_at < member.joined_at:
                created_at = member.joined_at + timedelta(hours=random.uniform(0, 24))

            message = Message(
                message_id=1000000 + i,
                group_id=group.id,
                member_id=member.id,
                user_id=member.user_id,
                message_type="text",
                text=random.choice(SAMPLE_MESSAGES),
                is_channel_message=False,
                created_at=created_at
            )
            session.add(message)

            # 更新成员统计
            member.message_count += 1
            if not member.last_message_at or created_at > member.last_message_at:
                member.last_message_at = created_at
            session.add(member)

        session.commit()
        print(f"✅ 消息生成完成！")

        # 统计信息
        print(f"\n📊 数据统计:")
        print(f"  - 群组: {group.group_name} ({group_id})")
        print(f"  - 用户数: {user_count}")
        print(f"  - 消息数: {message_count}")
        print(f"\n✅ 模拟数据生成完成！现在可以测试 /stats 和 /inactive 命令了")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python scripts/generate_mock_data.py <群组ID> [用户数] [消息数]")
        print("示例: python scripts/generate_mock_data.py -1001234567890 30 200")
        sys.exit(1)

    group_id = int(sys.argv[1])
    user_count = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    message_count = int(sys.argv[3]) if len(sys.argv) > 3 else 200

    generate_mock_data(group_id, user_count, message_count)
