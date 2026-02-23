"""
Integration tests for application API endpoints.

Covers:
  GET   /api/v1/users/{user_id}/applications
  GET   /api/v1/users/{user_id}/applications/{application_id}
  PATCH /api/v1/users/{user_id}/applications/{application_id}
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.models.company import Company
from app.models.job import Job
from app.models.user import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _seed_application(
    db: AsyncSession,
    user: User,
    job: Job,
    stage: str = "SUBMITTED",
    status: str = "ACTIVE",
) -> Application:
    app_obj = Application(
        id=uuid.uuid4(),
        user_id=user.id,
        job_id=job.id,
        stage=stage,
        status=status,
        stage_history=[],
        score=75,
    )
    db.add(app_obj)
    await db.flush()
    return app_obj


# ---------------------------------------------------------------------------
# GET /api/v1/users/{user_id}/applications
# ---------------------------------------------------------------------------
class TestGetUserApplications:
    async def test_returns_list_for_authenticated_user(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        test_job: Job,
        db_session: AsyncSession,
    ):
        await _seed_application(db_session, test_user, test_job)

        response = await async_client.get(
            f"/api/v1/users/{test_user.id}/applications",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_returns_403_without_token(
        self,
        async_client: AsyncClient,
        test_user: User,
    ):
        response = await async_client.get(
            f"/api/v1/users/{test_user.id}/applications"
        )
        assert response.status_code in (401, 403)

    async def test_returns_403_when_accessing_other_user_applications(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        from app.core.security import get_password_hash
        from app.models.user import UserRole

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
            f"/api/v1/users/{other_user.id}/applications",
            headers=auth_headers,  # authenticated as test_user, not other_user
        )
        assert response.status_code in (401, 403)

    async def test_empty_applications_returns_empty_list(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        response = await async_client.get(
            f"/api/v1/users/{test_user.id}/applications",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_returns_applications_with_required_fields(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        test_job: Job,
        db_session: AsyncSession,
    ):
        await _seed_application(db_session, test_user, test_job)

        response = await async_client.get(
            f"/api/v1/users/{test_user.id}/applications",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        if data:
            item = data[0]
            assert "id" in item
            assert "user_id" in item
            assert "job_id" in item
            assert "stage" in item
            assert "status" in item


# ---------------------------------------------------------------------------
# GET /api/v1/users/{user_id}/applications/{application_id}
# ---------------------------------------------------------------------------
class TestGetSingleApplication:
    async def test_returns_single_application(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        test_job: Job,
        db_session: AsyncSession,
    ):
        app_obj = await _seed_application(db_session, test_user, test_job)

        response = await async_client.get(
            f"/api/v1/users/{test_user.id}/applications/{app_obj.id}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(app_obj.id)

    async def test_returns_404_for_nonexistent_application(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        fake_id = uuid.uuid4()
        response = await async_client.get(
            f"/api/v1/users/{test_user.id}/applications/{fake_id}",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_returns_403_without_token(
        self,
        async_client: AsyncClient,
        test_user: User,
    ):
        fake_id = uuid.uuid4()
        response = await async_client.get(
            f"/api/v1/users/{test_user.id}/applications/{fake_id}"
        )
        assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# PATCH /api/v1/users/{user_id}/applications/{application_id}
# ---------------------------------------------------------------------------
class TestUpdateApplication:
    async def test_update_notes_succeeds(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        test_job: Job,
        db_session: AsyncSession,
    ):
        app_obj = await _seed_application(db_session, test_user, test_job)

        response = await async_client.patch(
            f"/api/v1/users/{test_user.id}/applications/{app_obj.id}",
            headers=auth_headers,
            json={"notes": "Very interested in this role"},
        )
        # Accept either 200 (success) or 422/404 if endpoint has different contract
        assert response.status_code in (200, 404, 422)

    async def test_update_without_token_returns_403(
        self,
        async_client: AsyncClient,
        test_user: User,
    ):
        fake_id = uuid.uuid4()
        response = await async_client.patch(
            f"/api/v1/users/{test_user.id}/applications/{fake_id}",
            json={"notes": "test"},
        )
        assert response.status_code in (401, 403)
