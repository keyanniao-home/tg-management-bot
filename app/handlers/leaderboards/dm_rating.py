"""
DM 榜单 - 统计群组成员使用 dm/pm 关键词的次数
"""

from typing import List, Tuple
from sqlmodel import Session, select, and_
from sqlalchemy import func
from telegram.helpers import escape_markdown

from app.handlers.leaderboards.base import BaseLeaderboard, LeaderboardEntry
from app.models.dm_detection import DMDetection


class DMRatingLeaderboard(BaseLeaderboard):
    """
    DM 榜单

    统计群组成员在消息中使用 dm/pm 关键词的次数
    按次数降序排列，只显示次数 > 0 的用户
    """

    @property
    def leaderboard_id(self) -> str:
        return "dm_rating"

    @property
    def display_name(self) -> str:
        return "DM榜"

    @property
    def emoji(self) -> str:
        return "📨"

    def is_enabled(self, group_config: dict) -> bool:
        return (
            group_config.get("leaderboards", {})
            .get("dm_rating", {})
            .get("enabled", False)
        )

    def get_config(self, group_config: dict) -> dict:
        return group_config.get("leaderboards", {}).get("dm_rating", {})

    def query_data(
        self,
        session: Session,
        group_id: int,
        days: int,
        limit: int,
        offset: int,
        **kwargs,
    ) -> Tuple[List[LeaderboardEntry], int]:
        """
        查询 DM 榜单数据

        注意：DM 榜单不按天数筛选，统计的是累计总次数
        """
        from app.models.group import GroupConfig

        # 获取群组的 Telegram ID
        group = session.get(GroupConfig, group_id)
        if not group:
            return [], 0

        telegram_group_id = group.group_id

        # 统计总数
        count_stmt = (
            select(func.count())
            .select_from(DMDetection)
            .where(
                and_(
                    DMDetection.group_id == telegram_group_id, DMDetection.dm_count > 0
                )
            )
        )
        total = session.exec(count_stmt).one()

        # 查询排名数据
        statement = (
            select(DMDetection)
            .where(
                and_(
                    DMDetection.group_id == telegram_group_id, DMDetection.dm_count > 0
                )
            )
            .order_by(DMDetection.dm_count.desc())
            .offset(offset)
            .limit(limit)
        )
        results = list(session.exec(statement).all())

        # 转换为 LeaderboardEntry
        entries = []
        for record in results:
            entry = LeaderboardEntry(
                user_id=record.user_id,
                username=record.username,
                full_name=record.full_name or f"用户{record.user_id}",
                score=record.dm_count,
            )
            entries.append(entry)

        return entries, total

    def format_entry(
        self, rank: int, entry: LeaderboardEntry, display_mode: str
    ) -> str:
        """格式化榜单条目"""
        # 排名图标
        if rank == 1:
            rank_icon = "🥇"
        elif rank == 2:
            rank_icon = "🥈"
        elif rank == 3:
            rank_icon = "🥉"
        else:
            rank_icon = f"{rank}\\."

        # 用户显示
        if display_mode == "mention" and entry.username:
            user_display = f"@{escape_markdown(entry.username, version=2)}"
        elif display_mode == "name_id":
            name = escape_markdown(entry.full_name or "Unknown", version=2)
            user_display = f"[{name}](tg://user?id={entry.user_id})"
        else:
            user_display = escape_markdown(entry.full_name or "Unknown", version=2)

        # 分数 - 需要转义特殊字符
        score = escape_markdown(str(entry.score), version=2)

        return f"{rank_icon} {user_display}: *{score}* 次"
