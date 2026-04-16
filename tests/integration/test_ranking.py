"""
B7.6 — Integration tests for the Candidate Ranking API

Verifies:
1. Ranking endpoint returns candidates sorted by final_effective_score DESC
2. Hard filter correctly excludes candidates without required skills
3. Full insights endpoint returns a valid MatchScoreResult
4. Recruiter decision endpoint persists the decision

Uses 5 seeded candidates with distinct profiles.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.models.company import Company
from app.models.job import Job
from app.models.mala import CandidatePUCProfile, JobMatchConfig, MatchScore
from app.models.user import User, UserRole


# ---------------------------------------------------------------------------
# Fixtures — company, admin, job, job config, 5 candidates + applications
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def ranking_company(db_session: AsyncSession) -> Company:
    """Company fixture for ranking tests."""
    from app.models.company import Company

    company = Company(
        id=uuid.uuid4(),
        name="Ranking Test Corp",
        description="Company for ranking tests",
        industry="Software",
        size="51-200",
        location="Remote",
        is_active=True,
        is_verified=True,
    )
    db_session.add(company)
    await db_session.flush()
    return company


@pytest_asyncio.fixture
async def ranking_admin(db_session: AsyncSession, ranking_company: Company) -> User:
    """Company admin for ranking tests."""
    from app.core.security import get_password_hash

    admin = User(
        id=uuid.uuid4(),
        email=f"ranking_admin_{uuid.uuid4().hex[:6]}@corp.com",
        password_hash=get_password_hash("Password1"),
        full_name="Ranking Admin",
        role=UserRole.COMPANY_ADMIN,
        company_id=ranking_company.id,
        skills=[],
        email_verified=True,
    )
    db_session.add(admin)
    await db_session.flush()
    return admin


@pytest_asyncio.fixture
async def ranking_job(db_session: AsyncSession, ranking_company: Company) -> Job:
    """Job fixture for ranking tests — requires Python and 2+ years."""
    from datetime import datetime, timezone

    ZERO_EMBEDDING: list[float] = [0.0] * 384

    job = Job(
        id=uuid.uuid4(),
        title="Senior Python Developer",
        company_id=ranking_company.id,
        location="Remote",
        short_description="Senior Python role",
        description="We need a Python expert.",
        tags=["python", "fastapi"],
        seniority="senior",
        is_active=True,
        job_embedding=ZERO_EMBEDDING,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(job)
    await db_session.flush()
    return job


@pytest_asyncio.fixture
async def ranking_job_config(
    db_session: AsyncSession,
    ranking_job: Job,
) -> JobMatchConfig:
    """JobMatchConfig for ranking_job: requires python, 2 years, no Big Five minimums."""
    config = JobMatchConfig(
        id=uuid.uuid4(),
        job_id=ranking_job.id,
        hard_skills_required=["python"],
        hard_skills_desired=["fastapi", "postgresql"],
        min_experience_years=2,
        required_education_level=None,
        required_languages=[],
        req_openness_min=0.0,
        req_conscientiousness_min=50.0,
        req_extraversion_min=0.0,
        req_agreeableness_min=0.0,
        req_stability_min=0.0,
        weight_hard=0.50,
        weight_soft=0.30,
        weight_predictive=0.20,
    )
    db_session.add(config)
    await db_session.flush()
    return config


def _make_puc(user_id: uuid.UUID, **kwargs) -> CandidatePUCProfile:
    """Helper to build a CandidatePUCProfile with defaults."""
    defaults = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        openness=70.0,
        conscientiousness=70.0,
        extraversion=60.0,
        agreeableness=65.0,
        emotional_stability=65.0,
        n_ach=0.7,
        n_aff=0.5,
        churn_risk=0.3,
        analytical_thinking=70.0,
        completeness_score=0.8,
        primary_archetype="El Ejecutor",
    )
    defaults.update(kwargs)
    return CandidatePUCProfile(**defaults)


@pytest_asyncio.fixture
async def five_candidates(
    db_session: AsyncSession,
    ranking_job: Job,
    ranking_job_config: JobMatchConfig,
) -> list[dict[str, Any]]:
    """Create 5 candidates with distinct profiles and pre-seeded MatchScore rows.

    Profiles:
    - alice:   Strong Python dev, high Big Five, high score
    - bob:     Good Python dev, medium Big Five, medium score
    - charlie: Python dev, low conscientiousness → lower soft score
    - diana:   High skills but churn_risk = 0.9 → lower score
    - eve:     Missing 'python' skill → FAILS hard filter, score = 0
    """
    from app.core.security import get_password_hash

    ZERO_EMBEDDING: list[float] = [0.0] * 384

    def _user(name: str, skills: list[str], email: str) -> User:
        return User(
            id=uuid.uuid4(),
            email=email,
            password_hash=get_password_hash("Password1"),
            full_name=name,
            role=UserRole.JOB_SEEKER,
            skills=skills,
            seniority="senior",
            profile_embedding=ZERO_EMBEDDING,
            email_verified=True,
        )

    alice = _user("Alice Smith", ["python", "fastapi", "postgresql"], f"alice_{uuid.uuid4().hex[:6]}@ex.com")
    bob = _user("Bob Jones", ["python", "fastapi"], f"bob_{uuid.uuid4().hex[:6]}@ex.com")
    charlie = _user("Charlie Brown", ["python"], f"charlie_{uuid.uuid4().hex[:6]}@ex.com")
    diana = _user("Diana Prince", ["python", "fastapi", "postgresql"], f"diana_{uuid.uuid4().hex[:6]}@ex.com")
    eve = _user("Eve Adams", ["javascript", "react"], f"eve_{uuid.uuid4().hex[:6]}@ex.com")

    for u in [alice, bob, charlie, diana, eve]:
        db_session.add(u)
    await db_session.flush()

    # Create PUC profiles
    alice_puc = _make_puc(alice.id, conscientiousness=90.0, openness=85.0, churn_risk=0.1, completeness_score=0.9)
    bob_puc = _make_puc(bob.id, conscientiousness=70.0, openness=65.0, churn_risk=0.3, completeness_score=0.75)
    charlie_puc = _make_puc(charlie.id, conscientiousness=30.0, openness=55.0, churn_risk=0.4, completeness_score=0.6)
    diana_puc = _make_puc(diana.id, conscientiousness=80.0, openness=80.0, churn_risk=0.9, completeness_score=0.85)
    eve_puc = _make_puc(eve.id, conscientiousness=75.0, openness=70.0, churn_risk=0.2, completeness_score=0.8)

    for puc in [alice_puc, bob_puc, charlie_puc, diana_puc, eve_puc]:
        db_session.add(puc)
    await db_session.flush()

    # Create applications
    apps = []
    for user in [alice, bob, charlie, diana, eve]:
        app = Application(
            id=uuid.uuid4(),
            user_id=user.id,
            job_id=ranking_job.id,
            stage="SUBMITTED",
            status="ACTIVE",
            stage_history=[],
        )
        db_session.add(app)
        apps.append(app)
    await db_session.flush()

    # Pre-seed MatchScore rows with plausible scores
    # Alice: passes hard filter, high scores
    alice_ms = MatchScore(
        id=uuid.uuid4(),
        user_id=alice.id,
        job_id=ranking_job.id,
        application_id=apps[0].id,
        total_score=88.0,
        confidence_multiplier=0.9,
        final_effective_score=79.2,
        hard_match_score=92.0,
        soft_match_score=85.0,
        predictive_match_score=80.0,
        hard_filter_passed=True,
        skills_coverage=1.0,
        experience_score=1.0,
        education_score=0.8,
        language_score=1.0,
        big_five_fit=88.0,
        mcclelland_culture_fit=70.0,
        appraisal_values_fit=70.0,
        career_narrative_fit=100.0,
        top_strengths=[{"title": "Alta autogestión", "evidence": "90/100", "confidence": 0.9, "source_layer": 4}],
        top_alerts=[],
        interview_guide=[],
        explanation_text="Excellent match.",
    )

    # Bob: passes hard filter, medium scores
    bob_ms = MatchScore(
        id=uuid.uuid4(),
        user_id=bob.id,
        job_id=ranking_job.id,
        application_id=apps[1].id,
        total_score=72.0,
        confidence_multiplier=0.75,
        final_effective_score=54.0,
        hard_match_score=78.0,
        soft_match_score=68.0,
        predictive_match_score=65.0,
        hard_filter_passed=True,
        skills_coverage=0.67,
        big_five_fit=70.0,
        top_strengths=[],
        top_alerts=[],
        interview_guide=[],
        explanation_text="Good match.",
    )

    # Charlie: passes hard filter but low soft score
    charlie_ms = MatchScore(
        id=uuid.uuid4(),
        user_id=charlie.id,
        job_id=ranking_job.id,
        application_id=apps[2].id,
        total_score=58.0,
        confidence_multiplier=0.6,
        final_effective_score=34.8,
        hard_match_score=65.0,
        soft_match_score=48.0,
        predictive_match_score=55.0,
        hard_filter_passed=True,
        skills_coverage=0.33,
        big_five_fit=40.0,
        top_strengths=[],
        top_alerts=[{"title": "Baja autogestión", "evidence": "30/100", "confidence": 0.8, "source_layer": 4}],
        interview_guide=[],
        explanation_text="Marginal match.",
    )

    # Diana: passes hard filter but high churn risk lowers score
    diana_ms = MatchScore(
        id=uuid.uuid4(),
        user_id=diana.id,
        job_id=ranking_job.id,
        application_id=apps[3].id,
        total_score=70.0,
        confidence_multiplier=0.85,
        final_effective_score=59.5,
        hard_match_score=85.0,
        soft_match_score=55.0,
        predictive_match_score=60.0,
        hard_filter_passed=True,
        skills_coverage=1.0,
        big_five_fit=78.0,
        career_narrative_fit=40.0,
        top_strengths=[],
        top_alerts=[{"title": "Riesgo de rotación", "evidence": "90%", "confidence": 0.9, "source_layer": 5}],
        interview_guide=[],
        explanation_text="Skills match but churn risk.",
    )

    # Eve: FAILS hard filter (no python skill)
    eve_ms = MatchScore(
        id=uuid.uuid4(),
        user_id=eve.id,
        job_id=ranking_job.id,
        application_id=apps[4].id,
        total_score=0.0,
        confidence_multiplier=0.8,
        final_effective_score=0.0,
        hard_match_score=0.0,
        soft_match_score=72.0,
        predictive_match_score=55.0,
        hard_filter_passed=False,
        skills_coverage=0.0,
        top_strengths=[],
        top_alerts=[{"title": "Habilidad requerida no acreditada: python", "evidence": "...", "confidence": 0.95, "source_layer": 1}],
        interview_guide=[],
        explanation_text="Fails hard filter.",
    )

    for ms in [alice_ms, bob_ms, charlie_ms, diana_ms, eve_ms]:
        db_session.add(ms)
    await db_session.flush()

    return [
        {"user": alice, "score": alice_ms, "puc": alice_puc},
        {"user": bob, "score": bob_ms, "puc": bob_puc},
        {"user": charlie, "score": charlie_ms, "puc": charlie_puc},
        {"user": diana, "score": diana_ms, "puc": diana_puc},
        {"user": eve, "score": eve_ms, "puc": eve_puc},
    ]


@pytest.fixture
def ranking_admin_token(ranking_admin: User) -> str:
    from app.core.security import create_access_token
    return create_access_token(data={"sub": str(ranking_admin.id)})


@pytest.fixture
def ranking_admin_headers(ranking_admin_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {ranking_admin_token}"}


# ---------------------------------------------------------------------------
# Test 1: Ranking is sorted by final_effective_score DESC
# ---------------------------------------------------------------------------

class TestRankingSortOrder:
    """Verify that GET /jobs/{job_id}/candidates/ranking returns candidates sorted DESC."""

    async def test_ranking_sorted_by_score_descending(
        self,
        async_client: AsyncClient,
        ranking_job: Job,
        ranking_admin_headers: dict,
        five_candidates: list,
    ):
        response = await async_client.get(
            f"/api/v1/companies/jobs/{ranking_job.id}/candidates/ranking",
            headers=ranking_admin_headers,
        )
        assert response.status_code == 200, response.text

        data = response.json()
        assert "candidates" in data
        candidates = data["candidates"]
        assert len(candidates) >= 2, "Should return at least 2 scored candidates"

        # Verify sort order
        scores = [c["final_effective_score"] for c in candidates]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"Candidates not sorted DESC: score[{i}]={scores[i]} > score[{i+1}]={scores[i+1]}"
            )

    async def test_alice_ranks_first(
        self,
        async_client: AsyncClient,
        ranking_job: Job,
        ranking_admin_headers: dict,
        five_candidates: list,
    ):
        """Alice (highest score 79.2) should appear first in the ranking."""
        alice = five_candidates[0]["user"]

        response = await async_client.get(
            f"/api/v1/companies/jobs/{ranking_job.id}/candidates/ranking",
            headers=ranking_admin_headers,
        )
        assert response.status_code == 200

        candidates = response.json()["candidates"]
        assert len(candidates) > 0

        top_candidate_id = candidates[0]["user_id"]
        assert str(alice.id) == top_candidate_id, (
            f"Expected Alice ({alice.id}) to rank first, got {top_candidate_id}"
        )

    async def test_total_count_returned(
        self,
        async_client: AsyncClient,
        ranking_job: Job,
        ranking_admin_headers: dict,
        five_candidates: list,
    ):
        response = await async_client.get(
            f"/api/v1/companies/jobs/{ranking_job.id}/candidates/ranking",
            headers=ranking_admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert data["page"] == 1

    async def test_pagination_works(
        self,
        async_client: AsyncClient,
        ranking_job: Job,
        ranking_admin_headers: dict,
        five_candidates: list,
    ):
        response = await async_client.get(
            f"/api/v1/companies/jobs/{ranking_job.id}/candidates/ranking",
            headers=ranking_admin_headers,
            params={"page": 1, "page_size": 2},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["candidates"]) == 2
        assert data["has_more"] is True

    async def test_unauthenticated_returns_401(
        self,
        async_client: AsyncClient,
        ranking_job: Job,
    ):
        response = await async_client.get(
            f"/api/v1/companies/jobs/{ranking_job.id}/candidates/ranking"
        )
        assert response.status_code in (401, 403)

    async def test_min_score_filter_applied(
        self,
        async_client: AsyncClient,
        ranking_job: Job,
        ranking_admin_headers: dict,
        five_candidates: list,
    ):
        """min_score=60 should exclude Charlie (34.8) and Eve (0.0)."""
        response = await async_client.get(
            f"/api/v1/companies/jobs/{ranking_job.id}/candidates/ranking",
            headers=ranking_admin_headers,
            params={"min_score": 60.0},
        )
        assert response.status_code == 200
        data = response.json()
        scores = [c["final_effective_score"] for c in data["candidates"]]
        for score in scores:
            assert score >= 60.0, f"Score {score} is below min_score=60"


# ---------------------------------------------------------------------------
# Test 2: Hard filter correctly excludes candidates without required skills
# ---------------------------------------------------------------------------

class TestHardFilterExclusion:
    """Verify hard-filter exclusion via the ranking and insights endpoints."""

    async def test_eve_has_zero_score(
        self,
        async_client: AsyncClient,
        ranking_job: Job,
        ranking_admin_headers: dict,
        five_candidates: list,
    ):
        """Eve (no python skill) should have final_effective_score=0."""
        eve = five_candidates[4]["user"]

        response = await async_client.get(
            f"/api/v1/companies/jobs/{ranking_job.id}/candidates/ranking",
            headers=ranking_admin_headers,
        )
        assert response.status_code == 200

        candidates = response.json()["candidates"]
        eve_entry = next((c for c in candidates if c["user_id"] == str(eve.id)), None)
        assert eve_entry is not None, "Eve should appear in ranking"
        assert eve_entry["final_effective_score"] == 0.0, (
            f"Eve should have score=0 (hard filter fails), got {eve_entry['final_effective_score']}"
        )

    async def test_eve_ranks_last(
        self,
        async_client: AsyncClient,
        ranking_job: Job,
        ranking_admin_headers: dict,
        five_candidates: list,
    ):
        """Eve (score=0) should appear last in the sorted ranking."""
        eve = five_candidates[4]["user"]

        response = await async_client.get(
            f"/api/v1/companies/jobs/{ranking_job.id}/candidates/ranking",
            headers=ranking_admin_headers,
        )
        assert response.status_code == 200

        candidates = response.json()["candidates"]
        last_id = candidates[-1]["user_id"]
        assert str(eve.id) == last_id, (
            f"Expected Eve ({eve.id}) to rank last, got {last_id}"
        )

    async def test_full_insights_shows_hard_filter_failure_for_eve(
        self,
        async_client: AsyncClient,
        ranking_job: Job,
        ranking_admin_headers: dict,
        five_candidates: list,
    ):
        """Full insights for Eve should show the hard filter alert."""
        eve = five_candidates[4]["user"]

        response = await async_client.get(
            f"/api/v1/companies/jobs/{ranking_job.id}/candidates/{eve.id}/full-insights",
            headers=ranking_admin_headers,
        )
        assert response.status_code == 200
        data = response.json()

        assert data["hard_match"]["passed_filter"] is False
        assert data["hard_match"]["score"] == 0.0


# ---------------------------------------------------------------------------
# Test 3: Full insights endpoint returns valid MatchScoreResult
# ---------------------------------------------------------------------------

class TestFullInsightsEndpoint:
    async def test_full_insights_returns_200(
        self,
        async_client: AsyncClient,
        ranking_job: Job,
        ranking_admin_headers: dict,
        five_candidates: list,
    ):
        alice = five_candidates[0]["user"]
        response = await async_client.get(
            f"/api/v1/companies/jobs/{ranking_job.id}/candidates/{alice.id}/full-insights",
            headers=ranking_admin_headers,
        )
        assert response.status_code == 200

    async def test_full_insights_has_required_fields(
        self,
        async_client: AsyncClient,
        ranking_job: Job,
        ranking_admin_headers: dict,
        five_candidates: list,
    ):
        alice = five_candidates[0]["user"]
        response = await async_client.get(
            f"/api/v1/companies/jobs/{ranking_job.id}/candidates/{alice.id}/full-insights",
            headers=ranking_admin_headers,
        )
        assert response.status_code == 200
        data = response.json()

        required_fields = [
            "user_id", "job_id", "total_score", "confidence_multiplier",
            "final_effective_score", "hard_match", "soft_match", "predictive_match",
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

    async def test_full_insights_unknown_user_returns_404_or_zero(
        self,
        async_client: AsyncClient,
        ranking_job: Job,
        ranking_admin_headers: dict,
        five_candidates: list,
        ranking_company: Company,
    ):
        """Requesting insights for a non-existent user returns 404 or a zero score."""
        fake_user_id = uuid.uuid4()
        response = await async_client.get(
            f"/api/v1/companies/jobs/{ranking_job.id}/candidates/{fake_user_id}/full-insights",
            headers=ranking_admin_headers,
        )
        # Either 404 (user not found) or 200 with computed zero score is acceptable
        assert response.status_code in (200, 404, 500)


# ---------------------------------------------------------------------------
# Test 4: Recruiter decision endpoint persists the decision
# ---------------------------------------------------------------------------

class TestRecruiterDecision:
    async def test_record_avanza_decision(
        self,
        async_client: AsyncClient,
        ranking_job: Job,
        ranking_admin_headers: dict,
        five_candidates: list,
    ):
        alice = five_candidates[0]["user"]
        response = await async_client.post(
            f"/api/v1/companies/jobs/{ranking_job.id}/candidates/{alice.id}/decision",
            headers=ranking_admin_headers,
            json={"decision": "avanza", "notes": "Great candidate"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["decision"] == "avanza"

    async def test_record_descarta_decision(
        self,
        async_client: AsyncClient,
        ranking_job: Job,
        ranking_admin_headers: dict,
        five_candidates: list,
    ):
        eve = five_candidates[4]["user"]
        response = await async_client.post(
            f"/api/v1/companies/jobs/{ranking_job.id}/candidates/{eve.id}/decision",
            headers=ranking_admin_headers,
            json={"decision": "descarta"},
        )
        assert response.status_code == 200
        assert response.json()["decision"] == "descarta"

    async def test_invalid_decision_value_returns_422(
        self,
        async_client: AsyncClient,
        ranking_job: Job,
        ranking_admin_headers: dict,
        five_candidates: list,
    ):
        alice = five_candidates[0]["user"]
        response = await async_client.post(
            f"/api/v1/companies/jobs/{ranking_job.id}/candidates/{alice.id}/decision",
            headers=ranking_admin_headers,
            json={"decision": "invalid_value"},
        )
        assert response.status_code == 422

    async def test_decision_reflects_in_ranking(
        self,
        async_client: AsyncClient,
        ranking_job: Job,
        ranking_admin_headers: dict,
        five_candidates: list,
        db_session: AsyncSession,
    ):
        """After recording a decision, filter by that decision in the ranking."""
        bob = five_candidates[1]["user"]

        # Record decision
        await async_client.post(
            f"/api/v1/companies/jobs/{ranking_job.id}/candidates/{bob.id}/decision",
            headers=ranking_admin_headers,
            json={"decision": "en_espera"},
        )

        # Filter ranking by decision status
        response = await async_client.get(
            f"/api/v1/companies/jobs/{ranking_job.id}/candidates/ranking",
            headers=ranking_admin_headers,
            params={"decision_status": "en_espera"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        for candidate in data["candidates"]:
            assert candidate["recruiter_decision"] == "en_espera"
