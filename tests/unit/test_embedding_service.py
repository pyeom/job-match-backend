"""
Unit tests for EmbeddingService.

Heavy ML operations (model.encode) are mocked so these tests run without
downloading or loading the sentence-transformer model.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.services.embedding_service import EmbeddingService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _unit_vec(dims: int = 384, value: float = 1.0) -> list[float]:
    """Return a normalised vector of length ``dims`` with all values ``value``."""
    v = [value] * dims
    norm = math.sqrt(sum(x ** 2 for x in v))
    return [x / norm for x in v]


def _make_service_with_model() -> EmbeddingService:
    """Return an EmbeddingService whose internal model is a mock that returns a
    fixed numpy array from encode()."""
    svc = EmbeddingService()
    mock_model = MagicMock()
    mock_model.encode = MagicMock(return_value=np.array(_unit_vec()))
    svc._model = mock_model
    svc._load_attempted = True
    return svc


# ---------------------------------------------------------------------------
# calculate_similarity
# ---------------------------------------------------------------------------
class TestCalculateSimilarity:
    def setup_method(self):
        self.svc = EmbeddingService()

    def test_identical_vectors_return_one(self):
        vec = _unit_vec()
        result = self.svc.calculate_similarity(vec, vec)
        assert result == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors_return_zero(self):
        dims = 4
        vec1 = [1.0, 0.0, 0.0, 0.0]
        vec2 = [0.0, 1.0, 0.0, 0.0]
        result = self.svc.calculate_similarity(vec1, vec2)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_opposite_vectors_clamped_to_zero(self):
        vec = _unit_vec()
        neg_vec = [-v for v in vec]
        result = self.svc.calculate_similarity(vec, neg_vec)
        # Cosine of opposite vectors = -1; clamped to 0
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_zero_vector_returns_zero(self):
        vec = _unit_vec()
        zero = [0.0] * len(vec)
        result = self.svc.calculate_similarity(vec, zero)
        assert result == 0.0

    def test_result_between_zero_and_one(self):
        import random

        random.seed(42)
        dims = 384
        v1 = [random.uniform(-1, 1) for _ in range(dims)]
        v2 = [random.uniform(-1, 1) for _ in range(dims)]
        result = self.svc.calculate_similarity(v1, v2)
        assert 0.0 <= result <= 1.0

    def test_similarity_weight_55_percent(self):
        """Verify that the scoring service applies the 55% embedding weight."""
        from app.services.scoring_service import ScoringService
        from datetime import datetime, timezone

        with patch(
            "app.services.scoring_service.embedding_service.calculate_similarity",
            return_value=1.0,
        ) as mock_sim:
            score = ScoringService.calculate_job_score(
                user_embedding=[1.0] * 384,
                job_embedding=[1.0] * 384,
                user_skills=None,
                user_seniority=None,
                user_preferences=None,
                job_tags=None,
                job_seniority=None,
                job_location=None,
                job_remote=False,
                job_created_at=datetime.now(timezone.utc),
            )
            mock_sim.assert_called_once()
        # With similarity=1, skill=0, seniority=0.5, recency~1, location=0.5:
        # 0.55 + 0 + 0.05 + 0.10 + 0.025 = 0.725 => 72-73
        assert score >= 70


# ---------------------------------------------------------------------------
# generate_user_embedding
# ---------------------------------------------------------------------------
class TestGenerateUserEmbedding:
    def test_empty_profile_returns_zero_vector(self):
        svc = EmbeddingService()
        # No model needed — the method returns zeros when all inputs are empty
        result = svc.generate_user_embedding()
        assert result == [0.0] * 384

    def test_returns_list_of_floats(self):
        svc = _make_service_with_model()
        result = svc.generate_user_embedding(
            headline="Senior Python Developer",
            skills=["python", "fastapi"],
        )
        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)
        assert len(result) == 384

    def test_model_encode_called(self):
        svc = _make_service_with_model()
        svc.generate_user_embedding(headline="Test", skills=["python"])
        svc._model.encode.assert_called_once()

    def test_bio_truncated_to_150_chars(self):
        svc = _make_service_with_model()
        long_bio = "x" * 500
        svc.generate_user_embedding(bio=long_bio)
        call_args = svc._model.encode.call_args[0][0]
        # Each part is joined with " | "; the bio part should be ≤ 150 chars
        bio_part = call_args.split(" | ")[0]
        assert len(bio_part) <= 150


# ---------------------------------------------------------------------------
# generate_job_embedding_from_parts
# ---------------------------------------------------------------------------
class TestGenerateJobEmbeddingFromParts:
    def test_returns_list_of_floats(self):
        svc = _make_service_with_model()
        result = svc.generate_job_embedding_from_parts(
            title="Backend Engineer",
            company="Acme",
            tags=["python", "docker"],
        )
        assert isinstance(result, list)
        assert len(result) == 384

    def test_description_truncated_to_500(self):
        svc = _make_service_with_model()
        long_desc = "y" * 600
        svc.generate_job_embedding_from_parts(
            title="Eng", company="Corp", description=long_desc
        )
        call_args = svc._model.encode.call_args[0][0]
        # The combined text must not contain 600-char segment
        assert len(long_desc) not in [len(part) for part in call_args.split(" | ")]

    def test_short_description_preferred_over_description(self):
        svc = _make_service_with_model()
        svc.generate_job_embedding_from_parts(
            title="Eng",
            company="Corp",
            short_description="Short",
            description="Long description that should not be used",
        )
        call_args = svc._model.encode.call_args[0][0]
        assert "Short" in call_args


# ---------------------------------------------------------------------------
# update_user_embedding_with_history
# ---------------------------------------------------------------------------
class TestUpdateUserEmbeddingWithHistory:
    def setup_method(self):
        self.svc = EmbeddingService()

    def test_empty_history_returns_base(self):
        base = [1.0] + [0.0] * 383
        result = self.svc.update_user_embedding_with_history(base, [])
        assert result == base

    def test_output_is_normalised(self):
        base = [1.0] + [0.0] * 383
        history = [[0.0, 1.0] + [0.0] * 382]
        result = self.svc.update_user_embedding_with_history(base, history)
        norm = math.sqrt(sum(v ** 2 for v in result))
        assert norm == pytest.approx(1.0, abs=1e-5)

    def test_blends_with_default_weights(self):
        """Default: 0.3 profile + 0.7 history."""
        dims = 4
        base = [1.0, 0.0, 0.0, 0.0]
        history = [[0.0, 1.0, 0.0, 0.0]]
        result = self.svc.update_user_embedding_with_history(base, history)
        result_arr = np.array(result)
        # Expect a mix tilted towards history direction
        assert result_arr[0] < result_arr[1]

    def test_alpha_override_respected(self):
        """alpha=1.0 means 100% profile, 0% history."""
        base = [1.0] + [0.0] * 383
        history = [[0.0, 1.0] + [0.0] * 382]
        result = self.svc.update_user_embedding_with_history(base, history, alpha=1.0)
        # With alpha=1 the result should be colinear with base
        result_arr = np.array(result)
        base_arr = np.array(base)
        norm_base = np.linalg.norm(base_arr)
        dot = np.dot(result_arr, base_arr / norm_base)
        assert dot > 0.99

    def test_output_length_matches_input(self):
        dims = 384
        base = [1.0] * dims
        history = [[0.5] * dims]
        result = self.svc.update_user_embedding_with_history(base, history)
        assert len(result) == dims


# ---------------------------------------------------------------------------
# build_experience_summary / build_education_summary
# ---------------------------------------------------------------------------
class TestBuildSummaries:
    def setup_method(self):
        self.svc = EmbeddingService()

    def test_experience_summary_from_dict(self):
        exp = [
            {"title": "Engineer", "company": "Acme", "description": "Built stuff"},
        ]
        result = self.svc.build_experience_summary(exp)
        assert "Engineer at Acme" in result

    def test_experience_summary_truncates_description(self):
        exp = [{"title": "Eng", "company": "Co", "description": "x" * 200}]
        result = self.svc.build_experience_summary(exp)
        # description is truncated to 80 chars in the summary
        assert len(result) < 200

    def test_experience_summary_empty_returns_none(self):
        result = self.svc.build_experience_summary([])
        assert result is None

    def test_education_summary_from_dict(self):
        edu = [
            {
                "degree": "BSc",
                "field_of_study": "Computer Science",
                "institution": "MIT",
            }
        ]
        result = self.svc.build_education_summary(edu)
        assert "BSc" in result
        assert "MIT" in result

    def test_education_summary_empty_returns_none(self):
        result = self.svc.build_education_summary([])
        assert result is None

    def test_only_top_3_experiences_used(self):
        exp = [
            {"title": f"Job{i}", "company": f"Co{i}", "description": ""}
            for i in range(6)
        ]
        result = self.svc.build_experience_summary(exp)
        # Only top 3 should appear
        assert "Job0" in result
        assert "Job1" in result
        assert "Job2" in result
        assert "Job3" not in result
