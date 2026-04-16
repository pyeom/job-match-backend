"""
Integration tests for MALA Assessment API endpoints.

Covers:
  GET  /api/v1/mala/questions
  GET  /api/v1/mala/questions?block=A
  GET  /api/v1/mala/questions/progress
  POST /api/v1/mala/responses
  GET  /api/v1/mala/responses
  GET  /api/v1/mala/responses/{code}/status
  DELETE /api/v1/mala/responses/{code}
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.user import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_LONG_RESPONSE = (
    "Durante mi carrera implementé varios sistemas que mejoraron la eficiencia operacional. "
    "Desarrollé una plataforma de análisis de datos que aumentó la productividad del equipo en 40%. "
    "Lideré la migración de infraestructura a la nube, reduciendo costos en un 25% anual. "
    "Coordiné con equipos multidisciplinarios para entregar proyectos de alta complejidad a tiempo. "
    "Diseñé arquitecturas escalables que soportaron un crecimiento de 10x en usuarios activos. "
    "Trabajé directamente con clientes para entender sus necesidades y traducirlas en soluciones técnicas. "
    "Creé procesos de revisión y mejora continua que elevaron la calidad del código significativamente."
)


def _mock_arq_pool():
    fake_job = MagicMock()
    fake_job.job_id = "test-job-id-123"
    fake_pool = AsyncMock()
    fake_pool.enqueue_job = AsyncMock(return_value=fake_job)

    async def _get_pool():
        return fake_pool

    return _get_pool


# ---------------------------------------------------------------------------
# GET /api/v1/mala/questions
# ---------------------------------------------------------------------------
class TestListQuestions:
    async def test_returns_all_12_questions(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        response = await async_client.get("/api/v1/mala/questions", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 12

    async def test_filter_by_block_a_returns_3_questions(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        response = await async_client.get(
            "/api/v1/mala/questions?block=A", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 3
        for q in data:
            assert q["block"] == "A"

    async def test_requires_authentication(self, async_client: AsyncClient):
        response = await async_client.get("/api/v1/mala/questions")
        assert response.status_code in (401, 403)

    async def test_company_user_cannot_access(
        self,
        async_client: AsyncClient,
        company_auth_headers: dict,
    ):
        response = await async_client.get(
            "/api/v1/mala/questions", headers=company_auth_headers
        )
        assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /api/v1/mala/questions/progress
# ---------------------------------------------------------------------------
class TestGetProgress:
    async def test_returns_progress_schema(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        response = await async_client.get(
            "/api/v1/mala/questions/progress", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "questions_answered" in data
        assert "questions_total" in data
        assert data["questions_total"] == 12
        assert "completion_percentage" in data
        assert "puc_completeness" in data
        assert "confidence_level" in data
        assert "blocks_status" in data
        assert set(data["blocks_status"].keys()) == {"A", "B", "C", "D"}
        for block_key, block_data in data["blocks_status"].items():
            assert "answered" in block_data
            assert "total" in block_data
            assert "is_complete" in block_data

    async def test_fresh_user_has_zero_answered(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        response = await async_client.get(
            "/api/v1/mala/questions/progress", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["questions_answered"] == 0
        assert data["completion_percentage"] == 0.0


# ---------------------------------------------------------------------------
# POST /api/v1/mala/responses
# ---------------------------------------------------------------------------
class TestSubmitResponse:
    async def test_submit_valid_response_returns_200(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        monkeypatch,
    ):
        import app.api.v1.mala.endpoints as ep
        monkeypatch.setattr(ep, "get_arq_pool", _mock_arq_pool())

        response = await async_client.post(
            "/api/v1/mala/responses",
            headers=auth_headers,
            json={"question_code": "P1", "response_text": _LONG_RESPONSE},
        )
        assert response.status_code == 200
        data = response.json()
        assert "response_id" in data
        assert "quality_result" in data
        assert "processing_job_id" in data
        assert "progress" in data
        assert data["quality_result"]["is_too_short"] is False

    async def test_submit_too_short_text_returns_422(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        response = await async_client.post(
            "/api/v1/mala/responses",
            headers=auth_headers,
            json={"question_code": "P1", "response_text": "Esta respuesta es muy corta."},
        )
        assert response.status_code == 422

    async def test_submit_text_under_pydantic_min_returns_422(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ):
        response = await async_client.post(
            "/api/v1/mala/responses",
            headers=auth_headers,
            json={"question_code": "P1", "response_text": "short"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/mala/responses
# ---------------------------------------------------------------------------
class TestListResponses:
    async def test_returns_empty_list_for_new_user(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        response = await async_client.get("/api/v1/mala/responses", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    async def test_returns_submitted_responses(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        monkeypatch,
    ):
        import app.api.v1.mala.endpoints as ep
        monkeypatch.setattr(ep, "get_arq_pool", _mock_arq_pool())

        await async_client.post(
            "/api/v1/mala/responses",
            headers=auth_headers,
            json={"question_code": "P2", "response_text": _LONG_RESPONSE},
        )

        response = await async_client.get("/api/v1/mala/responses", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["layer_results"] is None


# ---------------------------------------------------------------------------
# GET /api/v1/mala/responses/{question_code}/status
# ---------------------------------------------------------------------------
class TestGetResponseStatus:
    async def test_returns_status_for_existing_response(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        monkeypatch,
    ):
        import app.api.v1.mala.endpoints as ep
        monkeypatch.setattr(ep, "get_arq_pool", _mock_arq_pool())

        await async_client.post(
            "/api/v1/mala/responses",
            headers=auth_headers,
            json={"question_code": "P3", "response_text": _LONG_RESPONSE},
        )

        response = await async_client.get(
            "/api/v1/mala/responses/P3/status", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "error" in data

    async def test_returns_404_for_missing_response(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        response = await async_client.get(
            "/api/v1/mala/responses/P9/status", headers=auth_headers
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/mala/responses/{question_code}
# ---------------------------------------------------------------------------
class TestDeleteResponse:
    async def test_delete_existing_response_returns_204(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
        monkeypatch,
    ):
        import app.api.v1.mala.endpoints as ep
        monkeypatch.setattr(ep, "get_arq_pool", _mock_arq_pool())

        await async_client.post(
            "/api/v1/mala/responses",
            headers=auth_headers,
            json={"question_code": "P1", "response_text": _LONG_RESPONSE},
        )

        response = await async_client.delete(
            "/api/v1/mala/responses/P1", headers=auth_headers
        )
        assert response.status_code == 204

    async def test_delete_nonexistent_response_returns_404(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        test_user: User,
    ):
        response = await async_client.delete(
            "/api/v1/mala/responses/P1", headers=auth_headers
        )
        assert response.status_code == 404
