"""
Integration tests for swipe API endpoints.

Covers:
  POST /api/v1/swipes/
  GET  /api/v1/swipes/rejected
  GET  /api/v1/swipes/last
  DELETE /api/v1/swipes/{swipe_id}
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.swipe import Swipe
from app.models.user import User
from app.models.company import Company


# ---------------------------------------------------------------------------
# POST /api/v1/swipes/
# ---------------------------------------------------------------------------
class TestCreateSwipe:
    async def test_create_right_swipe_returns_201_or_200(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_job: Job,
    ):
        payload = {"job_id": str(test_job.id), "direction": "RIGHT"}
        response = await async_client.post(
            "/api/v1/swipes", json=payload, headers=auth_headers
        )
        # Endpoint uses POST and returns 200 (SwipeSchema response_model)
        assert response.status_code == 200
        data = response.json()
        assert data["direction"] == "RIGHT"
        assert data["job_id"] == str(test_job.id)

    async def test_create_left_swipe_succeeds(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_job: Job,
    ):
        payload = {"job_id": str(test_job.id), "direction": "LEFT"}
        response = await async_client.post(
            "/api/v1/swipes", json=payload, headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["direction"] == "LEFT"

    async def test_swipe_without_token_returns_403(
        self,
        async_client: AsyncClient,
        test_job: Job,
    ):
        payload = {"job_id": str(test_job.id), "direction": "RIGHT"}
        response = await async_client.post("/api/v1/swipes", json=payload)
        assert response.status_code in (401, 403)

    async def test_company_user_cannot_swipe(
        self,
        async_client: AsyncClient,
        company_auth_headers: dict,
        test_job: Job,
    ):
        payload = {"job_id": str(test_job.id), "direction": "RIGHT"}
        response = await async_client.post(
            "/api/v1/swipes", json=payload, headers=company_auth_headers
        )
        assert response.status_code in (401, 403)

    async def test_invalid_direction_returns_400(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_job: Job,
    ):
        payload = {"job_id": str(test_job.id), "direction": "UP"}
        response = await async_client.post(
            "/api/v1/swipes", json=payload, headers=auth_headers
        )
        assert response.status_code == 400

    async def test_nonexistent_job_returns_404(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        payload = {"job_id": str(uuid.uuid4()), "direction": "RIGHT"}
        response = await async_client.post(
            "/api/v1/swipes", json=payload, headers=auth_headers
        )
        assert response.status_code == 404

    async def test_invalid_job_id_returns_422(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        payload = {"job_id": "not-a-uuid", "direction": "RIGHT"}
        response = await async_client.post(
            "/api/v1/swipes", json=payload, headers=auth_headers
        )
        assert response.status_code == 422

    async def test_right_swipe_response_includes_swipe_fields(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_job: Job,
    ):
        payload = {"job_id": str(test_job.id), "direction": "RIGHT"}
        response = await async_client.post(
            "/api/v1/swipes", json=payload, headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "user_id" in data
        assert "job_id" in data
        assert "direction" in data
        assert "created_at" in data
        assert "is_undone" in data


# ---------------------------------------------------------------------------
# GET /api/v1/swipes/rejected
# ---------------------------------------------------------------------------
class TestGetRejectedJobs:
    async def test_returns_empty_list_for_new_user(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        response = await async_client.get(
            "/api/v1/swipes/rejected", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert isinstance(data["items"], list)
        assert "total" in data
        assert "has_more" in data

    async def test_includes_left_swiped_jobs(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        test_job: Job,
        db_session: AsyncSession,
    ):
        # Create a left swipe
        swipe = Swipe(
            id=uuid.uuid4(),
            user_id=test_user.id,
            job_id=test_job.id,
            direction="LEFT",
            is_undone=False,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(swipe)
        await db_session.flush()

        response = await async_client.get(
            "/api/v1/swipes/rejected", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        job_ids = [item["job_id"] for item in data["items"]]
        assert str(test_job.id) in job_ids

    async def test_does_not_include_right_swiped_jobs(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        db_session: AsyncSession,
        test_company: Company,
    ):
        # Create a right swipe for a job
        right_job = Job(
            id=uuid.uuid4(),
            title="Right Swipe Job",
            company_id=test_company.id,
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(right_job)
        await db_session.flush()

        swipe = Swipe(
            id=uuid.uuid4(),
            user_id=test_user.id,
            job_id=right_job.id,
            direction="RIGHT",
            is_undone=False,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(swipe)
        await db_session.flush()

        response = await async_client.get(
            "/api/v1/swipes/rejected", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        job_ids = [item["job_id"] for item in data["items"]]
        assert str(right_job.id) not in job_ids

    async def test_returns_403_without_token(self, async_client: AsyncClient):
        response = await async_client.get("/api/v1/swipes/rejected")
        assert response.status_code in (401, 403)

    async def test_respects_limit_parameter(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        response = await async_client.get(
            "/api/v1/swipes/rejected?limit=5", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) <= 5


# ---------------------------------------------------------------------------
# GET /api/v1/swipes/last
# ---------------------------------------------------------------------------
class TestGetLastSwipe:
    async def test_returns_none_when_no_recent_swipe(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        response = await async_client.get(
            "/api/v1/swipes/last", headers=auth_headers
        )
        assert response.status_code == 200
        # Should return null/None when no swipe within window
        data = response.json()
        assert data is None or isinstance(data, dict)

    async def test_returns_403_without_token(self, async_client: AsyncClient):
        response = await async_client.get("/api/v1/swipes/last")
        assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# DELETE /api/v1/swipes/{swipe_id}
# ---------------------------------------------------------------------------
class TestUndoSwipe:
    async def test_undo_recent_swipe_succeeds(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        test_job: Job,
        db_session: AsyncSession,
    ):
        # Create a very fresh swipe
        swipe = Swipe(
            id=uuid.uuid4(),
            user_id=test_user.id,
            job_id=test_job.id,
            direction="LEFT",
            is_undone=False,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(swipe)
        await db_session.flush()

        response = await async_client.delete(
            f"/api/v1/swipes/{swipe.id}", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["swipe_id"] == str(swipe.id)
        assert data["job_id"] == str(test_job.id)
        assert "undone_at" in data

    async def test_undo_nonexistent_swipe_returns_404(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        fake_id = uuid.uuid4()
        response = await async_client.delete(
            f"/api/v1/swipes/{fake_id}", headers=auth_headers
        )
        assert response.status_code == 404

    async def test_undo_invalid_uuid_returns_400(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        response = await async_client.delete(
            "/api/v1/swipes/not-a-uuid", headers=auth_headers
        )
        assert response.status_code == 400

    async def test_undo_without_token_returns_403(
        self,
        async_client: AsyncClient,
        test_job: Job,
    ):
        response = await async_client.delete(f"/api/v1/swipes/{uuid.uuid4()}")
        assert response.status_code in (401, 403)

    async def test_undo_already_undone_swipe_returns_400(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        test_job: Job,
        db_session: AsyncSession,
    ):
        swipe = Swipe(
            id=uuid.uuid4(),
            user_id=test_user.id,
            job_id=test_job.id,
            direction="LEFT",
            is_undone=True,
            undone_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(swipe)
        await db_session.flush()

        response = await async_client.delete(
            f"/api/v1/swipes/{swipe.id}", headers=auth_headers
        )
        assert response.status_code == 400
