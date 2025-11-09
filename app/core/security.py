from datetime import datetime, timedelta
from typing import Optional, Union, Set
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import settings
import hashlib
import threading
import os

# Configure bcrypt - we handle 72-byte limit manually in get_password_hash()
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

# In-memory token blacklist (use Redis in production)
_token_blacklist: Set[str] = set()
_blacklist_lock = threading.Lock()


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
        # Truncate to 72 bytes, ensuring we don't break UTF-8 encoding
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
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm="HS256")
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT refresh token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(seconds=settings.refresh_token_expires)
    
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm="HS256")
    return encoded_jwt


def _get_token_hash(token: str) -> str:
    """Generate a hash of the token for blacklist storage"""
    return hashlib.sha256(token.encode()).hexdigest()


def blacklist_token(token: str) -> None:
    """Add token to blacklist"""
    token_hash = _get_token_hash(token)
    with _blacklist_lock:
        _token_blacklist.add(token_hash)


def is_token_blacklisted(token: str) -> bool:
    """Check if token is blacklisted"""
    token_hash = _get_token_hash(token)
    with _blacklist_lock:
        return token_hash in _token_blacklist


def cleanup_expired_tokens() -> None:
    """Clean up expired tokens from blacklist (should be called periodically)"""
    # For in-memory implementation, we'll clean up tokens older than max refresh time
    # In production with Redis, use TTL instead
    pass


def verify_token(token: str, token_type: str = "access") -> Optional[str]:
    """Verify JWT token and return subject (user_id) if valid"""
    try:
        # Check if token is blacklisted first
        if is_token_blacklisted(token):
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
    """Get token expiration time"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        exp = payload.get("exp")
        if exp:
            return datetime.fromtimestamp(exp)
        return None
    except JWTError:
        return None


def is_token_expired(token: str) -> bool:
    """Check if token is expired"""
    exp_time = get_token_expiration(token)
    if exp_time is None:
        return True
    return datetime.utcnow() > exp_time


def decode_token(token: str) -> Optional[dict]:
    """Decode JWT token and return payload if valid"""
    try:
        if is_token_blacklisted(token):
            return None

        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload
    except JWTError:
        return None