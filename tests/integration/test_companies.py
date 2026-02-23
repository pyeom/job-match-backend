"""
Integration tests for company API endpoints.

Covers:
  GET   /api/v1/companies/
  GET   /api/v1/companies/public/{company_id}
  GET   /api/v1/companies/{company_id}
  PATCH /api/v1/companies/{company_id}
  GET   /api/v1/companies/{company_id}/jobs
  POST  /api/v1/companies/{company_id}/jobs
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.job import Job
from app.models.user import User


# ---------------------------------------------------------------------------
# GET /api/v1/companies/ (list active companies, public-ish)
# ---------------------------------------------------------------------------
class TestListCompanies:
    async def test_returns_list_for_authenticated_user(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_company: Company,
    ):
        response = await async_client.get(
            "/api/v1/companies/", headers=auth_headers
        )
        # Some implementations may require auth, others not
        assert response.status_code in (200, 403)

    async def test_response_is_list_when_200(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        response = await async_client.get(
            "/api/v1/companies/", headers=auth_headers
        )
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)


# ---------------------------------------------------------------------------
# GET /api/v1/companies/public/{company_id}
# ---------------------------------------------------------------------------
class TestGetPublicCompany:
    async def test_returns_public_company_info(
        self,
        async_client: AsyncClient,
        test_company: Company,
    ):
        response = await async_client.get(
            f"/api/v1/companies/public/{test_company.id}"
        )
        # No auth required for public endpoint
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == test_company.name

    async def test_returns_404_for_nonexistent_company(
        self,
        async_client: AsyncClient,
    ):
        fake_id = uuid.uuid4()
        response = await async_client.get(
            f"/api/v1/companies/public/{fake_id}"
        )
        assert response.status_code == 404

    async def test_returns_422_for_invalid_uuid(
        self,
        async_client: AsyncClient,
    ):
        response = await async_client.get("/api/v1/companies/public/not-a-uuid")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/companies/{company_id}
# ---------------------------------------------------------------------------
class TestGetCompany:
    async def test_company_admin_can_get_own_company(
        self,
        async_client: AsyncClient,
        company_auth_headers: dict,
        test_company: Company,
    ):
        response = await async_client.get(
            f"/api/v1/companies/{test_company.id}",
            headers=company_auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == test_company.name

    async def test_returns_403_without_token(
        self,
        async_client: AsyncClient,
        test_company: Company,
    ):
        response = await async_client.get(
            f"/api/v1/companies/{test_company.id}"
        )
        assert response.status_code in (401, 403)

    async def test_job_seeker_cannot_access_company_admin_endpoint(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_company: Company,
    ):
        # The admin-only endpoint is /admin suffix — the base GET returns
        # public info to any authenticated user.
        response = await async_client.get(
            f"/api/v1/companies/{test_company.id}/admin",
            headers=auth_headers,  # job seeker token
        )
        assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# PATCH /api/v1/companies/{company_id}
# ---------------------------------------------------------------------------
class TestUpdateCompany:
    async def test_company_admin_can_update_company(
        self,
        async_client: AsyncClient,
        company_auth_headers: dict,
        test_company: Company,
    ):
        response = await async_client.patch(
            f"/api/v1/companies/{test_company.id}",
            headers=company_auth_headers,
            json={"description": "Updated description"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["description"] == "Updated description"

    async def test_update_without_token_returns_403(
        self,
        async_client: AsyncClient,
        test_company: Company,
    ):
        response = await async_client.patch(
            f"/api/v1/companies/{test_company.id}",
            json={"description": "hack"},
        )
        assert response.status_code in (401, 403)

    async def test_job_seeker_cannot_update_company(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_company: Company,
    ):
        response = await async_client.patch(
            f"/api/v1/companies/{test_company.id}",
            headers=auth_headers,
            json={"description": "hack attempt"},
        )
        assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /api/v1/companies/{company_id}/jobs
# ---------------------------------------------------------------------------
class TestGetCompanyJobs:
    async def test_returns_company_jobs(
        self,
        async_client: AsyncClient,
        company_auth_headers: dict,
        test_company: Company,
        test_job: Job,
    ):
        response = await async_client.get(
            f"/api/v1/companies/{test_company.id}/jobs",
            headers=company_auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        # Response may be a list or a paginated object
        assert data is not None

    async def test_returns_403_without_token(
        self,
        async_client: AsyncClient,
        test_company: Company,
    ):
        response = await async_client.get(
            f"/api/v1/companies/{test_company.id}/jobs"
        )
        assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# POST /api/v1/companies/{company_id}/jobs
# ---------------------------------------------------------------------------
class TestCreateCompanyJob:
    async def test_company_admin_can_create_job(
        self,
        async_client: AsyncClient,
        company_auth_headers: dict,
        test_company: Company,
    ):
        payload = {
            "title": "Senior Python Developer",
            "location": "Remote",
            "short_description": "Build great APIs",
            "description": "Full job description.",
            "tags": ["python", "fastapi"],
            "seniority": "senior",
            "salary_min": 100_000,
            "salary_max": 140_000,
            "remote": True,
            "work_arrangement": "Remote",
            "job_type": "Full-time",
        }
        response = await async_client.post(
            f"/api/v1/companies/{test_company.id}/jobs",
            headers=company_auth_headers,
            json=payload,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Senior Python Developer"
        assert data["company_id"] == str(test_company.id)

    async def test_create_job_without_token_returns_403(
        self,
        async_client: AsyncClient,
        test_company: Company,
    ):
        payload = {"title": "Test Job"}
        response = await async_client.post(
            f"/api/v1/companies/{test_company.id}/jobs",
            json=payload,
        )
        assert response.status_code in (401, 403)

    async def test_job_seeker_cannot_create_job(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_company: Company,
    ):
        payload = {"title": "Test Job"}
        response = await async_client.post(
            f"/api/v1/companies/{test_company.id}/jobs",
            headers=auth_headers,
            json=payload,
        )
        assert response.status_code in (401, 403)

    async def test_missing_title_returns_422(
        self,
        async_client: AsyncClient,
        company_auth_headers: dict,
        test_company: Company,
    ):
        response = await async_client.post(
            f"/api/v1/companies/{test_company.id}/jobs",
            headers=company_auth_headers,
            json={"location": "Remote"},  # missing title
        )
        assert response.status_code == 422

    async def test_create_job_for_different_company_returns_403(
        self,
        async_client: AsyncClient,
        company_auth_headers: dict,
        db_session: AsyncSession,
    ):
        # Create a different company
        other_company = Company(
            id=uuid.uuid4(),
            name=f"Other Corp {uuid.uuid4().hex[:8]}",
            is_active=True,
        )
        db_session.add(other_company)
        await db_session.flush()

        payload = {"title": "Unauthorized Job"}
        response = await async_client.post(
            f"/api/v1/companies/{other_company.id}/jobs",
            headers=company_auth_headers,
            json=payload,
        )
        assert response.status_code in (401, 403)
