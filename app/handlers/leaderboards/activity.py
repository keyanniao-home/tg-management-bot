"""
Activity Leaderboard - 发言活跃榜

统计指定天数内的用户发言数，剔除发言为0的用户
"""

from datetime import timedelta, UTC, timezone
from telegram.helpers import escape_markdown
from sqlmodel import Session
from sqlalchemy import text
from typing import List, Tuple

from .base import BaseLeaderboard, LeaderboardEntry


class ActivityLeaderboard(BaseLeaderboard):
    """
    发言活跃榜

    统计指定天数内的用户发言数，按发言数降序排列
    只显示发言数 > 0 的用户
    """

    @property
    def leaderboard_id(self) -> str:
        return "activity"

    @property
    def display_name(self) -> str:
        return "发言榜"

    @property
    def emoji(self) -> str:
        return "💬"

    def is_enabled(self, group_config: dict) -> bool:
        return group_config.get('leaderboards', {}).get('activity', {}).get('enabled', False)

    def get_config(self, group_config: dict) -> dict:
        """
        获取发言榜配置

        Args:
            group_config: 群组配置字典

        Returns:
            发言榜配置
        """
        return group_config.get('leaderboards', {}).get('activity', {})

    def query_data(self, session: Session, group_id: int, days: int,
                   limit: int, offset: int, **kwargs) -> Tuple[List[LeaderboardEntry], int]:
        """
        查询发言榜数据

        Args:
            session: 数据库会话
            group_id: 群组ID
            days: 统计天数
            limit: 返回条数
            offset: 偏移量

        Returns:
            (榜单条目列表, 总条目数)
        """
        # 查询活跃用户数据
        query = text("""
        SELECT
            gm.user_id,
            gm.username,
            gm.full_name,
            COUNT(m.id) as msg_count,
            MAX(m.created_at) as last_msg_at
        FROM group_members gm
        LEFT JOIN messages m
            ON gm.id = m.member_id
            AND m.is_deleted = false
            AND m.created_at >= NOW() - :days * INTERVAL '1 day'
        WHERE gm.group_id = :group_id
            AND gm.is_active = true
        GROUP BY gm.user_id, gm.username, gm.full_name
        HAVING COUNT(m.id) > 0
        ORDER BY msg_count DESC, last_msg_at DESC
        LIMIT :limit OFFSET :offset
        """)

        result = session.execute(query, {
            "group_id": group_id,
            "days": days,
            "limit": limit,
            "offset": offset
        })

        entries = []
        for user_id, username, full_name, msg_count, last_msg_at in result:
            entries.append(LeaderboardEntry(
                user_id=user_id,
                username=username,
                full_name=full_name,
                score=msg_count,
                metadata={
                    'msg_count': msg_count,
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
            HAVING COUNT(m.id) > 0
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
        msg_count = e(str(entry.metadata['msg_count']), version=2)
        last_msg_at = entry.metadata['last_msg_at']

        if last_msg_at:
            last_msg_local = last_msg_at.replace(tzinfo=UTC).astimezone(
                timezone(timedelta(hours=8))
            )
            time_str = last_msg_local.strftime('%Y-%m-%d %H:%M')
            time_str = time_str.replace('-', '\\-')
        else:
            time_str = '无'

        return (
            f"{rank}\\. {user_display}\n"
            f"   发言: {msg_count}次 \\| 最后: {time_str}\n"
        )

