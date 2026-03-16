"""Auth-related background tasks."""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def cleanup_expired_sessions(ctx: dict) -> dict:
    """Scan all user session sorted sets and remove expired entries.

    Redis TTLs on individual session hashes (session:{user_id}:{device_id})
    handle automatic data expiry.  This task cleans up the index sorted sets
    (user_sessions:{user_id}) so they don't accumulate stale members.
    """
    from app.core.cache import get_redis

    r = await get_redis()
    now = int(datetime.now(timezone.utc).timestamp())

    cursor = 0
    total_cleaned = 0

    while True:
        cursor, keys = await r.scan(cursor, match="user_sessions:*", count=100)
        for key in keys:
            removed = await r.zremrangebyscore(key, "-inf", now)
            total_cleaned += removed
        if cursor == 0:
            break

    logger.info("cleanup_expired_sessions: removed %d stale session index entries", total_cleaned)
    return {"cleaned_count": total_cleaned}
