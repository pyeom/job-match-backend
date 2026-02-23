"""
factory-boy factories for all major ORM models.

Usage example (inside an async test with db_session fixture):

    company = await CompanyFactory.create_async(db_session)
    user = await UserFactory.create_async(db_session, company_id=company.id)
    job = await JobFactory.create_async(db_session, company_id=company.id)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.security import get_password_hash
from app.models.application import Application
from app.models.company import Company
from app.models.job import Job
from app.models.swipe import Swipe
from app.models.user import User, UserRole

# ---------------------------------------------------------------------------
# Shared zero embedding (matches the mock embedding service in conftest.py)
# ---------------------------------------------------------------------------
ZERO_EMBEDDING: list[float] = [0.0] * 384


# ---------------------------------------------------------------------------
# Base async factory helper
# ---------------------------------------------------------------------------
class _AsyncFactory:
    """Minimal async factory helper.

    Subclasses declare ``_model`` (the ORM class) and override ``_defaults()``
    to supply default column values.  Call ``create_async(session, **kwargs)``
    to insert a row and return the flushed instance.
    """

    _model: type

    @classmethod
    def _defaults(cls) -> dict[str, Any]:
        return {}

    @classmethod
    async def create_async(cls, session, **kwargs) -> Any:
        """Create and flush an ORM instance within the given session."""
        data = {**cls._defaults(), **kwargs}
        instance = cls._model(**data)
        session.add(instance)
        await session.flush()
        return instance

    @classmethod
    def build(cls, **kwargs) -> Any:
        """Build an unsaved ORM instance (no DB interaction)."""
        data = {**cls._defaults(), **kwargs}
        return cls._model(**data)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------
class CompanyFactory(_AsyncFactory):
    _model = Company

    @classmethod
    def _defaults(cls) -> dict[str, Any]:
        suffix = uuid.uuid4().hex[:8]
        return {
            "id": uuid.uuid4(),
            "name": f"Company {suffix}",
            "description": "A test company",
            "website": "https://example.com",
            "industry": "Software",
            "size": "11-50",
            "location": "San Francisco, CA",
            "is_verified": False,
            "is_active": True,
        }


class UserFactory(_AsyncFactory):
    _model = User

    @classmethod
    def _defaults(cls) -> dict[str, Any]:
        suffix = uuid.uuid4().hex[:8]
        return {
            "id": uuid.uuid4(),
            "email": f"user_{suffix}@example.com",
            "password_hash": get_password_hash("Password1"),
            "full_name": f"Test User {suffix}",
            "role": UserRole.JOB_SEEKER,
            "company_id": None,
            "skills": ["python", "fastapi"],
            "seniority": "mid",
            "preferred_locations": ["remote", "san francisco"],
            "profile_embedding": ZERO_EMBEDDING,
        }


class CompanyAdminFactory(_AsyncFactory):
    """Factory for COMPANY_ADMIN users; requires a company_id kwarg."""

    _model = User

    @classmethod
    def _defaults(cls) -> dict[str, Any]:
        suffix = uuid.uuid4().hex[:8]
        return {
            "id": uuid.uuid4(),
            "email": f"admin_{suffix}@company.com",
            "password_hash": get_password_hash("Password1"),
            "full_name": f"Company Admin {suffix}",
            "role": UserRole.COMPANY_ADMIN,
            "company_id": None,  # caller must supply this
            "skills": [],
            "seniority": None,
            "preferred_locations": [],
            "profile_embedding": ZERO_EMBEDDING,
        }


class JobFactory(_AsyncFactory):
    _model = Job

    @classmethod
    def _defaults(cls) -> dict[str, Any]:
        suffix = uuid.uuid4().hex[:8]
        return {
            "id": uuid.uuid4(),
            "title": f"Software Engineer {suffix}",
            "company_id": None,  # caller must supply
            "location": "San Francisco, CA",
            "short_description": "Build great software",
            "description": "Full job description goes here.",
            "tags": ["python", "fastapi", "postgresql"],
            "seniority": "mid",
            "salary_min": 80_000,
            "salary_max": 120_000,
            "currency": "USD",
            "salary_negotiable": False,
            "remote": False,
            "work_arrangement": "Hybrid",
            "job_type": "Full-time",
            "is_active": True,
            "job_embedding": ZERO_EMBEDDING,
            "created_at": datetime.now(timezone.utc),
        }


class SwipeFactory(_AsyncFactory):
    _model = Swipe

    @classmethod
    def _defaults(cls) -> dict[str, Any]:
        return {
            "id": uuid.uuid4(),
            "user_id": None,  # caller must supply
            "job_id": None,  # caller must supply
            "direction": "LEFT",
            "is_undone": False,
            "undone_at": None,
            "created_at": datetime.now(timezone.utc),
        }


class ApplicationFactory(_AsyncFactory):
    _model = Application

    @classmethod
    def _defaults(cls) -> dict[str, Any]:
        return {
            "id": uuid.uuid4(),
            "user_id": None,  # caller must supply
            "job_id": None,  # caller must supply
            "stage": "SUBMITTED",
            "status": "ACTIVE",
            "stage_history": [],
            "score": 75,
        }
