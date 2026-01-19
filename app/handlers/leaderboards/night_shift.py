"""
Night Shift Leaderboard implementation.

Tracks users active during late night hours (1:00 AM - 5:30 AM) with
a minimum 2-hour message span.
"""

from datetime import datetime, timezone, timedelta, UTC
from typing import List, Tuple
from sqlalchemy import text
from sqlmodel import Session
from telegram.helpers import escape_markdown

from .base import BaseLeaderboard, LeaderboardEntry


class NightShiftLeaderboard(BaseLeaderboard):
    """
    Night shift leaderboard (值班榜).

    Tracks users who are active during 1:00-5:30 AM (Asia/Shanghai timezone)
    and have a message span of at least 2 hours during that period.
    Ranks users by their last message time (later = higher rank).
    """

    # Constants (hardcoded as per requirements)
    NIGHT_START_HOUR = 1
    NIGHT_END_HOUR = 5
    NIGHT_END_MINUTE = 30
    MIN_DURATION_HOURS = 2

    @property
    def leaderboard_id(self) -> str:
        return "night_shift"

    @property
    def display_name(self) -> str:
        return "值班榜"

    @property
    def emoji(self) -> str:
        return "🌙"

    def is_enabled(self, group_config: dict) -> bool:
        return group_config.get('leaderboards', {}).get('night_shift', {}).get('enabled', False)

    def get_config(self, group_config: dict) -> dict:
        return group_config.get('leaderboards', {}).get('night_shift', {})

    def query_data(self, session: Session, group_id: int, days: int,
                   limit: int, offset: int, **kwargs) -> Tuple[List[LeaderboardEntry], int]:
        """
        Query users active during night shift (1:00-5:30 AM)
        with message span >= 2 hours, sorted by last message time (descending).

        Shows the most recent COMPLETED night shift period:
        - Before 05:30: Shows previous day's 1:00-5:30 (yesterday's completed shift)
        - After 05:30: Shows today's 1:00-5:30 (just completed shift)
        """

        # Calculate time range in Python (much clearer!)
        # Get current time in Beijing timezone
        beijing_tz = timezone(timedelta(hours=8))
        now_beijing = datetime.now(UTC).astimezone(beijing_tz)

        # Determine which shift to show
        if now_beijing.hour < 5 or (now_beijing.hour == 5 and now_beijing.minute <= 30):
            # Before 05:30, show yesterday's shift
            shift_date = now_beijing.date() - timedelta(days=1)
        else:
            # After 05:30, show today's shift
            shift_date = now_beijing.date()

        # Create shift time range in Beijing timezone
        shift_start_beijing = datetime.combine(shift_date, datetime.min.time().replace(hour=1), tzinfo=beijing_tz)
        shift_end_beijing = datetime.combine(shift_date, datetime.min.time().replace(hour=5, minute=30), tzinfo=beijing_tz)

        # Convert to UTC for database query
        shift_start_utc = shift_start_beijing.astimezone(UTC)
        shift_end_utc = shift_end_beijing.astimezone(UTC)

        # Simple SQL query using UTC times
        query = text("""
        WITH night_messages AS (
            SELECT
                gm.user_id,
                gm.username,
                gm.full_name,
                m.created_at
            FROM messages m
            JOIN group_members gm ON m.member_id = gm.id
            WHERE m.group_id = :group_id
                AND m.is_deleted = false
                AND gm.is_active = true
                AND m.created_at >= :start_time
                AND m.created_at <= :end_time
        ),
        user_stats AS (
            SELECT
                user_id,
                username,
                full_name,
                MIN(created_at) as first_msg,
                MAX(created_at) as last_msg,
                COUNT(*) as msg_count
            FROM night_messages
            GROUP BY user_id, username, full_name
            HAVING EXTRACT(EPOCH FROM (MAX(created_at) - MIN(created_at)))/3600 >= :min_hours
        )
        SELECT
            user_id,
            username,
            full_name,
            last_msg,
            msg_count,
            COUNT(*) OVER() as total_count
        FROM user_stats
        ORDER BY last_msg DESC
        LIMIT :limit OFFSET :offset
        """)

        params = {
            'group_id': group_id,
            'start_time': shift_start_utc,
            'end_time': shift_end_utc,
            'min_hours': self.MIN_DURATION_HOURS,
            'limit': limit,
            'offset': offset
        }

        result = session.execute(query, params).fetchall()

        if not result:
            return [], 0

        total_count = result[0][5] if result else 0

        # Convert UTC times back to Beijing time for display
        entries = [
            LeaderboardEntry(
                user_id=row[0],
                username=row[1],
                full_name=row[2],
                score=row[3].replace(tzinfo=UTC).astimezone(beijing_tz),  # Convert to Beijing time
                metadata={'msg_count': row[4]}
            )
            for row in result
        ]

        return entries, total_count

    def format_entry(self, rank: int, entry: LeaderboardEntry,
                     display_mode: str) -> str:
        """
        Format entry as:
        rank. user
           最后: HH:MM | 消息: N条
        """

        # User display (reuse existing logic from stats.py)
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

        # Format timestamp
        # entry.score is already in Beijing timezone (aware datetime)
        time_str = escape_markdown(entry.score.strftime('%H:%M'), version=2)
        msg_count = escape_markdown(str(entry.metadata['msg_count']), version=2)

        return (
            f"{rank}\\. {user_display}\n"
            f"   最后: {time_str} \\| 消息: {msg_count}条\n"
        )
