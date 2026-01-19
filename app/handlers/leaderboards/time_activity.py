"""
Time Activity Leaderboard - 时段活跃榜

统计用户在不同30分钟时间段内的发言情况
每个时间段内有发言则计分+1，最终分数代表用户的全天活跃度
"""

from datetime import timedelta, UTC, timezone
from telegram.helpers import escape_markdown
from sqlmodel import Session
from sqlalchemy import text
from typing import List, Tuple

from .base import BaseLeaderboard, LeaderboardEntry


class TimeActivityLeaderboard(BaseLeaderboard):
    """
    时段活跃榜

    以30分钟为一个时间段，统计指定天数内用户在多少个不同时间段内发言
    分数 = 在不同时间段内发言的段数
    分数越高说明用户全天在线活跃度越高
    """

    @property
    def leaderboard_id(self) -> str:
        return "time_activity"

    @property
    def display_name(self) -> str:
        return "活跃榜"

    @property
    def emoji(self) -> str:
        return "⏰"

    def is_enabled(self, group_config: dict) -> bool:
        return group_config.get('leaderboards', {}).get('time_activity', {}).get('enabled', False)

    def get_config(self, group_config: dict) -> dict:
        """
        获取时段活跃榜配置

        Args:
            group_config: 群组配置字典

        Returns:
            时段活跃榜配置
        """
        return group_config.get('leaderboards', {}).get('time_activity', {})

    def query_data(self, session: Session, group_id: int, days: int,
                   limit: int, offset: int, **kwargs) -> Tuple[List[LeaderboardEntry], int]:
        """
        查询时段活跃榜数据

        Args:
            session: 数据库会话
            group_id: 群组ID
            days: 统计天数
            limit: 返回条数
            offset: 偏移量

        Returns:
            (榜单条目列表, 总条目数)
        """
        # 查询在不同30分钟时间段内发言的用户数据
        # 使用 FLOOR(EXTRACT(EPOCH FROM created_at) / 1800) 将时间戳转换为30分钟段
        # 1800秒 = 30分钟
        query = text("""
        SELECT
            gm.user_id,
            gm.username,
            gm.full_name,
            COUNT(DISTINCT FLOOR(EXTRACT(EPOCH FROM m.created_at) / 1800)) as time_slots,
            COUNT(m.id) as total_messages,
            MAX(m.created_at) as last_msg_at
        FROM group_members gm
        LEFT JOIN messages m
            ON gm.id = m.member_id
            AND m.is_deleted = false
            AND m.created_at >= NOW() - :days * INTERVAL '1 day'
        WHERE gm.group_id = :group_id
            AND gm.is_active = true
        GROUP BY gm.user_id, gm.username, gm.full_name
        HAVING COUNT(DISTINCT FLOOR(EXTRACT(EPOCH FROM m.created_at) / 1800)) > 0
        ORDER BY time_slots DESC, total_messages DESC, last_msg_at DESC
        LIMIT :limit OFFSET :offset
        """)

        result = session.execute(query, {
            "group_id": group_id,
            "days": days,
            "limit": limit,
            "offset": offset
        })

        entries = []
        for user_id, username, full_name, time_slots, total_messages, last_msg_at in result:
            entries.append(LeaderboardEntry(
                user_id=user_id,
                username=username,
                full_name=full_name,
                score=time_slots,  # 分数为活跃时间段数
                metadata={
                    'time_slots': time_slots,
                    'total_messages': total_messages,
                    'last_msg_at': last_msg_at
                }
            ))

        # 查询总数
        count_query = text("""
        SELECT COUNT(*) as total
        FROM (
            SELECT gm.user_id
            FROM group_members gm
            LEFT JOIN messages m
                ON gm.id = m.member_id
                AND m.is_deleted = false
                AND m.created_at >= NOW() - :days * INTERVAL '1 day'
            WHERE gm.group_id = :group_id
                AND gm.is_active = true
            GROUP BY gm.user_id
            HAVING COUNT(DISTINCT FLOOR(EXTRACT(EPOCH FROM m.created_at) / 1800)) > 0
        ) active_users
        """)

        count_result = session.execute(count_query, {
            "group_id": group_id,
            "days": days
        }).first()

        total_count = count_result[0] if count_result else 0

        return entries, total_count

    def format_entry(self, rank: int, entry: LeaderboardEntry, display_mode: str = 'mention') -> str:
        """
        格式化单个榜单条目

        Args:
            rank: 排名（从1开始）
            entry: 榜单条目
            display_mode: 显示模式 (mention/name/name_id)

        Returns:
            格式化后的 MarkdownV2 文本
        """
        e = escape_markdown

        # 根据显示模式格式化用户名
        if display_mode == 'name_id':
            # 名字+ID模式
            escaped_name = e(entry.full_name, version=2)
            escaped_id = e(str(entry.user_id), version=2)
            user_display = f"{escaped_name} \\(ID: {escaped_id}\\)"
        elif display_mode == 'name':
            # 只显示名字模式
            user_display = e(entry.full_name, version=2)
        else:
            # mention模式（默认）
            if entry.user_id < 0:  # 频道ID是负数
                if entry.username:
                    user_display = f"@{e(entry.username, version=2)}"
                else:
                    user_display = e(entry.full_name, version=2)
            else:
                # Regular user - create mention link
                escaped_name = e(entry.full_name, version=2)
                user_display = f"[{escaped_name}](tg://user?id={entry.user_id})"

        # 格式化元数据
        time_slots = e(str(entry.metadata['time_slots']), version=2)
        total_messages = e(str(entry.metadata['total_messages']), version=2)
        last_msg_at = entry.metadata['last_msg_at']

        if last_msg_at:
            last_msg_local = last_msg_at.replace(tzinfo=UTC).astimezone(
                timezone(timedelta(hours=8))
            )
            time_str = last_msg_local.strftime('%Y-%m-%d %H:%M')
            time_str = time_str.replace('-', '\\-')
        else:
            time_str = '无'

        # 计算活跃度百分比 (假设一天最多48个时间段)
        # 如果统计7天，理论最大段数是 7 * 48 = 336
        # 但这里只显示活跃段数和总消息数
        return (
            f"{rank}\\. {user_display}\n"
            f"   活跃段数: {time_slots} \\| 总消息: {total_messages}次 \\| 最后: {time_str}\n"
        )
