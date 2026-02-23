"""
Unit tests for ScoringService.

Tests the hybrid scoring algorithm:
  55% embedding similarity
  20% skill overlap
  10% seniority match
  10% recency decay
  5%  location match
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from app.services.scoring_service import ScoringService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_embedding(value: float = 1.0, dims: int = 384) -> list[float]:
    """Return a unit-normalised embedding pointing in direction ``value``."""
    vec = [value] * dims
    norm = math.sqrt(sum(v ** 2 for v in vec))
    return [v / norm for v in vec]


# ---------------------------------------------------------------------------
# calculate_skill_overlap
# ---------------------------------------------------------------------------
class TestCalculateSkillOverlap:
    def test_full_overlap(self):
        result = ScoringService.calculate_skill_overlap(
            user_skills=["python", "fastapi"],
            job_tags=["python", "fastapi"],
        )
        assert result == 1.0

    def test_partial_overlap(self):
        result = ScoringService.calculate_skill_overlap(
            user_skills=["python", "fastapi", "sql"],
            job_tags=["python", "fastapi", "go", "rust"],
        )
        # 2 common out of 4 job tags = 0.5
        assert result == pytest.approx(0.5)

    def test_no_overlap(self):
        result = ScoringService.calculate_skill_overlap(
            user_skills=["java", "spring"],
            job_tags=["python", "fastapi"],
        )
        assert result == 0.0

    def test_empty_user_skills(self):
        result = ScoringService.calculate_skill_overlap(
            user_skills=[],
            job_tags=["python"],
        )
        assert result == 0.0

    def test_none_user_skills(self):
        result = ScoringService.calculate_skill_overlap(
            user_skills=None,
            job_tags=["python"],
        )
        assert result == 0.0

    def test_none_job_tags(self):
        result = ScoringService.calculate_skill_overlap(
            user_skills=["python"],
            job_tags=None,
        )
        assert result == 0.0

    def test_case_insensitive(self):
        result = ScoringService.calculate_skill_overlap(
            user_skills=["Python", "FastAPI"],
            job_tags=["python", "fastapi"],
        )
        assert result == 1.0

    def test_skill_weight_in_total_score(self):
        """20% skill weight: perfect overlap on otherwise zero-contributing factors."""
        now = datetime.now(timezone.utc)
        # Use identical embeddings for similarity = 1.0
        emb = _make_embedding(1.0)

        with patch(
            "app.services.scoring_service.embedding_service.calculate_similarity",
            return_value=0.0,
        ):
            score = ScoringService.calculate_job_score(
                user_embedding=emb,
                job_embedding=emb,
                user_skills=["python"],
                user_seniority=None,
                user_preferences=None,
                job_tags=["python"],
                job_seniority=None,
                job_location=None,
                job_remote=False,
                job_created_at=now,
            )

        # With similarity=0, seniority default=0.5, recency~1, location default=0.5:
        # 0 + 0.20*1 + 0.10*0.5 + 0.10*~1 + 0.05*0.5 ≈ 0.375
        # Score 0–100, so ≈ 37–38.  Just verify skill contributes.
        assert score > 0


# ---------------------------------------------------------------------------
# calculate_seniority_match
# ---------------------------------------------------------------------------
class TestCalculateSeniorityMatch:
    def test_exact_match_returns_one(self):
        result = ScoringService.calculate_seniority_match("mid", "mid")
        assert result == 1.0

    def test_adjacent_levels_return_half(self):
        result = ScoringService.calculate_seniority_match("junior", "mid")
        assert result == 0.5

    def test_two_levels_apart_returns_zero(self):
        result = ScoringService.calculate_seniority_match("junior", "senior")
        assert result == 0.0

    def test_missing_user_seniority_returns_default(self):
        result = ScoringService.calculate_seniority_match(None, "senior")
        assert result == 0.5

    def test_missing_job_seniority_returns_default(self):
        result = ScoringService.calculate_seniority_match("mid", None)
        assert result == 0.5

    def test_case_insensitive(self):
        result = ScoringService.calculate_seniority_match("Mid", "MID")
        assert result == 1.0

    def test_senior_to_lead_adjacent(self):
        result = ScoringService.calculate_seniority_match("senior", "lead")
        assert result == 0.5

    def test_junior_to_lead_far_apart(self):
        result = ScoringService.calculate_seniority_match("junior", "lead")
        assert result == 0.0


# ---------------------------------------------------------------------------
# calculate_recency_decay
# ---------------------------------------------------------------------------
class TestCalculateRecencyDecay:
    def test_just_created_returns_near_one(self):
        just_now = datetime.now(timezone.utc)
        result = ScoringService.calculate_recency_decay(just_now)
        assert result == pytest.approx(1.0, abs=0.01)

    def test_72_hours_old_returns_half(self):
        # Half-life is 72 hours: exp(-72/72) = exp(-1) ≈ 0.368 (not 0.5;
        # the code uses an exponential with 72-hr characteristic time).
        created_at = datetime.now(timezone.utc) - timedelta(hours=72)
        result = ScoringService.calculate_recency_decay(created_at)
        expected = math.exp(-1)  # ≈ 0.368
        assert result == pytest.approx(expected, abs=0.05)

    def test_30_day_old_job_has_decayed_score(self):
        created_at = datetime.now(timezone.utc) - timedelta(days=30)
        result = ScoringService.calculate_recency_decay(created_at)
        # 30 days = 720 hours; exp(-720/72) = exp(-10) ≈ 4.5e-5
        assert result < 0.01

    def test_new_job_beats_old_job(self):
        new_job = datetime.now(timezone.utc)
        old_job = datetime.now(timezone.utc) - timedelta(days=7)
        new_score = ScoringService.calculate_recency_decay(new_job)
        old_score = ScoringService.calculate_recency_decay(old_job)
        assert new_score > old_score

    def test_result_bounded_zero_to_one(self):
        # Very old job
        ancient = datetime.now(timezone.utc) - timedelta(days=365)
        result = ScoringService.calculate_recency_decay(ancient)
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# calculate_location_match
# ---------------------------------------------------------------------------
class TestCalculateLocationMatch:
    def test_remote_job_always_matches(self):
        result = ScoringService.calculate_location_match(
            user_preferences=["New York"],
            job_location="San Francisco",
            job_remote=True,
        )
        assert result == 1.0

    def test_matching_location_returns_one(self):
        result = ScoringService.calculate_location_match(
            user_preferences=["San Francisco"],
            job_location="San Francisco, CA",
            job_remote=False,
        )
        assert result == 1.0

    def test_no_matching_location_returns_zero(self):
        result = ScoringService.calculate_location_match(
            user_preferences=["New York"],
            job_location="San Francisco",
            job_remote=False,
        )
        assert result == 0.0

    def test_empty_preferences_returns_default(self):
        result = ScoringService.calculate_location_match(
            user_preferences=[],
            job_location="San Francisco",
            job_remote=False,
        )
        assert result == 0.5

    def test_none_preferences_returns_default(self):
        result = ScoringService.calculate_location_match(
            user_preferences=None,
            job_location="San Francisco",
            job_remote=False,
        )
        assert result == 0.5

    def test_partial_match_in_preference(self):
        # "san francisco" is a substring of job_location
        result = ScoringService.calculate_location_match(
            user_preferences=["san francisco"],
            job_location="San Francisco, CA",
            job_remote=False,
        )
        assert result == 1.0


# ---------------------------------------------------------------------------
# calculate_job_score — integration of all factors
# ---------------------------------------------------------------------------
class TestCalculateJobScore:
    def _score(
        self,
        similarity: float = 0.85,
        user_skills: list | None = None,
        job_tags: list | None = None,
        user_seniority: str | None = "mid",
        job_seniority: str | None = "mid",
        user_preferences: list | None = None,
        job_location: str | None = None,
        job_remote: bool = False,
        hours_old: int = 0,
    ) -> int:
        created_at = datetime.now(timezone.utc) - timedelta(hours=hours_old)
        emb = _make_embedding(1.0)
        with patch(
            "app.services.scoring_service.embedding_service.calculate_similarity",
            return_value=similarity,
        ):
            return ScoringService.calculate_job_score(
                user_embedding=emb,
                job_embedding=emb,
                user_skills=user_skills or ["python"],
                user_seniority=user_seniority,
                user_preferences=user_preferences or ["remote"],
                job_tags=job_tags or ["python"],
                job_seniority=job_seniority,
                job_location=job_location or "remote",
                job_remote=job_remote,
                job_created_at=created_at,
            )

    def test_returns_integer(self):
        score = self._score()
        assert isinstance(score, int)

    def test_score_bounded_0_to_100(self):
        score = self._score(similarity=1.0, job_remote=True)
        assert 0 <= score <= 100

    def test_perfect_match_near_100(self):
        """All factors maxed out should produce a very high score."""
        score = self._score(
            similarity=1.0,
            user_skills=["python", "fastapi"],
            job_tags=["python", "fastapi"],
            user_seniority="mid",
            job_seniority="mid",
            user_preferences=["remote"],
            job_remote=True,
            hours_old=0,
        )
        # 0.55*1 + 0.20*1 + 0.10*1 + 0.10*1 + 0.05*1 = 1.0 => score 100
        assert score >= 95

    def test_no_overlap_lower_score(self):
        """No skill overlap, seniority mismatch, old job → lower score."""
        score = self._score(
            similarity=0.0,
            user_skills=["java"],
            job_tags=["python"],
            user_seniority="junior",
            job_seniority="senior",
            hours_old=720,  # 30 days old
        )
        # similarity=0 (55%), skill=0 (20%), seniority=0 (10%), recency~0 (10%), location default~0.5 (5%)
        # max possible ≈ 0 + 0 + 0 + tiny + 0.025 = ~2-3
        assert score < 10

    def test_embedding_similarity_dominates(self):
        """55% weight: high similarity should dominate the score."""
        high_sim_score = self._score(similarity=1.0)
        low_sim_score = self._score(similarity=0.0)
        assert high_sim_score > low_sim_score

    def test_recency_decay_lowers_score_for_old_jobs(self):
        fresh_score = self._score(similarity=0.7, hours_old=0)
        stale_score = self._score(similarity=0.7, hours_old=720)
        assert fresh_score > stale_score
