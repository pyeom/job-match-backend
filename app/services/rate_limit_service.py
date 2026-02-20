"""
Rate limiting service for API endpoints.

Uses Redis sorted sets (sliding window algorithm) for distributed, accurate
rate limiting. Falls back gracefully if Redis is unavailable.

Legacy in-memory helpers (check_rate_limit with user_id, record_request,
cleanup_old_entries) are retained for backward compatibility but are no-ops
when Redis is available.
"""
import logging
import time
import uuid
from typing import Tuple

logger = logging.getLogger(__name__)


class RateLimitService:
    """
    Rate limiting service backed by Redis sliding-window counters.

    The primary interface is the async ``check_rate_limit(key, max_requests,
    window_seconds)`` method which atomically records and evaluates the
    current request against a per-key sorted-set counter in Redis.

    Legacy synchronous methods (``record_request``, ``cleanup_old_entries``)
    are kept as no-ops so that existing callers (e.g. avatar upload) continue
    to import without errors while being migrated to the async interface.
    """

    # ── Redis sliding-window implementation ───────────────────────────────────

    async def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
        *,
        # Legacy keyword arguments accepted for backward compatibility.
        # If ``user_id`` is supplied instead of ``key`` (old call-site style)
        # the caller must migrate; this signature handles both styles via the
        # ``key`` positional parameter.
        user_id: uuid.UUID | None = None,
    ) -> Tuple[bool, int]:
        """
        Check whether the caller identified by *key* has exceeded the rate
        limit, and record the current request.

        Uses a Redis sorted-set sliding window:
        - Removes entries older than the window.
        - Inserts the current timestamp.
        - Counts remaining entries.
        - Sets a TTL so keys expire automatically.

        Args:
            key:            Unique rate-limit bucket identifier, e.g.
                            ``"login:ip:1.2.3.4"`` or ``"login:email:a@b.com"``.
            max_requests:   Maximum number of requests allowed inside
                            *window_seconds*.
            window_seconds: Length of the sliding window in seconds.

        Returns:
            Tuple of (is_allowed, retry_after_seconds).
            ``is_allowed`` is False when the limit is exceeded.
            ``retry_after_seconds`` is 0 when allowed, otherwise the number
            of seconds until the oldest request in the window expires.
        """
        # Support legacy callers that pass user_id as the first positional arg.
        # In that case ``key`` will actually be a UUID object.
        if isinstance(key, uuid.UUID) or user_id is not None:
            resolved_key = f"ratelimit:user:{user_id or key}"
        else:
            resolved_key = f"ratelimit:{key}"

        try:
            from app.core.cache import get_redis

            r = await get_redis()
            now = time.time()
            window_start = now - window_seconds

            pipe = r.pipeline()
            # Remove entries that have fallen outside the current window.
            pipe.zremrangebyscore(resolved_key, 0, window_start)
            # Record this request with the current timestamp as both member
            # and score (append a random suffix to avoid member collisions when
            # multiple requests arrive at the same fractional second).
            pipe.zadd(resolved_key, {f"{now}:{time.monotonic_ns()}": now})
            # Count entries remaining inside the window.
            pipe.zcard(resolved_key)
            # Ensure the key expires so Redis memory is not leaked.
            pipe.expire(resolved_key, window_seconds)
            results = await pipe.execute()

            count: int = results[2]

            if count > max_requests:
                # Find the oldest entry to compute the precise retry-after.
                oldest = await r.zrange(resolved_key, 0, 0, withscores=True)
                if oldest:
                    retry_after = int(window_seconds - (now - oldest[0][1]))
                    retry_after = max(retry_after, 1)
                else:
                    retry_after = window_seconds
                return False, retry_after

            return True, 0

        except Exception:
            # If Redis is unavailable, fail open rather than blocking all users.
            logger.warning(
                "Rate limit check failed for key '%s' — failing open",
                key,
                exc_info=True,
            )
            return True, 0

    # ── Legacy synchronous stubs (backward compatibility) ─────────────────────

    def record_request(self, user_id: uuid.UUID) -> None:
        """
        No-op stub retained for backward compatibility.

        The Redis implementation records each request atomically inside
        ``check_rate_limit``, so a separate ``record_request`` call is no
        longer needed. Existing call-sites that still invoke this method will
        continue to work without error.
        """

    def reset_user_limit(self, user_id: uuid.UUID) -> None:
        """
        No-op stub retained for backward compatibility.

        To reset a Redis-backed limit, delete the key directly via
        ``get_redis().delete(f"ratelimit:user:{user_id}")``.
        """

    def cleanup_old_entries(self, max_age_seconds: int = 7200) -> int:
        """
        No-op stub retained for backward compatibility.

        Redis keys have a TTL set by ``check_rate_limit`` and expire
        automatically, so no periodic cleanup is required.

        Returns:
            Always 0 (nothing cleaned up by this method).
        """
        return 0


# Singleton instance used throughout the application.
rate_limit_service = RateLimitService()
