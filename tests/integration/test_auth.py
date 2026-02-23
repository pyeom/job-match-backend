"""
Integration tests for the authentication API endpoints.

Covers:
  POST /api/v1/auth/register
  POST /api/v1/auth/register-company
  POST /api/v1/auth/login
  POST /api/v1/auth/refresh
  POST /api/v1/auth/logout
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, create_refresh_token, get_password_hash
from app.models.company import Company
from app.models.user import User, UserRole


# ---------------------------------------------------------------------------
# POST /api/v1/auth/register
# ---------------------------------------------------------------------------
class TestRegister:
    async def test_valid_registration_returns_tokens(self, async_client: AsyncClient):
        payload = {
            "email": f"newuser_{uuid.uuid4().hex[:8]}@example.com",
            "password": "Password1",
            "full_name": "New User",
        }
        response = await async_client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_duplicate_email_returns_400(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        email = f"dup_{uuid.uuid4().hex[:8]}@example.com"
        # Pre-create user in DB
        existing = User(
            id=uuid.uuid4(),
            email=email,
            password_hash=get_password_hash("Password1"),
            full_name="Existing User",
            role=UserRole.JOB_SEEKER,
        )
        db_session.add(existing)
        await db_session.flush()

        response = await async_client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "Password1", "full_name": "Dup User"},
        )
        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()

    async def test_invalid_email_returns_422(self, async_client: AsyncClient):
        response = await async_client.post(
            "/api/v1/auth/register",
            json={"email": "not-an-email", "password": "pass", "full_name": "User"},
        )
        assert response.status_code == 422

    async def test_missing_full_name_returns_422(self, async_client: AsyncClient):
        response = await async_client.post(
            "/api/v1/auth/register",
            json={"email": "test@example.com", "password": "pass"},
        )
        assert response.status_code == 422

    async def test_empty_full_name_returns_422(self, async_client: AsyncClient):
        response = await async_client.post(
            "/api/v1/auth/register",
            json={"email": "test@example.com", "password": "pass", "full_name": ""},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/auth/register-company
# ---------------------------------------------------------------------------
class TestRegisterCompany:
    async def test_valid_company_registration_returns_tokens(
        self, async_client: AsyncClient
    ):
        suffix = uuid.uuid4().hex[:8]
        payload = {
            "email": f"admin_{suffix}@corp.com",
            "password": "Password1",
            "full_name": "Corp Admin",
            "role": "admin",
            "company_name": f"Corp {suffix}",
            "company_description": "A test company",
            "company_industry": "Software",
        }
        response = await async_client.post(
            "/api/v1/auth/register-company", json=payload
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_invalid_company_role_returns_422(self, async_client: AsyncClient):
        suffix = uuid.uuid4().hex[:8]
        payload = {
            "email": f"u_{suffix}@corp.com",
            "password": "pass",
            "full_name": "User",
            "role": "job_seeker",  # invalid for company registration
            "company_name": f"Corp {suffix}",
        }
        response = await async_client.post(
            "/api/v1/auth/register-company", json=payload
        )
        assert response.status_code == 422

    async def test_duplicate_email_for_company_returns_400(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        email = f"cadmin_{uuid.uuid4().hex[:8]}@corp.com"
        existing = User(
            id=uuid.uuid4(),
            email=email,
            password_hash=get_password_hash("Password1"),
            full_name="Existing Admin",
            role=UserRole.COMPANY_ADMIN,
        )
        db_session.add(existing)
        await db_session.flush()

        payload = {
            "email": email,
            "password": "Password1",
            "full_name": "New Admin",
            "role": "admin",
            "company_name": f"Co_{uuid.uuid4().hex[:8]}",
        }
        response = await async_client.post(
            "/api/v1/auth/register-company", json=payload
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login
# ---------------------------------------------------------------------------
class TestLogin:
    async def test_valid_login_returns_tokens(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        email = f"login_{uuid.uuid4().hex[:8]}@example.com"
        raw_password = "Password1"
        user = User(
            id=uuid.uuid4(),
            email=email,
            password_hash=get_password_hash(raw_password),
            full_name="Login Test",
            role=UserRole.JOB_SEEKER,
        )
        db_session.add(user)
        await db_session.flush()

        response = await async_client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": raw_password},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    async def test_wrong_password_returns_401(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        email = f"badpass_{uuid.uuid4().hex[:8]}@example.com"
        user = User(
            id=uuid.uuid4(),
            email=email,
            password_hash=get_password_hash("CorrectPass1"),
            full_name="Bad Pass Test",
            role=UserRole.JOB_SEEKER,
        )
        db_session.add(user)
        await db_session.flush()

        response = await async_client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "WrongPass1"},
        )
        assert response.status_code == 401

    async def test_non_existent_email_returns_401(self, async_client: AsyncClient):
        response = await async_client.post(
            "/api/v1/auth/login",
            json={"email": "ghost@nowhere.com", "password": "Password1"},
        )
        assert response.status_code == 401

    async def test_invalid_email_format_returns_422(self, async_client: AsyncClient):
        response = await async_client.post(
            "/api/v1/auth/login",
            json={"email": "not-an-email", "password": "pass"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/auth/refresh
# ---------------------------------------------------------------------------
class TestRefreshToken:
    async def test_valid_refresh_returns_new_tokens(
        self,
        async_client: AsyncClient,
        test_user: User,
    ):
        refresh_token = create_refresh_token(data={"sub": str(test_user.id)})
        response = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert "expires_in" in data

    async def test_invalid_token_returns_401(self, async_client: AsyncClient):
        response = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "this.is.not.valid"},
        )
        assert response.status_code == 401

    async def test_access_token_used_as_refresh_returns_401(
        self,
        async_client: AsyncClient,
        test_user: User,
    ):
        # access tokens have type="access", not "refresh"
        access_token = create_access_token(data={"sub": str(test_user.id)})
        response = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": access_token},
        )
        assert response.status_code == 401

    async def test_missing_refresh_token_returns_422(self, async_client: AsyncClient):
        response = await async_client.post("/api/v1/auth/refresh", json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/auth/logout
# ---------------------------------------------------------------------------
class TestLogout:
    async def test_logout_with_valid_token_returns_200(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        response = await async_client.post(
            "/api/v1/auth/logout", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "logged out" in data["message"].lower()

    async def test_logout_without_token_returns_401_or_403(self, async_client: AsyncClient):
        # HTTPBearer returns 403 (missing) in some FastAPI versions, 401 in others
        response = await async_client.post("/api/v1/auth/logout")
        assert response.status_code in (401, 403)

    async def test_logout_with_invalid_token_returns_401_or_403(
        self, async_client: AsyncClient
    ):
        response = await async_client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": "Bearer this.is.invalid"},
        )
        assert response.status_code in (401, 403)
