"""
Integration tests for user profile API endpoints.

Covers:
  GET   /api/v1/users/{user_id}
  PATCH /api/v1/users/{user_id}
  POST  /api/v1/users/{user_id}/change-password
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.models.user import User, UserRole


# ---------------------------------------------------------------------------
# GET /api/v1/users/{user_id}
# ---------------------------------------------------------------------------
class TestGetUserProfile:
    async def test_returns_own_profile(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        response = await async_client.get(
            f"/api/v1/users/{test_user.id}", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(test_user.id)
        assert data["email"] == test_user.email

    async def test_returns_403_without_token(
        self,
        async_client: AsyncClient,
        test_user: User,
    ):
        response = await async_client.get(f"/api/v1/users/{test_user.id}")
        assert response.status_code in (401, 403)

    async def test_returns_403_for_other_users_profile(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        other_user = User(
            id=uuid.uuid4(),
            email=f"other_{uuid.uuid4().hex[:8]}@example.com",
            password_hash=get_password_hash("Password1"),
            full_name="Other User",
            role=UserRole.JOB_SEEKER,
        )
        db_session.add(other_user)
        await db_session.flush()

        response = await async_client.get(
            f"/api/v1/users/{other_user.id}", headers=auth_headers
        )
        assert response.status_code in (401, 403)

    async def test_returns_422_for_invalid_uuid(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        response = await async_client.get(
            "/api/v1/users/not-a-valid-uuid", headers=auth_headers
        )
        assert response.status_code == 422

    async def test_response_includes_expected_fields(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        response = await async_client.get(
            f"/api/v1/users/{test_user.id}", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        required_fields = ["id", "email", "full_name", "role", "created_at"]
        for field in required_fields:
            assert field in data

    async def test_password_hash_not_exposed(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        response = await async_client.get(
            f"/api/v1/users/{test_user.id}", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "password_hash" not in data
        assert "password" not in data

    async def test_user_type_computed_field_present(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        response = await async_client.get(
            f"/api/v1/users/{test_user.id}", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "user_type" in data
        assert data["user_type"] == "job_seeker"


# ---------------------------------------------------------------------------
# PATCH /api/v1/users/{user_id}
# ---------------------------------------------------------------------------
class TestUpdateUserProfile:
    async def test_update_headline_succeeds(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        response = await async_client.patch(
            f"/api/v1/users/{test_user.id}",
            headers=auth_headers,
            json={"headline": "Senior Python Developer"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["headline"] == "Senior Python Developer"

    async def test_update_skills_succeeds(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        response = await async_client.patch(
            f"/api/v1/users/{test_user.id}",
            headers=auth_headers,
            json={"skills": ["python", "fastapi", "postgresql", "docker"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert "python" in data["skills"]

    async def test_update_without_token_returns_403(
        self,
        async_client: AsyncClient,
        test_user: User,
    ):
        response = await async_client.patch(
            f"/api/v1/users/{test_user.id}",
            json={"headline": "New Headline"},
        )
        assert response.status_code in (401, 403)

    async def test_update_other_user_returns_403(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        other_user = User(
            id=uuid.uuid4(),
            email=f"other_{uuid.uuid4().hex[:8]}@example.com",
            password_hash=get_password_hash("Password1"),
            full_name="Other User",
            role=UserRole.JOB_SEEKER,
        )
        db_session.add(other_user)
        await db_session.flush()

        response = await async_client.patch(
            f"/api/v1/users/{other_user.id}",
            headers=auth_headers,
            json={"headline": "Hacked Headline"},
        )
        assert response.status_code in (401, 403)

    async def test_empty_full_name_returns_422(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        response = await async_client.patch(
            f"/api/v1/users/{test_user.id}",
            headers=auth_headers,
            json={"full_name": ""},
        )
        assert response.status_code == 422

    async def test_update_seniority_succeeds(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        response = await async_client.patch(
            f"/api/v1/users/{test_user.id}",
            headers=auth_headers,
            json={"seniority": "senior"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["seniority"] == "senior"

    async def test_partial_update_only_changes_specified_fields(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        original_email = test_user.email
        response = await async_client.patch(
            f"/api/v1/users/{test_user.id}",
            headers=auth_headers,
            json={"headline": "Just updating headline"},
        )
        assert response.status_code == 200
        data = response.json()
        # email should be unchanged
        assert data["email"] == original_email


# ---------------------------------------------------------------------------
# POST /api/v1/users/{user_id}/change-password
# ---------------------------------------------------------------------------
class TestChangePassword:
    async def test_valid_password_change_succeeds(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        from app.core.security import create_access_token

        # Create a fresh user with known password
        password = "OldPassword1"
        user = User(
            id=uuid.uuid4(),
            email=f"pwchange_{uuid.uuid4().hex[:8]}@example.com",
            password_hash=get_password_hash(password),
            full_name="PW Change User",
            role=UserRole.JOB_SEEKER,
        )
        db_session.add(user)
        await db_session.flush()

        token = create_access_token(data={"sub": str(user.id)})
        headers = {"Authorization": f"Bearer {token}"}

        response = await async_client.post(
            f"/api/v1/users/{user.id}/change-password",
            headers=headers,
            json={"current_password": password, "new_password": "NewPassword1"},
        )
        assert response.status_code == 200

    async def test_wrong_current_password_returns_401_or_400(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        response = await async_client.post(
            f"/api/v1/users/{test_user.id}/change-password",
            headers=auth_headers,
            json={
                "current_password": "WrongPassword1",
                "new_password": "NewPassword1",
            },
        )
        assert response.status_code in (400, 401)

    async def test_weak_new_password_returns_422(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        response = await async_client.post(
            f"/api/v1/users/{test_user.id}/change-password",
            headers=auth_headers,
            json={"current_password": "Password1", "new_password": "weak"},
        )
        assert response.status_code == 422

    async def test_without_token_returns_403(
        self,
        async_client: AsyncClient,
        test_user: User,
    ):
        response = await async_client.post(
            f"/api/v1/users/{test_user.id}/change-password",
            json={"current_password": "old", "new_password": "NewPassword1"},
        )
        assert response.status_code in (401, 403)
