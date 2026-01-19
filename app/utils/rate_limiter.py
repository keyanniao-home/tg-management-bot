"""
Rate limiter utility for callback queries.

Prevents rapid repeated clicks on inline buttons by implementing
both global and per-user rate limiting.
"""

import time
from collections import defaultdict
from typing import Dict, Tuple
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes


class CallbackRateLimiter:
    """
    Rate limiter for callback queries.

    Implements two levels of rate limiting:
    1. Global rate limit: Same callback can only be processed once per interval
    2. Per-user rate limit: User can only trigger callbacks at a certain rate
    """

    def __init__(self):
        # Global rate limit: callback_data -> last_timestamp
        self._global_cache: Dict[str, float] = {}

        # Per-user rate limit: user_id -> (callback_data, last_timestamp)
        self._user_cache: Dict[int, Tuple[str, float]] = {}

        # Cleanup timestamp
        self._last_cleanup = time.time()

    def is_rate_limited(self, callback_data: str, user_id: int,
                       global_interval: float = 1.0,
                       user_interval: float = 0.5) -> Tuple[bool, str]:
        """
        Check if a callback should be rate limited.

        Args:
            callback_data: The callback data string
            user_id: The user ID triggering the callback
            global_interval: Global cooldown in seconds (default: 1.0)
            user_interval: Per-user cooldown in seconds (default: 0.5)

        Returns:
            (is_limited, reason) tuple where:
                - is_limited: True if rate limited, False otherwise
                - reason: Human-readable reason for rate limiting
        """
        current_time = time.time()

        # Periodic cleanup of old entries (every 60 seconds)
        if current_time - self._last_cleanup > 60:
            self._cleanup_old_entries(current_time)

        # Check global rate limit
        if callback_data in self._global_cache:
            time_since_last = current_time - self._global_cache[callback_data]
            if time_since_last < global_interval:
                remaining = global_interval - time_since_last
                return True, f"⚠️ 操作过快 (429)\n请等待 {remaining:.1f} 秒后再试"

        # Check per-user rate limit
        if user_id in self._user_cache:
            last_callback, last_time = self._user_cache[user_id]
            time_since_last = current_time - last_time
            if time_since_last < user_interval:
                remaining = user_interval - time_since_last
                return True, f"⚠️ 点击过快 (429)\n请等待 {remaining:.1f} 秒后再试"

        # Not rate limited - update caches
        self._global_cache[callback_data] = current_time
        self._user_cache[user_id] = (callback_data, current_time)

        return False, ""

    def _cleanup_old_entries(self, current_time: float, max_age: float = 300.0):
        """
        Clean up entries older than max_age seconds.

        Args:
            current_time: Current timestamp
            max_age: Maximum age in seconds (default: 5 minutes)
        """
        # Clean global cache
        self._global_cache = {
            k: v for k, v in self._global_cache.items()
            if current_time - v < max_age
        }

        # Clean user cache
        self._user_cache = {
            k: v for k, v in self._user_cache.items()
            if current_time - v[1] < max_age
        }

        self._last_cleanup = current_time

    def reset(self):
        """Clear all rate limit caches."""
        self._global_cache.clear()
        self._user_cache.clear()
        self._last_cleanup = time.time()


# Global rate limiter instance
_rate_limiter = CallbackRateLimiter()


def rate_limit_callback(global_interval: float = 1.0, user_interval: float = 0.5):
    """
    Decorator for rate limiting callback query handlers.

    Args:
        global_interval: Global cooldown in seconds (default: 1.0)
        user_interval: Per-user cooldown in seconds (default: 0.5)

    Usage:
        @rate_limit_callback(global_interval=1.0, user_interval=0.5)
        async def my_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            query = update.callback_query

            if not query:
                # Not a callback query, proceed normally
                return await func(update, context, *args, **kwargs)

            callback_data = query.data
            user_id = query.from_user.id

            # Check rate limit
            is_limited, reason = _rate_limiter.is_rate_limited(
                callback_data, user_id, global_interval, user_interval
            )

            if is_limited:
                # Answer the callback to stop loading animation
                await query.answer(reason, show_alert=False)
                return None

            # Not rate limited, proceed with handler
            return await func(update, context, *args, **kwargs)

        return wrapper
    return decorator


def get_rate_limiter() -> CallbackRateLimiter:
    """Get the global rate limiter instance."""
    return _rate_limiter
