from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
import hashlib

# Configure bcrypt - we handle 72-byte limit manually in get_password_hash()
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash"""
    # Truncate password to 72 bytes if needed (bcrypt limitation)
    if len(plain_password.encode('utf-8')) > 72:
        plain_password = plain_password.encode('utf-8')[:72].decode('utf-8', errors='ignore')
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password with bcrypt (truncates to 72 bytes as required)"""
    # Bcrypt has a hard limit of 72 bytes. Truncate before hashing.
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        password = password_bytes[:72].decode('utf-8', errors='ignore')
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(seconds=settings.access_token_expires)

    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm="HS256")


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT refresh token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(seconds=settings.refresh_token_expires)

    to_encode.update({"exp": expire, "type": "refresh"})
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
        remaining = int(exp - datetime.utcnow().timestamp())
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
        return user_id
    except JWTError:
        return None


def get_token_expiration(token: str) -> Optional[datetime]:
    """Get token expiration time (does not check blacklist)."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        exp = payload.get("exp")
        if exp:
            return datetime.fromtimestamp(exp)
        return None
    except JWTError:
        return None


def is_token_expired(token: str) -> bool:
    """Check if token is expired (does not check blacklist)."""
    exp_time = get_token_expiration(token)
    if exp_time is None:
        return True
    return datetime.utcnow() > exp_time


async def decode_token(token: str) -> Optional[dict]:
    """Decode JWT token and return payload if valid and not blacklisted."""
    try:
        if await is_token_blacklisted(token):
            return None
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload
    except JWTError:
        return None
