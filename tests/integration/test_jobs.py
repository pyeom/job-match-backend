"""
Integration tests for job API endpoints.

Covers:
  GET /api/v1/jobs/discover
  GET /api/v1/jobs/{job_id}
  POST /api/v1/jobs/search
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.job import Job
from app.models.user import User


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/discover
# ---------------------------------------------------------------------------
class TestDiscoverJobs:
    async def test_returns_200_for_authenticated_user(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_job: Job,
    ):
        response = await async_client.get(
            "/api/v1/jobs/discover", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert isinstance(data["items"], list)

    async def test_returns_401_without_token(self, async_client: AsyncClient):
        response = await async_client.get("/api/v1/jobs/discover")
        assert response.status_code in (401, 403)

    async def test_company_user_cannot_access_discover(
        self,
        async_client: AsyncClient,
        company_auth_headers: dict,
    ):
        response = await async_client.get(
            "/api/v1/jobs/discover", headers=company_auth_headers
        )
        # Discover is restricted to job seekers only
        assert response.status_code in (401, 403)

    async def test_respects_limit_parameter(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_company: Company,
    ):
        from datetime import datetime, timezone

        # Create multiple jobs
        for i in range(5):
            job = Job(
                id=uuid.uuid4(),
                title=f"Test Job {i}",
                company_id=test_company.id,
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
            db_session.add(job)
        await db_session.flush()

        response = await async_client.get(
            "/api/v1/jobs/discover?limit=2", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) <= 2

    async def test_invalid_limit_returns_422(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        response = await async_client.get(
            "/api/v1/jobs/discover?limit=0", headers=auth_headers
        )
        assert response.status_code == 422

    async def test_limit_too_large_returns_422(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        response = await async_client.get(
            "/api/v1/jobs/discover?limit=100", headers=auth_headers
        )
        assert response.status_code == 422

    async def test_returns_job_fields(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_job: Job,
    ):
        response = await async_client.get(
            "/api/v1/jobs/discover", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        if data["items"]:
            item = data["items"][0]
            assert "id" in item
            assert "title" in item
            assert "company_id" in item

    async def test_pagination_cursor_in_response(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_company: Company,
    ):
        from datetime import datetime, timezone

        # Create more jobs than the page limit
        for i in range(25):
            job = Job(
                id=uuid.uuid4(),
                title=f"Paginated Job {i}",
                company_id=test_company.id,
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
            db_session.add(job)
        await db_session.flush()

        response = await async_client.get(
            "/api/v1/jobs/discover?limit=5", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        # May or may not have next_cursor depending on ES mock returning empty
        assert "next_cursor" in data


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{job_id}
# ---------------------------------------------------------------------------
class TestGetJob:
    async def test_returns_job_details(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_job: Job,
    ):
        response = await async_client.get(
            f"/api/v1/jobs/{test_job.id}", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(test_job.id)
        assert data["title"] == test_job.title

    async def test_returns_404_for_nonexistent_job(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        fake_id = uuid.uuid4()
        response = await async_client.get(
            f"/api/v1/jobs/{fake_id}", headers=auth_headers
        )
        assert response.status_code == 404

    async def test_returns_403_without_auth(
        self,
        async_client: AsyncClient,
        test_job: Job,
    ):
        response = await async_client.get(f"/api/v1/jobs/{test_job.id}")
        assert response.status_code in (401, 403)

    async def test_returns_422_for_invalid_uuid(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        response = await async_client.get(
            "/api/v1/jobs/not-a-valid-uuid", headers=auth_headers
        )
        assert response.status_code == 422

    async def test_inactive_job_returns_404(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        test_company: Company,
    ):
        from datetime import datetime, timezone

        inactive_job = Job(
            id=uuid.uuid4(),
            title="Inactive Job",
            company_id=test_company.id,
            is_active=False,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(inactive_job)
        await db_session.flush()

        response = await async_client.get(
            f"/api/v1/jobs/{inactive_job.id}", headers=auth_headers
        )
        assert response.status_code == 404

    async def test_job_response_includes_company_info(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_job: Job,
    ):
        response = await async_client.get(
            f"/api/v1/jobs/{test_job.id}", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "company" in data
        if data["company"]:
            assert "name" in data["company"]
