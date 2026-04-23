"""
Integration tests for the WorkOS AuthKit callback endpoint.

Covers:
  POST /api/v1/auth/workos/callback

All tests mock app.services.workos_service.get_user_from_code via monkeypatch
so no real WorkOS credentials or network calls are required.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.company import Company
from app.models.user import User, UserRole
from app.services.workos_service import WorkOSEmailVerificationRequired, WorkOSUser

# ---------------------------------------------------------------------------
# Default WorkOS user returned by the mock for most test cases
# ---------------------------------------------------------------------------
_DEFAULT_WORKOS_USER = WorkOSUser(
    id="workos_user_01ABC",
    email="social@example.com",
    email_verified=True,
    first_name="Social",
    last_name="User",
    profile_picture_url=None,
)

_CALLBACK_URL = "/api/v1/auth/workos/callback"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_get_user(monkeypatch, return_value) -> None:
    """Patch get_user_from_code to return *return_value* (coroutine-safe)."""
    import app.api.v1.auth.endpoints as auth_ep

    async def _fake(code: str):
        return return_value

    monkeypatch.setattr(auth_ep, "get_user_from_code", _fake)


def _decode_jwt(token: str) -> dict:
    """Decode a JWT without verifying expiry for assertion purposes."""
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        options={"verify_exp": False},
    )


# ---------------------------------------------------------------------------
# Test group
# ---------------------------------------------------------------------------
class TestWorkOSCallback:

    # -----------------------------------------------------------------------
    # 1. New job-seeker created on first social login
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_new_job_seeker_created(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch,
    ):
        """A brand-new WorkOS user results in a new User row and is_new_user=True."""
        _mock_get_user(monkeypatch, _DEFAULT_WORKOS_USER)

        response = await async_client.post(
            _CALLBACK_URL,
            json={"code": "valid_code", "role": "job_seeker"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["is_new_user"] is True

        # Confirm the DB row was created with the right attributes
        result = await db_session.execute(
            select(User).where(User.external_id == "workos_user_01ABC")
        )
        db_user = result.scalar_one_or_none()
        assert db_user is not None
        assert db_user.auth_provider == "workos"
        assert db_user.email == "social@example.com"
        assert db_user.email_verified is True
        assert db_user.role == UserRole.JOB_SEEKER

    # -----------------------------------------------------------------------
    # 2. Existing local account is linked to the WorkOS identity
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_existing_email_user_linked(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch,
    ):
        """A local (password) account with the same email is linked, not duplicated."""
        _mock_get_user(monkeypatch, _DEFAULT_WORKOS_USER)

        # Pre-create a local account with the same email
        local_user = User(
            id=uuid.uuid4(),
            email="social@example.com",
            password_hash=get_password_hash("Password1"),
            full_name="Local User",
            role=UserRole.JOB_SEEKER,
            auth_provider="local",
        )
        db_session.add(local_user)
        await db_session.flush()
        original_id = local_user.id

        response = await async_client.post(
            _CALLBACK_URL,
            json={"code": "valid_code", "role": "job_seeker"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data

        # The existing row should be updated, not a new one created
        result = await db_session.execute(
            select(User).where(User.email == "social@example.com")
        )
        users = result.scalars().all()
        assert len(users) == 1, "No duplicate user should be created"
        linked = users[0]
        assert linked.id == original_id
        assert linked.external_id == "workos_user_01ABC"
        assert linked.auth_provider == "workos"

    # -----------------------------------------------------------------------
    # 3. Returning WorkOS user gets a valid token for the existing account
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_existing_workos_user_returns_token(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch,
    ):
        """A user who already has external_id set gets a token whose sub matches their DB id."""
        _mock_get_user(monkeypatch, _DEFAULT_WORKOS_USER)

        existing = User(
            id=uuid.uuid4(),
            email="social@example.com",
            password_hash=None,
            full_name="Social User",
            role=UserRole.JOB_SEEKER,
            auth_provider="workos",
            external_id="workos_user_01ABC",
            email_verified=True,
        )
        db_session.add(existing)
        await db_session.flush()

        response = await async_client.post(
            _CALLBACK_URL,
            json={"code": "valid_code", "role": "job_seeker"},
        )

        assert response.status_code == 200
        data = response.json()
        payload = _decode_jwt(data["access_token"])
        assert payload["sub"] == str(existing.id)

    # -----------------------------------------------------------------------
    # 4. company_admin role without company_name returns 400
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_company_admin_requires_company_name(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch,
    ):
        """Registering as company_admin without company_name must return 400."""
        admin_user = WorkOSUser(
            id="workos_user_ADMIN01",
            email="admin@newcorp.com",
            email_verified=True,
            first_name="Corp",
            last_name="Admin",
            profile_picture_url=None,
        )
        _mock_get_user(monkeypatch, admin_user)

        response = await async_client.post(
            _CALLBACK_URL,
            json={"code": "x", "role": "company_admin"},
        )

        assert response.status_code == 400
        assert "company_name" in response.json()["detail"].lower()

    # -----------------------------------------------------------------------
    # 5. company_admin with company_name creates the Company row
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_company_admin_creates_company(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch,
    ):
        """Registering as company_admin with a company_name creates the Company in the DB."""
        admin_user = WorkOSUser(
            id="workos_user_ADMIN02",
            email="founder@acme.com",
            email_verified=True,
            first_name="Founder",
            last_name="One",
            profile_picture_url=None,
        )
        _mock_get_user(monkeypatch, admin_user)

        response = await async_client.post(
            _CALLBACK_URL,
            json={"code": "x", "role": "company_admin", "company_name": "Acme Corp"},
        )

        assert response.status_code == 200

        result = await db_session.execute(
            select(Company).where(Company.name == "Acme Corp")
        )
        company = result.scalar_one_or_none()
        assert company is not None

    # -----------------------------------------------------------------------
    # 6. Job-seeker app rejects existing company-admin accounts
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_jobseeker_app_rejects_company_user(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch,
    ):
        """X-Client-App: jobseeker header causes 401 when the user is a COMPANY_ADMIN."""
        _mock_get_user(monkeypatch, _DEFAULT_WORKOS_USER)

        company_admin = User(
            id=uuid.uuid4(),
            email="social@example.com",
            password_hash=None,
            full_name="Social User",
            role=UserRole.COMPANY_ADMIN,
            auth_provider="workos",
            external_id="workos_user_01ABC",
            email_verified=True,
        )
        db_session.add(company_admin)
        await db_session.flush()

        response = await async_client.post(
            _CALLBACK_URL,
            json={"code": "valid_code", "role": "company_admin"},
            headers={"X-Client-App": "jobseeker"},
        )

        assert response.status_code == 401

    # -----------------------------------------------------------------------
    # 7. email-verification-required returns 202 with the right shape
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_email_verification_required_returns_202(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch,
    ):
        """When WorkOS requires email verification, the endpoint returns HTTP 202."""
        pending = WorkOSEmailVerificationRequired(
            email="x@y.com",
            email_verification_id="evid_01",
            pending_authentication_token="pat_01",
        )
        _mock_get_user(monkeypatch, pending)

        response = await async_client.post(
            _CALLBACK_URL,
            json={"code": "code_needing_verify", "role": "job_seeker"},
        )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "email_verification_required"
        assert data["pending_authentication_token"] == "pat_01"
        assert "email_verification_id" in data
