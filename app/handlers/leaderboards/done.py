"""
Done Leaderboard implementation.

Tracks users who posted images that were detected as "done" images
(images containing green check marks or completion indicators).
"""

from datetime import datetime, timezone, timedelta, UTC
from typing import List, Tuple
from sqlalchemy import text
from sqlmodel import Session
from telegram.helpers import escape_markdown

from .base import BaseLeaderboard, LeaderboardEntry


class DoneLeaderboard(BaseLeaderboard):
    """
    Done leaderboard (打卡榜/完成榜).

    Tracks users who posted images with detected completion indicators.
    Ranks users by the number of "done" images they posted.
    """

    @property
    def leaderboard_id(self) -> str:
        return "done"

    @property
    def display_name(self) -> str:
        return "DONE榜"

    @property
    def emoji(self) -> str:
        return "💯"

    def is_enabled(self, group_config: dict) -> bool:
        return group_config.get('leaderboards', {}).get('done', {}).get('enabled', False)

    def get_config(self, group_config: dict) -> dict:
        return group_config.get('leaderboards', {}).get('done', {})

    def query_data(self, session: Session, group_id: int, days: int,
                   limit: int, offset: int, **kwargs) -> Tuple[List[LeaderboardEntry], int]:
        """
        Query users with the most "done" images within the specified time range.
        """

        query = text("""
        SELECT
            gm.user_id,
            gm.username,
            gm.full_name,
            COUNT(*) as done_count,
            MAX(m.created_at) as last_done,
            COUNT(*) OVER() as total_count
        FROM messages m
        JOIN group_members gm ON m.member_id = gm.id
        WHERE m.group_id = :group_id
            AND m.is_deleted = false
            AND m.created_at >= NOW() - :days * INTERVAL '1 day'
            AND gm.is_active = true
            AND m.message_type = 'photo'
            AND m.extra_data IS NOT NULL
            AND m.extra_data->>'is_done_image' = 'true'
        GROUP BY gm.user_id, gm.username, gm.full_name
        ORDER BY done_count DESC, last_done DESC
        LIMIT :limit OFFSET :offset
        """)

        params = {
            'group_id': group_id,
            'days': days,
            'limit': limit,
            'offset': offset
        }

        result = session.execute(query, params).fetchall()

        if not result:
            return [], 0

        total_count = result[0][5] if result else 0

        entries = [
            LeaderboardEntry(
                user_id=row[0],
                username=row[1],
                full_name=row[2],
                score=row[3],  # done_count
                metadata={'last_done': row[4]}
            )
            for row in result
        ]

        return entries, total_count

    def format_entry(self, rank: int, entry: LeaderboardEntry,
                     display_mode: str) -> str:
        """
        Format entry as:
        rank. user
           打卡: N次 | 最后: YYYY-MM-DD HH:MM
        """

        # User display (same logic as other leaderboards)
        if display_mode == 'name_id':
            escaped_name = escape_markdown(entry.full_name, version=2)
            user_display = f"{escaped_name} \\(ID: {entry.user_id}\\)"
        elif display_mode == 'name':
            user_display = escape_markdown(entry.full_name, version=2)
        else:  # mention
            if entry.user_id < 0:
                # Negative ID = channel
                if entry.username:
                    user_display = f"@{escape_markdown(entry.username, version=2)}"
                else:
                    user_display = escape_markdown(entry.full_name, version=2)
            else:
                # Regular user - create mention link
                escaped_name = escape_markdown(entry.full_name, version=2)
                user_display = f"[{escaped_name}](tg://user?id={entry.user_id})"

        # Format metadata
        done_count = escape_markdown(str(entry.score), version=2)
        last_done_local = entry.metadata['last_done'].replace(tzinfo=UTC).astimezone(
            timezone(timedelta(hours=8))
        )
        # Format time
        time_str = last_done_local.strftime('%Y-%m-%d %H:%M')
        time_str = time_str.replace('-', '\\-')

        return (
            f"{rank}\\. {user_display}\n"
            f"   DONE: {done_count}次 \\| 最后: {time_str}\n"
        )
