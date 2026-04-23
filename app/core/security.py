import base64
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
import hashlib

# Configure bcrypt
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)


def _prepare_password(password: str) -> str:
    """Pre-hash password with SHA-256 to bypass bcrypt's 72-byte limit deterministically."""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")  # always 44 chars


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash using SHA-256 pre-hashing."""
    return pwd_context.verify(_prepare_password(plain_password), hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password with bcrypt using SHA-256 pre-hashing."""
    return pwd_context.hash(_prepare_password(password))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(seconds=settings.access_token_expires)

    to_encode.update({"exp": expire, "iat": now, "type": "access"})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm="HS256")


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT refresh token"""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(seconds=settings.refresh_token_expires)

    to_encode.update({"exp": expire, "iat": now, "type": "refresh"})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm="HS256")


def _get_token_hash(token: str) -> str:
    """SHA-256 hash of the token string for use as Redis key."""
    return hashlib.sha256(token.encode()).hexdigest()


def _get_remaining_ttl(token: str) -> int:
    """Return seconds remaining until token expiry (minimum 1)."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            options={"verify_exp": False},
        )
        exp = payload.get("exp")
        if exp is None:
            return 1
        remaining = int(exp - datetime.now(timezone.utc).timestamp())
        return max(remaining, 1)
    except JWTError:
        return 1


async def blacklist_token(token: str) -> None:
    """Add token to Redis blacklist with TTL equal to its remaining lifetime."""
    from app.core.cache import get_redis
    token_hash = _get_token_hash(token)
    ttl = _get_remaining_ttl(token)
    r = await get_redis()
    await r.setex(f"blacklist:{token_hash}", ttl, "1")


async def is_token_blacklisted(token: str) -> bool:
    """Return True if the token has been blacklisted in Redis."""
    from app.core.cache import get_redis
    token_hash = _get_token_hash(token)
    r = await get_redis()
    return await r.exists(f"blacklist:{token_hash}") > 0


async def invalidate_user_tokens(user_id: str) -> None:
    """Record a timestamp so all tokens issued before now are considered invalid.

    Called on password reset.  The key expires after 7 days (the maximum
    refresh token lifetime) so the check naturally becomes a no-op once all
    old tokens have expired anyway.
    """
    from app.core.cache import get_redis
    r = await get_redis()
    now_ts = int(datetime.now(timezone.utc).timestamp())
    await r.setex(f"tokens_invalid_before:{user_id}", settings.refresh_token_expires, str(now_ts))


async def verify_token(token: str, token_type: str = "access") -> Optional[str]:
    """Verify JWT token and return subject (user_id) if valid."""
    try:
        if await is_token_blacklisted(token):
            return None

        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id: str = payload.get("sub")
        token_type_payload: str = payload.get("type")

        if user_id is None or token_type_payload != token_type:
            return None

        # Check per-user invalidation timestamp (set on password reset)
        from app.core.cache import get_redis
        r = await get_redis()
        invalid_before_raw = await r.get(f"tokens_invalid_before:{user_id}")
        if invalid_before_raw:
            invalid_before = int(invalid_before_raw)
            iat = payload.get("iat")
            # Tokens without iat or issued before the invalidation point are rejected
            if iat is None or iat < invalid_before:
                return None

        return user_id
    except JWTError:
        return None


def get_token_expiration(token: str) -> Optional[datetime]:
    """Get token expiration time (does not check blacklist)."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        exp = payload.get("exp")
        if exp:
            return datetime.fromtimestamp(exp, tz=timezone.utc)
        return None
    except JWTError:
        return None


def is_token_expired(token: str) -> bool:
    """Check if token is expired (does not check blacklist)."""
    exp_time = get_token_expiration(token)
    if exp_time is None:
        return True
    return datetime.now(timezone.utc) > exp_time


async def decode_token(token: str) -> Optional[dict]:
    """Decode JWT token and return payload if valid and not blacklisted."""
    try:
        if await is_token_blacklisted(token):
            return None
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload
    except JWTError:
        return None


def get_device_id_from_token(token: str) -> Optional[str]:
    """Extract device_id ('did' claim) from a JWT token without validating expiry."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            options={"verify_exp": False},
        )
        return payload.get("did")
    except JWTError:
        return None


def get_token_expires_at(token: str) -> int:
    """Return the 'exp' claim of a token as a Unix timestamp, or 0 on error."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            options={"verify_exp": False},
        )
        return int(payload.get("exp", 0))
    except JWTError:
        return 0


async def store_device_session(
    user_id: str,
    device_id: str,
    token_hash: str,
    expires_at: int,
    device_name: str = "Unknown Device",
    platform: str = "unknown",
) -> None:
    """Store a new device session in Redis.

    Keys used:
    - session:{user_id}:{device_id}  ->  hash with session metadata
    - user_sessions:{user_id}        ->  sorted set: device_id -> expires_at (score)
    """
    from app.core.cache import get_redis
    r = await get_redis()

    now = int(datetime.now(timezone.utc).timestamp())
    ttl = max(expires_at - now, 1)

    session_key = f"session:{user_id}:{device_id}"
    sessions_key = f"user_sessions:{user_id}"

    await r.hset(session_key, mapping={
        "token_hash": token_hash,
        "device_name": device_name,
        "platform": platform,
        "created_at": str(now),
        "expires_at": str(expires_at),
    })
    await r.expire(session_key, ttl)
    await r.zadd(sessions_key, {device_id: expires_at})
    # Keep the index alive slightly beyond the longest possible token
    await r.expire(sessions_key, settings.refresh_token_expires + 86400)


async def update_device_session(
    user_id: str,
    device_id: str,
    new_token_hash: str,
    expires_at: int,
) -> None:
    """Update the token hash for an existing device session (called on token rotation)."""
    from app.core.cache import get_redis
    r = await get_redis()

    now = int(datetime.now(timezone.utc).timestamp())
    ttl = max(expires_at - now, 1)

    session_key = f"session:{user_id}:{device_id}"
    await r.hset(session_key, "token_hash", new_token_hash)
    await r.hset(session_key, "expires_at", str(expires_at))
    await r.expire(session_key, ttl)
    await r.zadd(f"user_sessions:{user_id}", {device_id: expires_at})


async def revoke_device_session(user_id: str, device_id: str) -> bool:
    """Revoke a specific device session. Returns True if the session existed."""
    from app.core.cache import get_redis
    r = await get_redis()

    session_key = f"session:{user_id}:{device_id}"
    session_data = await r.hgetall(session_key)

    if not session_data:
        return False

    def _decode(v) -> str:
        return v.decode() if isinstance(v, bytes) else str(v)

    token_hash = _decode(session_data.get(b"token_hash") or session_data.get("token_hash", ""))
    expires_at_raw = session_data.get(b"expires_at") or session_data.get("expires_at", 0)
    expires_at = int(_decode(expires_at_raw))

    now = int(datetime.now(timezone.utc).timestamp())
    remaining_ttl = max(expires_at - now, 1)

    await r.setex(f"blacklist:{token_hash}", remaining_ttl, "1")
    await r.delete(session_key)
    await r.zrem(f"user_sessions:{user_id}", device_id)

    return True


async def revoke_all_user_sessions(user_id: str) -> int:
    """Revoke all active sessions for a user. Returns the number of sessions revoked."""
    from app.core.cache import get_redis
    r = await get_redis()

    sessions_key = f"user_sessions:{user_id}"
    device_ids_raw = await r.zrange(sessions_key, 0, -1)

    def _decode(v) -> str:
        return v.decode() if isinstance(v, bytes) else str(v)

    now = int(datetime.now(timezone.utc).timestamp())
    count = 0

    for device_id_raw in device_ids_raw:
        device_id = _decode(device_id_raw)
        session_key = f"session:{user_id}:{device_id}"
        session_data = await r.hgetall(session_key)

        if session_data:
            token_hash = _decode(session_data.get(b"token_hash") or session_data.get("token_hash", ""))
            expires_at_raw = session_data.get(b"expires_at") or session_data.get("expires_at", 0)
            expires_at = int(_decode(expires_at_raw))
            remaining_ttl = max(expires_at - now, 1)

            if token_hash:
                await r.setex(f"blacklist:{token_hash}", remaining_ttl, "1")

        await r.delete(session_key)
        count += 1

    await r.delete(sessions_key)
    # Timestamp-based bulk invalidation as a safety net
    await invalidate_user_tokens(user_id)

    return count


async def get_user_sessions(user_id: str) -> list:
    """Return all active (non-expired) device sessions for a user."""
    from app.core.cache import get_redis
    r = await get_redis()

    sessions_key = f"user_sessions:{user_id}"
    now = int(datetime.now(timezone.utc).timestamp())

    # Lazily remove expired entries from the sorted set
    await r.zremrangebyscore(sessions_key, "-inf", now)

    device_ids_raw = await r.zrange(sessions_key, 0, -1)

    def _decode(v) -> str:
        return v.decode() if isinstance(v, bytes) else str(v)

    sessions = []
    for device_id_raw in device_ids_raw:
        device_id = _decode(device_id_raw)
        session_key = f"session:{user_id}:{device_id}"
        session_data = await r.hgetall(session_key)

        if not session_data:
            continue

        decoded = {
            (_decode(k)): _decode(v)
            for k, v in session_data.items()
        }

        sessions.append({
            "device_id": device_id,
            "device_name": decoded.get("device_name", "Unknown Device"),
            "platform": decoded.get("platform", "unknown"),
            "created_at": int(decoded.get("created_at", 0)),
            "expires_at": int(decoded.get("expires_at", 0)),
        })

    return sessions
