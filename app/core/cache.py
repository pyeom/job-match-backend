import json
import logging
import uuid
from datetime import datetime, date
from typing import Optional

from redis.asyncio import Redis, ConnectionPool

from app.core.config import settings

logger = logging.getLogger(__name__)

_pool: Optional[ConnectionPool] = None

USER_CACHE_TTL = 300       # 5 minutes
COMPANY_CACHE_TTL = 3600   # 1 hour


# ── Connection pool ───────────────────────────────────────────────────────────

async def get_redis_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            settings.redis_url,
            max_connections=settings.redis_pool_size,
            decode_responses=True,
        )
        logger.info("Redis connection pool created: %s", settings.redis_url)
    return _pool


async def get_redis() -> Redis:
    pool = await get_redis_pool()
    return Redis(connection_pool=pool)


async def close_redis_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
        logger.info("Redis connection pool closed")


# ── Serialization helpers ─────────────────────────────────────────────────────

def _serialize_company_model(company) -> dict:
    return {
        "id": str(company.id),
        "name": company.name,
        "description": company.description,
        "website": company.website,
        "logo_url": company.logo_url,
        "industry": company.industry,
        "size": company.size,
        "location": company.location,
        "founded_year": company.founded_year,
        "is_verified": bool(company.is_verified),
        "is_active": bool(company.is_active),
        "created_at": company.created_at.isoformat() if company.created_at else None,
        "updated_at": company.updated_at.isoformat() if company.updated_at else None,
    }


def _deserialize_company_model(data: dict):
    from app.models.company import Company
    company = Company()
    company.id = uuid.UUID(data["id"])
    company.name = data.get("name")
    company.description = data.get("description")
    company.website = data.get("website")
    company.logo_url = data.get("logo_url")
    company.industry = data.get("industry")
    company.size = data.get("size")
    company.location = data.get("location")
    company.founded_year = data.get("founded_year")
    company.is_verified = data.get("is_verified", False)
    company.is_active = data.get("is_active", True)
    ca = data.get("created_at")
    company.created_at = datetime.fromisoformat(ca) if ca else None
    ua = data.get("updated_at")
    company.updated_at = datetime.fromisoformat(ua) if ua else None
    return company


def _serialize_user_model(user) -> dict:
    # profile_embedding may be a numpy array or list; elements may be numpy.float32
    emb = user.profile_embedding
    if emb is not None:
        try:
            emb = [float(x) for x in emb]
        except TypeError:
            emb = None

    company_data = (
        _serialize_company_model(user.company) if user.company is not None else None
    )

    return {
        "id": str(user.id),
        "email": user.email,
        "password_hash": user.password_hash,
        "role": user.role.value if hasattr(user.role, "value") else user.role,
        "company_id": str(user.company_id) if user.company_id else None,
        "full_name": user.full_name,
        "headline": user.headline,
        "bio": user.bio,
        "skills": user.skills,
        "preferred_locations": user.preferred_locations,
        "seniority": user.seniority,
        "phone": user.phone,
        "experience": user.experience,
        "education": user.education,
        "avatar_url": user.avatar_url,
        "avatar_thumbnail_url": user.avatar_thumbnail_url,
        "profile_embedding": emb,
        "is_premium": bool(user.is_premium),
        "daily_undo_count": user.daily_undo_count or 0,
        "undo_count_reset_date": (
            user.undo_count_reset_date.isoformat()
            if user.undo_count_reset_date
            else None
        ),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "_company": company_data,
    }


def _deserialize_user_model(data: dict):
    from app.models.user import User, UserRole

    user = User()
    user.id = uuid.UUID(data["id"])
    user.email = data.get("email")
    user.password_hash = data.get("password_hash")
    user.role = UserRole(data["role"]) if data.get("role") else None
    user.company_id = uuid.UUID(data["company_id"]) if data.get("company_id") else None
    user.full_name = data.get("full_name")
    user.headline = data.get("headline")
    user.bio = data.get("bio")
    user.skills = data.get("skills")
    user.preferred_locations = data.get("preferred_locations")
    user.seniority = data.get("seniority")
    user.phone = data.get("phone")
    user.experience = data.get("experience")
    user.education = data.get("education")
    user.avatar_url = data.get("avatar_url")
    user.avatar_thumbnail_url = data.get("avatar_thumbnail_url")
    user.profile_embedding = data.get("profile_embedding")  # list of floats
    user.is_premium = data.get("is_premium", False)
    user.daily_undo_count = data.get("daily_undo_count", 0)

    rsd = data.get("undo_count_reset_date")
    user.undo_count_reset_date = date.fromisoformat(rsd) if rsd else None

    ca = data.get("created_at")
    user.created_at = datetime.fromisoformat(ca) if ca else None
    ua = data.get("updated_at")
    user.updated_at = datetime.fromisoformat(ua) if ua else None

    company_data = data.get("_company")
    user.company = _deserialize_company_model(company_data) if company_data else None

    return user


# ── User cache ────────────────────────────────────────────────────────────────

async def get_cached_user(user_id: str):
    """Return a deserialized User ORM instance from cache, or None on miss/error."""
    try:
        r = await get_redis()
        raw = await r.get(f"user:{user_id}")
        if raw:
            return _deserialize_user_model(json.loads(raw))
    except Exception:
        logger.warning("User cache read failed for %s", user_id, exc_info=True)
    return None


async def set_cached_user(user_id: str, user) -> None:
    """Serialize and store a User ORM instance in cache."""
    try:
        r = await get_redis()
        await r.setex(
            f"user:{user_id}",
            USER_CACHE_TTL,
            json.dumps(_serialize_user_model(user)),
        )
    except Exception:
        logger.warning("User cache write failed for %s", user_id, exc_info=True)


async def invalidate_user_cache(user_id: str) -> None:
    """Delete a user's cache entry."""
    try:
        r = await get_redis()
        await r.delete(f"user:{user_id}")
    except Exception:
        logger.warning("User cache invalidation failed for %s", user_id, exc_info=True)


# ── Company cache ─────────────────────────────────────────────────────────────

async def get_cached_company(company_id: str):
    """Return a deserialized Company ORM instance from cache, or None on miss/error."""
    try:
        r = await get_redis()
        raw = await r.get(f"company:public:{company_id}")
        if raw:
            return _deserialize_company_model(json.loads(raw))
    except Exception:
        logger.warning("Company cache read failed for %s", company_id, exc_info=True)
    return None


async def set_cached_company(company_id: str, company) -> None:
    """Serialize and store a Company ORM instance in cache."""
    try:
        r = await get_redis()
        await r.setex(
            f"company:public:{company_id}",
            COMPANY_CACHE_TTL,
            json.dumps(_serialize_company_model(company)),
        )
    except Exception:
        logger.warning("Company cache write failed for %s", company_id, exc_info=True)


async def invalidate_company_cache(company_id: str) -> None:
    """Delete a company's cache entry."""
    try:
        r = await get_redis()
        await r.delete(f"company:public:{company_id}")
    except Exception:
        logger.warning(
            "Company cache invalidation failed for %s", company_id, exc_info=True
        )
