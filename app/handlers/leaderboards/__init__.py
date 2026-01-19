"""
Leaderboard registry and module exports.

This module provides a central registry for all leaderboard types and manages
their lifecycle.
"""

from typing import Dict, List, Optional
from .base import BaseLeaderboard, LeaderboardEntry


class LeaderboardRegistry:
    """
    Central registry for all leaderboard types.

    The registry manages leaderboard discovery, registration, and retrieval.
    All leaderboard implementations should be registered here.
    """

    def __init__(self):
        self._leaderboards: Dict[str, BaseLeaderboard] = {}

    def register(self, leaderboard: BaseLeaderboard):
        """
        Register a leaderboard implementation.

        Args:
            leaderboard: Leaderboard instance to register
        """
        self._leaderboards[leaderboard.leaderboard_id] = leaderboard

    def unregister(self, leaderboard_id: str):
        """
        Unregister a leaderboard by ID.

        Args:
            leaderboard_id: ID of leaderboard to remove
        """
        if leaderboard_id in self._leaderboards:
            del self._leaderboards[leaderboard_id]

    def get(self, leaderboard_id: str) -> Optional[BaseLeaderboard]:
        """
        Get leaderboard by ID.

        Args:
            leaderboard_id: Unique leaderboard identifier

        Returns:
            BaseLeaderboard instance or None if not found
        """
        return self._leaderboards.get(leaderboard_id)

    def get_enabled(self, group_config: dict) -> List[BaseLeaderboard]:
        """
        Get all enabled leaderboards for a group.

        This method dynamically registers keyword leaderboards based on
        the group's configuration before returning enabled leaderboards.

        Args:
            group_config: The group's configuration dictionary

        Returns:
            List of enabled leaderboard instances
        """
        # First, sync keyword leaderboards with config
        self._sync_keyword_leaderboards(group_config)

        # Then return all enabled leaderboards
        return [
            lb for lb in self._leaderboards.values()
            if lb.is_enabled(group_config)
        ]

    def _sync_keyword_leaderboards(self, group_config: dict):
        """
        Synchronize keyword leaderboards with the group's configuration.

        This removes old keyword leaderboard instances and creates new ones
        based on the current patterns in the config.
        """
        from .keyword import KeywordLeaderboard

        # Remove all existing keyword leaderboards
        keyword_ids = [lb_id for lb_id in self._leaderboards.keys()
                      if lb_id.startswith('keyword_')]
        for lb_id in keyword_ids:
            self.unregister(lb_id)

        # Get keyword patterns from config
        keyword_config = group_config.get('leaderboards', {}).get('keyword', {})
        if not keyword_config.get('enabled', False):
            return

        patterns = keyword_config.get('patterns', [])

        # Register a new leaderboard instance for each pattern
        for idx, pattern in enumerate(patterns):
            pattern_name = pattern.get('name', f'关键字榜{idx+1}')
            pattern_regex = pattern.get('regex', '')

            if pattern_regex:  # Only register if regex is not empty
                leaderboard = KeywordLeaderboard(
                    pattern_name=pattern_name,
                    pattern_regex=pattern_regex,
                    pattern_index=idx
                )
                self.register(leaderboard)

    def all(self) -> List[BaseLeaderboard]:
        """
        Get all registered leaderboards.

        Returns:
            List of all leaderboard instances
        """
        return list(self._leaderboards.values())


# Global registry instance
registry = LeaderboardRegistry()


# Import and register static leaderboard implementations
def _register_static_leaderboards():
    """Import and register static leaderboard implementations."""
    from .night_shift import NightShiftLeaderboard
    from .done import DoneLeaderboard
    from .activity import ActivityLeaderboard
    from .time_activity import TimeActivityLeaderboard
    from .nsfw import NsfwLeaderboard

    registry.register(NightShiftLeaderboard())
    registry.register(DoneLeaderboard())
    registry.register(ActivityLeaderboard())
    registry.register(TimeActivityLeaderboard())
    registry.register(NsfwLeaderboard())
    # Note: Keyword leaderboards are registered dynamically per-group


# Register static leaderboards on module import
_register_static_leaderboards()


# Public exports
__all__ = [
    'BaseLeaderboard',
    'LeaderboardEntry',
    'LeaderboardRegistry',
    'registry'
]
