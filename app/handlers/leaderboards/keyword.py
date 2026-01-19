"""
Keyword Leaderboard implementation.

Tracks users whose messages match configured regex patterns.
"""

from datetime import datetime, timezone, timedelta, UTC
from typing import List, Tuple, Dict, Optional
from sqlalchemy import text
from sqlmodel import Session
from telegram.helpers import escape_markdown

from .base import BaseLeaderboard, LeaderboardEntry


class KeywordLeaderboard(BaseLeaderboard):
    """
    Keyword matching leaderboard (关键字榜).

    Each instance represents a single keyword pattern.
    Multiple instances can be registered for different patterns.
    """

    def __init__(self, pattern_name: str, pattern_regex: str, pattern_index: int = 0):
        """
        Initialize a keyword leaderboard for a specific pattern.

        Args:
            pattern_name: Display name for this pattern (e.g., "链接榜")
            pattern_regex: Regex pattern to match
            pattern_index: Index in the patterns array (for config lookup)
        """
        self._pattern_name = pattern_name
        self._pattern_regex = pattern_regex
        self._pattern_index = pattern_index

    @property
    def leaderboard_id(self) -> str:
        return f"keyword_{self._pattern_index}"

    @property
    def display_name(self) -> str:
        return self._pattern_name

    @property
    def emoji(self) -> str:
        return "🔑"

    def is_enabled(self, group_config: dict) -> bool:
        # Check if keyword leaderboard is enabled globally
        keyword_config = group_config.get('leaderboards', {}).get('keyword', {})
        if not keyword_config.get('enabled', False):
            return False

        # Check if this specific pattern still exists in config
        patterns = keyword_config.get('patterns', [])
        return self._pattern_index < len(patterns)

    def get_config(self, group_config: dict) -> dict:
        return group_config.get('leaderboards', {}).get('keyword', {})

    def query_data(self, session: Session, group_id: int, days: int,
                   limit: int, offset: int, **kwargs) -> Tuple[List[LeaderboardEntry], int]:
        """
        Query users matching this keyword pattern.
        """

        query = text("""
        SELECT
            gm.user_id,
            gm.username,
            gm.full_name,
            COUNT(*) as match_count,
            MAX(m.created_at) as last_match,
            COUNT(*) OVER() as total_count
        FROM messages m
        JOIN group_members gm ON m.member_id = gm.id
        WHERE m.group_id = :group_id
            AND m.is_deleted = false
            AND m.created_at >= NOW() - :days * INTERVAL '1 day'
            AND gm.is_active = true
            AND m.text IS NOT NULL
            AND m.text ~ :regex_pattern
        GROUP BY gm.user_id, gm.username, gm.full_name
        ORDER BY match_count DESC, last_match DESC
        LIMIT :limit OFFSET :offset
        """)

        params = {
            'group_id': group_id,
            'days': days,
            'regex_pattern': self._pattern_regex,
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
                score=row[3],  # match_count
                metadata={'last_match': row[4], 'pattern_name': self._pattern_name}
            )
            for row in result
        ]

        return entries, total_count

    def format_entry(self, rank: int, entry: LeaderboardEntry,
                     display_mode: str) -> str:
        """
        Format entry as:
        rank. user
           匹配: N次 | 最后: YYYY-MM-DD HH:MM
        """

        # User display (same logic as night shift)
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
        match_count = escape_markdown(str(entry.score), version=2)
        last_match_local = entry.metadata['last_match'].replace(tzinfo=UTC).astimezone(
            timezone(timedelta(hours=8))
        )
        # Format time without escaping (escape_markdown would turn - into \-)
        time_str = last_match_local.strftime('%Y-%m-%d %H:%M')
        # Manually escape only the hyphens that need escaping in MarkdownV2
        time_str = time_str.replace('-', '\\-')

        return (
            f"{rank}\\. {user_display}\n"
            f"   匹配: {match_count}次 \\| 最后: {time_str}\n"
        )
