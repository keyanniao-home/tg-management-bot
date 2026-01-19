"""
NSFW Leaderboard implementation.

Tracks users who posted NSFW images (porn, hentai, sexy) detected by the NSFW detector.
"""

from datetime import datetime, timezone, timedelta, UTC
from typing import List, Tuple, Dict
from sqlalchemy import text
from sqlmodel import Session
from telegram.helpers import escape_markdown

from .base import BaseLeaderboard, LeaderboardEntry


class NsfwLeaderboard(BaseLeaderboard):
    """
    NSFW leaderboard (NSFW榜).

    Tracks users who posted NSFW images categorized by type:
    - porn (色情): 🍌
    - hentai (色情动漫): ❤️‍🔥
    - sexy (性感): 💋

    Ranks users by total NSFW image count.
    """

    @property
    def leaderboard_id(self) -> str:
        return "nsfw"

    @property
    def display_name(self) -> str:
        return "NSFW榜"

    @property
    def emoji(self) -> str:
        return "🔞"

    def is_enabled(self, group_config: dict) -> bool:
        return group_config.get('leaderboards', {}).get('nsfw', {}).get('enabled', False)

    def get_config(self, group_config: dict) -> dict:
        return group_config.get('leaderboards', {}).get('nsfw', {})

    def query_data(self, session: Session, group_id: int, days: int,
                   limit: int, offset: int, **kwargs) -> Tuple[List[LeaderboardEntry], int]:
        """
        Query users with the most NSFW images within the specified time range.
        Groups by NSFW type (porn, hentai, sexy) and shows counts for each type.
        """

        query = text("""
        WITH nsfw_messages AS (
            SELECT
                gm.user_id,
                gm.username,
                gm.full_name,
                m.extra_data->>'nsfw_type' as nsfw_type,
                m.created_at
            FROM messages m
            JOIN group_members gm ON m.member_id = gm.id
            WHERE m.group_id = :group_id
                AND m.is_deleted = false
                AND m.created_at >= NOW() - :days * INTERVAL '1 day'
                AND gm.is_active = true
                AND m.message_type = 'photo'
                AND m.extra_data IS NOT NULL
                AND m.extra_data->>'nsfw_type' IS NOT NULL
        )
        SELECT
            user_id,
            username,
            full_name,
            COUNT(*) as total_nsfw,
            COUNT(*) FILTER (WHERE nsfw_type = 'porn') as porn_count,
            COUNT(*) FILTER (WHERE nsfw_type = 'hentai') as hentai_count,
            COUNT(*) FILTER (WHERE nsfw_type = 'sexy') as sexy_count,
            MAX(created_at) as last_nsfw,
            COUNT(*) OVER() as total_count
        FROM nsfw_messages
        GROUP BY user_id, username, full_name
        ORDER BY total_nsfw DESC, last_nsfw DESC
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

        total_count = result[0][8] if result else 0

        entries = [
            LeaderboardEntry(
                user_id=row[0],
                username=row[1],
                full_name=row[2],
                score=row[3],  # total_nsfw
                metadata={
                    'porn_count': row[4],
                    'hentai_count': row[5],
                    'sexy_count': row[6],
                    'last_nsfw': row[7]
                }
            )
            for row in result
        ]

        return entries, total_count

    def format_entry(self, rank: int, entry: LeaderboardEntry,
                     display_mode: str) -> str:
        """
        Format entry as:
        rank. user
           🔞总计: N次 | 🍌: X 🔥: Y 👄: Z
           最后: YYYY-MM-DD HH:MM
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

        # Format counts
        total_count = escape_markdown(str(entry.score), version=2)
        porn_count = entry.metadata['porn_count']
        hentai_count = entry.metadata['hentai_count']
        sexy_count = entry.metadata['sexy_count']

        # Build counts string - only show non-zero counts
        count_parts = []
        if porn_count > 0:
            count_parts.append(f"🍌: {porn_count}")
        if hentai_count > 0:
            count_parts.append(f"❤️‍🔥: {hentai_count}")
        if sexy_count > 0:
            count_parts.append(f"💋: {sexy_count}")

        counts_str = " ".join(count_parts)
        counts_str = escape_markdown(counts_str, version=2)

        # Format time
        last_nsfw_local = entry.metadata['last_nsfw'].replace(tzinfo=UTC).astimezone(
            timezone(timedelta(hours=8))
        )
        time_str = last_nsfw_local.strftime('%Y-%m-%d %H:%M')
        time_str = time_str.replace('-', '\\-')

        return (
            f"{rank}\\. {user_display}\n"
            f"   🔞总计: {total_count}次 \\| {counts_str}\n"
            f"   最后: {time_str}\n"
        )
