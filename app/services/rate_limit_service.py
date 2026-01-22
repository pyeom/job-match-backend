"""
Rate limiting service for API endpoints.
In-memory implementation for now, should use Redis in production.
"""
from datetime import datetime, timedelta
from typing import Dict, Tuple
from collections import defaultdict
import uuid


class RateLimitService:
    """Service for rate limiting requests per user."""

    def __init__(self):
        # Store: {user_id: [(timestamp1, count1), (timestamp2, count2), ...]}
        # Each entry represents a time window with count of requests
        self._requests: Dict[uuid.UUID, list[Tuple[datetime, int]]] = defaultdict(list)

    def check_rate_limit(
        self,
        user_id: uuid.UUID,
        max_requests: int = 10,
        window_seconds: int = 3600
    ) -> Tuple[bool, int]:
        """
        Check if user has exceeded rate limit.

        Args:
            user_id: The user's UUID
            max_requests: Maximum number of requests allowed in the time window
            window_seconds: Time window in seconds (default: 3600 = 1 hour)

        Returns:
            Tuple of (is_allowed, retry_after_seconds)
            - is_allowed: True if request is allowed, False if rate limit exceeded
            - retry_after_seconds: 0 if allowed, otherwise seconds until rate limit resets
        """
        now = datetime.utcnow()
        cutoff_time = now - timedelta(seconds=window_seconds)

        # Clean up old entries
        if user_id in self._requests:
            self._requests[user_id] = [
                (ts, count) for ts, count in self._requests[user_id]
                if ts > cutoff_time
            ]

        # Count requests in current window
        total_requests = sum(count for _, count in self._requests[user_id])

        if total_requests >= max_requests:
            # Calculate retry_after - time until oldest request expires
            if self._requests[user_id]:
                oldest_timestamp = self._requests[user_id][0][0]
                retry_after = int((oldest_timestamp + timedelta(seconds=window_seconds) - now).total_seconds())
                return False, max(retry_after, 0)
            return False, window_seconds

        return True, 0

    def record_request(self, user_id: uuid.UUID) -> None:
        """
        Record a request for the user.

        Args:
            user_id: The user's UUID
        """
        now = datetime.utcnow()

        # Add new request timestamp
        # We store each request individually for accurate tracking
        self._requests[user_id].append((now, 1))

    def reset_user_limit(self, user_id: uuid.UUID) -> None:
        """
        Reset rate limit for a specific user (admin function).

        Args:
            user_id: The user's UUID
        """
        if user_id in self._requests:
            del self._requests[user_id]

    def cleanup_old_entries(self, max_age_seconds: int = 7200) -> int:
        """
        Clean up old entries to prevent memory bloat.
        Should be called periodically (e.g., via background task).

        Args:
            max_age_seconds: Maximum age of entries to keep (default: 2 hours)

        Returns:
            Number of users cleaned up
        """
        now = datetime.utcnow()
        cutoff_time = now - timedelta(seconds=max_age_seconds)

        users_to_remove = []

        for user_id, requests in self._requests.items():
            # Filter out old requests
            filtered_requests = [(ts, count) for ts, count in requests if ts > cutoff_time]

            if not filtered_requests:
                users_to_remove.append(user_id)
            else:
                self._requests[user_id] = filtered_requests

        # Remove users with no recent requests
        for user_id in users_to_remove:
            del self._requests[user_id]

        return len(users_to_remove)


# Singleton instance
rate_limit_service = RateLimitService()
