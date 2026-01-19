"""
Base classes for leaderboard system.

This module defines the abstract interface that all leaderboard types must implement.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple, Optional
from dataclasses import dataclass
from sqlmodel import Session


@dataclass
class LeaderboardEntry:
    """Standard leaderboard entry format."""
    user_id: int
    username: Optional[str]
    full_name: str
    score: Any  # Can be int (count), datetime (timestamp), float (score)
    metadata: Dict[str, Any]  # Additional info specific to leaderboard type

    def __init__(self, user_id: int, username: Optional[str], full_name: str,
                 score: Any, metadata: Optional[Dict[str, Any]] = None):
        self.user_id = user_id
        self.username = username
        self.full_name = full_name
        self.score = score
        self.metadata = metadata or {}


class BaseLeaderboard(ABC):
    """
    Abstract base class for all leaderboard types.

    All leaderboard implementations must inherit from this class and implement
    all abstract methods.
    """

    @property
    @abstractmethod
    def leaderboard_id(self) -> str:
        """
        Unique identifier for this leaderboard type.

        Returns:
            str: Unique ID (e.g., 'night_shift', 'keyword')
        """
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """
        Display name in Chinese for UI.

        Returns:
            str: Display name (e.g., '值班榜', '关键字榜')
        """
        pass

    @property
    @abstractmethod
    def emoji(self) -> str:
        """
        Emoji icon for UI display.

        Returns:
            str: Emoji (e.g., '🌙', '🔑')
        """
        pass

    @abstractmethod
    def is_enabled(self, group_config: dict) -> bool:
        """
        Check if this leaderboard is enabled for the group.

        Args:
            group_config: The group's config dictionary

        Returns:
            bool: True if enabled, False otherwise
        """
        pass

    @abstractmethod
    def get_config(self, group_config: dict) -> dict:
        """
        Get leaderboard-specific configuration.

        Args:
            group_config: The group's config dictionary

        Returns:
            dict: Leaderboard-specific config
        """
        pass

    @abstractmethod
    def query_data(self, session: Session, group_id: int, days: int,
                   limit: int, offset: int, **kwargs) -> Tuple[List[LeaderboardEntry], int]:
        """
        Query leaderboard data from database.

        Args:
            session: SQLModel database session
            group_id: Internal group ID (not Telegram chat ID)
            days: Time range in days (1, 7, 30, etc.)
            limit: Maximum entries to return (page size)
            offset: Offset for pagination
            **kwargs: Additional parameters specific to leaderboard type

        Returns:
            Tuple of:
                - List[LeaderboardEntry]: Leaderboard entries for current page
                - int: Total count of entries (for pagination)
        """
        pass

    @abstractmethod
    def format_entry(self, rank: int, entry: LeaderboardEntry,
                     display_mode: str) -> str:
        """
        Format a single leaderboard entry for display.

        Args:
            rank: Rank number (1-indexed)
            entry: LeaderboardEntry to format
            display_mode: Display mode ('mention', 'name_id', 'name')

        Returns:
            str: Formatted entry text (MarkdownV2 format)
        """
        pass

    def get_extra_buttons(self, group_config: dict, current_selection: Optional[str] = None) -> List[List[Dict[str, str]]]:
        """
        Get additional inline button rows specific to this leaderboard.

        Override this method if the leaderboard needs custom buttons
        (e.g., keyword leaderboard pattern selector).

        Args:
            group_config: The group's config dictionary
            current_selection: Current selection identifier (optional)

        Returns:
            List of button rows, where each row is a list of button dicts with:
                - 'text': Button label
                - 'callback_data': Callback data string
        """
        return []
