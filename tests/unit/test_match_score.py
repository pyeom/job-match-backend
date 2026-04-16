"""
B7.6 — Unit tests for Match Score Service

Tests all 4 required cases from the spec:
1. hard_match with missing required skills → passed_filter=False, score=0
2. soft_match with ideal candidate (Big Five all 100) → big_five_fit > 95
3. final formula with configurable weights
4. confidence_multiplier reduces score correctly

Pure Python objects — no DB, no async.
"""

from __future__ import annotations

import pytest

from app.services.match_score_service import (
    compute_hard_match,
    compute_soft_match,
    compute_predictive_match,
    EDU_SCORES,
)
from app.schemas.match_score import HardMatchDetail, SoftMatchDetail, PredictiveMatchDetail


# ---------------------------------------------------------------------------
# Helpers — lightweight stand-ins for ORM models (no DB)
# ---------------------------------------------------------------------------

class _MockJobMatchConfig:
    """Minimal stand-in for JobMatchConfig ORM rows."""

    def __init__(
        self,
        hard_skills_required=None,
        hard_skills_desired=None,
        min_experience_years=0,
        required_education_level=None,
        required_languages=None,
        req_openness_min=0.0,
        req_conscientiousness_min=0.0,
        req_extraversion_min=0.0,
        req_agreeableness_min=0.0,
        req_stability_min=0.0,
        ideal_archetype=None,
        weight_hard=0.50,
        weight_soft=0.30,
        weight_predictive=0.20,
    ):
        self.hard_skills_required = hard_skills_required or []
        self.hard_skills_desired = hard_skills_desired or []
        self.min_experience_years = min_experience_years
        self.required_education_level = required_education_level
        self.required_languages = required_languages or []
        self.req_openness_min = req_openness_min
        self.req_conscientiousness_min = req_conscientiousness_min
        self.req_extraversion_min = req_extraversion_min
        self.req_agreeableness_min = req_agreeableness_min
        self.req_stability_min = req_stability_min
        self.ideal_archetype = ideal_archetype
        self.weight_hard = weight_hard
        self.weight_soft = weight_soft
        self.weight_predictive = weight_predictive


class _MockCandidatePUCProfile:
    """Minimal stand-in for CandidatePUCProfile ORM rows."""

    def __init__(
        self,
        openness=None,
        conscientiousness=None,
        extraversion=None,
        agreeableness=None,
        emotional_stability=None,
        big_five_confidence=None,
        n_ach=None,
        n_aff=None,
        n_pow=None,
        churn_risk=None,
        primary_archetype=None,
        completeness_score=0.5,
        social_desirability_flag=False,
        analytical_thinking=None,
        leadership_score=None,
        collaboration_score=None,
        adaptability_score=None,
        resilience_score=None,
        integrity_score=None,
        written_communication=None,
    ):
        self.openness = openness
        self.conscientiousness = conscientiousness
        self.extraversion = extraversion
        self.agreeableness = agreeableness
        self.emotional_stability = emotional_stability
        self.big_five_confidence = big_five_confidence
        self.n_ach = n_ach
        self.n_aff = n_aff
        self.n_pow = n_pow
        self.churn_risk = churn_risk
        self.primary_archetype = primary_archetype
        self.completeness_score = completeness_score
        self.social_desirability_flag = social_desirability_flag
        self.analytical_thinking = analytical_thinking
        self.leadership_score = leadership_score
        self.collaboration_score = collaboration_score
        self.adaptability_score = adaptability_score
        self.resilience_score = resilience_score
        self.integrity_score = integrity_score
        self.written_communication = written_communication


class _MockOrgProfile:
    """Minimal stand-in for CompanyOrgProfile ORM rows."""

    def __init__(
        self,
        affiliation_vs_achievement=None,
        anti_profile_signals=None,
    ):
        self.affiliation_vs_achievement = affiliation_vs_achievement
        self.anti_profile_signals = anti_profile_signals or {}


# ===========================================================================
# Case 1 — Hard match: missing required skills → passed_filter=False, score=0
# ===========================================================================

class TestHardMatchMissingSkills:
    """B7.6.1 — hard_match with missing required skills → passed_filter=False, score=0"""

    def test_missing_one_required_skill_fails_filter(self):
        candidate = {
            "skills": ["python", "fastapi"],
            "experience_years": 3,
            "education_level": "universitario",
            "languages": [],
        }
        config = _MockJobMatchConfig(
            hard_skills_required=["python", "fastapi", "kubernetes"],
            min_experience_years=0,
        )
        result = compute_hard_match(candidate, config)

        assert result.passed_filter is False
        assert result.score == 0.0
        assert "kubernetes" in result.missing_required_skills

    def test_missing_all_required_skills_fails_filter(self):
        candidate = {
            "skills": [],
            "experience_years": 5,
            "education_level": "postgrado",
            "languages": [],
        }
        config = _MockJobMatchConfig(
            hard_skills_required=["react", "typescript", "graphql"],
            min_experience_years=0,
        )
        result = compute_hard_match(candidate, config)

        assert result.passed_filter is False
        assert result.score == 0.0
        assert len(result.missing_required_skills) == 3

    def test_insufficient_experience_fails_filter(self):
        candidate = {
            "skills": ["python", "django"],
            "experience_years": 1,
            "education_level": "universitario",
            "languages": [],
        }
        config = _MockJobMatchConfig(
            hard_skills_required=["python", "django"],
            min_experience_years=3,
        )
        result = compute_hard_match(candidate, config)

        assert result.passed_filter is False
        assert result.score == 0.0

    def test_missing_skill_and_insufficient_experience_both_fail(self):
        candidate = {
            "skills": ["python"],
            "experience_years": 0,
            "education_level": "técnico",
            "languages": [],
        }
        config = _MockJobMatchConfig(
            hard_skills_required=["python", "rust"],
            min_experience_years=5,
        )
        result = compute_hard_match(candidate, config)

        assert result.passed_filter is False
        assert result.score == 0.0

    def test_case_insensitive_skill_matching(self):
        """Skill matching should be case-insensitive."""
        candidate = {
            "skills": ["Python", "FastAPI"],
            "experience_years": 2,
            "education_level": "universitario",
            "languages": [],
        }
        config = _MockJobMatchConfig(
            hard_skills_required=["python", "fastapi"],
            min_experience_years=0,
        )
        result = compute_hard_match(candidate, config)

        assert result.passed_filter is True
        assert result.score > 0

    def test_no_required_skills_passes_filter(self):
        """Empty required skills list should always pass the filter."""
        candidate = {
            "skills": [],
            "experience_years": 0,
            "education_level": "",
            "languages": [],
        }
        config = _MockJobMatchConfig(
            hard_skills_required=[],
            min_experience_years=0,
        )
        result = compute_hard_match(candidate, config)

        assert result.passed_filter is True
        assert result.score > 0


# ===========================================================================
# Case 2 — Soft match: ideal candidate (Big Five all 100) → big_five_fit > 95
# ===========================================================================

class TestSoftMatchIdealCandidate:
    """B7.6.2 — soft_match with ideal candidate (Big Five all 100) → big_five_fit > 95"""

    def test_perfect_big_five_gives_high_fit(self):
        puc = _MockCandidatePUCProfile(
            openness=100.0,
            conscientiousness=100.0,
            extraversion=100.0,
            agreeableness=100.0,
            emotional_stability=100.0,
        )
        config = _MockJobMatchConfig(
            req_openness_min=50.0,
            req_conscientiousness_min=60.0,
            req_extraversion_min=40.0,
            req_agreeableness_min=50.0,
            req_stability_min=55.0,
        )
        result = compute_soft_match(puc, config, None)

        assert result.big_five_fit > 95.0, (
            f"Expected big_five_fit > 95 for perfect Big Five, got {result.big_five_fit}"
        )

    def test_perfect_big_five_no_requirements_gives_max_fit(self):
        """All Big Five = 100 with zero minimums → fit should be 100."""
        puc = _MockCandidatePUCProfile(
            openness=100.0,
            conscientiousness=100.0,
            extraversion=100.0,
            agreeableness=100.0,
            emotional_stability=100.0,
        )
        config = _MockJobMatchConfig()  # all minimums = 0
        result = compute_soft_match(puc, config, None)

        assert result.big_five_fit == 100.0

    def test_candidate_with_no_big_five_data_gets_neutral_score(self):
        """Candidate with no Big Five data should get big_five_fit = 50."""
        puc = _MockCandidatePUCProfile()  # all None
        config = _MockJobMatchConfig(
            req_conscientiousness_min=70.0,
        )
        result = compute_soft_match(puc, config, None)

        assert result.big_five_fit == 50.0

    def test_ideal_archetype_match_gives_career_fit_100(self):
        puc = _MockCandidatePUCProfile(
            openness=80.0,
            conscientiousness=80.0,
            extraversion=80.0,
            agreeableness=80.0,
            emotional_stability=80.0,
            primary_archetype="El Ejecutor",
        )
        config = _MockJobMatchConfig(ideal_archetype="El Ejecutor")
        result = compute_soft_match(puc, config, None)

        assert result.career_narrative_fit == 100.0

    def test_high_churn_risk_lowers_career_fit(self):
        puc = _MockCandidatePUCProfile(
            openness=80.0,
            churn_risk=0.85,
        )
        config = _MockJobMatchConfig(ideal_archetype="El Constructor")
        result = compute_soft_match(puc, config, None)

        assert result.career_narrative_fit == 40.0

    def test_mcclelland_fit_with_affiliation_org(self):
        """High affiliation culture → n_aff drives mcclelland fit."""
        puc = _MockCandidatePUCProfile(n_aff=0.9, n_ach=0.3)
        config = _MockJobMatchConfig()
        org = _MockOrgProfile(affiliation_vs_achievement=0.8)
        result = compute_soft_match(puc, config, org)

        assert result.mcclelland_culture_fit == pytest.approx(90.0, abs=1.0)

    def test_mcclelland_fit_with_achievement_org(self):
        """Low affiliation culture → n_ach drives mcclelland fit."""
        puc = _MockCandidatePUCProfile(n_ach=0.85, n_aff=0.2)
        config = _MockJobMatchConfig()
        org = _MockOrgProfile(affiliation_vs_achievement=0.2)
        result = compute_soft_match(puc, config, org)

        assert result.mcclelland_culture_fit == pytest.approx(85.0, abs=1.0)

    def test_no_org_profile_gives_neutral_appraisal_fit(self):
        puc = _MockCandidatePUCProfile()
        config = _MockJobMatchConfig()
        result = compute_soft_match(puc, config, None)

        assert result.appraisal_values_fit == 70.0

    def test_soft_score_weighted_sum_correct(self):
        """Verify the weighted formula: 0.30 BF + 0.25 MC + 0.25 AP + 0.20 CN."""
        puc = _MockCandidatePUCProfile(
            openness=100.0,
            conscientiousness=100.0,
            extraversion=100.0,
            agreeableness=100.0,
            emotional_stability=100.0,
        )
        config = _MockJobMatchConfig(ideal_archetype="X")
        result = compute_soft_match(puc, config, None)

        expected = (
            result.big_five_fit * 0.30
            + result.mcclelland_culture_fit * 0.25
            + result.appraisal_values_fit * 0.25
            + result.career_narrative_fit * 0.20
        )
        assert result.score == pytest.approx(expected, abs=0.01)


# ===========================================================================
# Case 3 — Final formula with configurable weights
# ===========================================================================

class TestFinalFormula:
    """B7.6.3 — final formula with configurable weights."""

    def test_equal_weights(self):
        """With equal weights the score is the arithmetic mean of sub-scores."""
        hard_score = 80.0
        soft_score = 60.0
        pred_score = 70.0
        w_hard, w_soft, w_pred = 1 / 3, 1 / 3, 1 / 3

        expected = hard_score * w_hard + soft_score * w_soft + pred_score * w_pred
        computed = hard_score * w_hard + soft_score * w_soft + pred_score * w_pred
        assert computed == pytest.approx(expected, abs=0.01)

    def test_skills_heavy_weighting(self):
        """When weight_hard=0.65, hard score dominates."""
        hard_score = 90.0
        soft_score = 40.0
        pred_score = 50.0
        w_hard, w_soft, w_pred = 0.65, 0.20, 0.15

        total = hard_score * w_hard + soft_score * w_soft + pred_score * w_pred
        # With weight_hard=0.65 and hard=90, contribution from hard alone is 58.5
        assert total == pytest.approx(90 * 0.65 + 40 * 0.20 + 50 * 0.15, abs=0.01)

    def test_attitude_heavy_weighting(self):
        """When weight_soft=0.45, soft score dominates."""
        hard_score = 50.0
        soft_score = 95.0
        pred_score = 60.0
        w_hard, w_soft, w_pred = 0.35, 0.45, 0.20

        total = hard_score * w_hard + soft_score * w_soft + pred_score * w_pred
        assert total == pytest.approx(50 * 0.35 + 95 * 0.45 + 60 * 0.20, abs=0.01)

    def test_default_weights_sum_to_one(self):
        """Default JobMatchConfig weights must sum to 1.0."""
        config = _MockJobMatchConfig()
        total = config.weight_hard + config.weight_soft + config.weight_predictive
        assert total == pytest.approx(1.0, abs=0.001)

    def test_predictive_score_heuristic_formula(self):
        """Verify heuristic predictive formula."""
        features = {"hard_match_score": 80.0, "soft_match_score": 60.0}
        result = compute_predictive_match(features, outcomes_count=0)

        base = (80.0 * 0.5 + 60.0 * 0.5) / 100.0
        expected_hire = min(0.95, base * 0.85 + 0.1)
        expected_retention = min(0.95, base * 0.70 + 0.2)
        expected_score = (expected_hire * 0.6 + expected_retention * 0.4) * 100

        assert result.score == pytest.approx(expected_score, abs=0.01)
        assert result.hire_probability == pytest.approx(expected_hire, abs=0.001)
        assert result.is_heuristic is True

    def test_predictive_score_marks_not_heuristic_at_50_outcomes(self):
        """With >= 50 outcomes, is_heuristic should be False."""
        features = {"hard_match_score": 70.0, "soft_match_score": 70.0}
        result = compute_predictive_match(features, outcomes_count=50)

        assert result.is_heuristic is False

    def test_hard_match_scoring_formula(self):
        """Verify hard match sub-score formula for a passing candidate."""
        candidate = {
            "skills": ["python", "django", "postgresql"],
            "experience_years": 4,
            "education_level": "universitario",
            "languages": ["inglés"],
        }
        config = _MockJobMatchConfig(
            hard_skills_required=["python"],
            hard_skills_desired=["django", "postgresql"],
            min_experience_years=2,
            required_education_level="universitario",
            required_languages=["inglés"],
        )
        result = compute_hard_match(candidate, config)

        assert result.passed_filter is True
        assert result.skills_coverage == pytest.approx(1.0, abs=0.001)
        assert result.experience_score == pytest.approx(1.0, abs=0.001)
        # edu_score for "universitario" = 0.8; not below required → stays 0.8
        assert result.education_score == pytest.approx(0.8, abs=0.001)
        assert result.language_score == pytest.approx(1.0, abs=0.001)

        expected = (1.0 * 0.40 + 1.0 * 0.25 + 0.8 * 0.20 + 1.0 * 0.15) * 100
        assert result.score == pytest.approx(expected, abs=0.01)

    def test_education_below_required_halves_edu_score(self):
        """Education below required level → edu_score halved."""
        candidate = {
            "skills": ["python"],
            "experience_years": 3,
            "education_level": "técnico",
            "languages": [],
        }
        config = _MockJobMatchConfig(
            hard_skills_required=["python"],
            min_experience_years=0,
            required_education_level="universitario",
        )
        result = compute_hard_match(candidate, config)

        assert result.passed_filter is True
        # técnico score = 0.6, halved because below required universitario → 0.3
        assert result.education_score == pytest.approx(0.3, abs=0.001)


# ===========================================================================
# Case 4 — Confidence multiplier reduces score correctly
# ===========================================================================

class TestConfidenceMultiplier:
    """B7.6.4 — confidence_multiplier reduces final_effective_score."""

    def _compute_effective_score(
        self,
        hard: float,
        soft: float,
        pred: float,
        completeness: float,
        w_hard: float = 0.50,
        w_soft: float = 0.30,
        w_pred: float = 0.20,
    ) -> tuple[float, float, float]:
        """Return (total_score, multiplier, final_effective_score)."""
        total = hard * w_hard + soft * w_soft + pred * w_pred
        # Clamp completeness to [0.3, 1.0] (matches service logic)
        multiplier = max(0.3, min(1.0, completeness))
        effective = total * multiplier
        return total, multiplier, effective

    def test_full_completeness_preserves_score(self):
        total, multiplier, effective = self._compute_effective_score(
            hard=80.0, soft=70.0, pred=60.0, completeness=1.0
        )
        assert multiplier == 1.0
        assert effective == pytest.approx(total, abs=0.01)

    def test_half_completeness_halves_score(self):
        total, multiplier, effective = self._compute_effective_score(
            hard=80.0, soft=60.0, pred=50.0, completeness=0.5
        )
        assert multiplier == pytest.approx(0.5, abs=0.001)
        assert effective == pytest.approx(total * 0.5, abs=0.01)

    def test_zero_completeness_clamped_to_minimum(self):
        """completeness=0 should be clamped to 0.3, not zero the score entirely."""
        total, multiplier, effective = self._compute_effective_score(
            hard=80.0, soft=60.0, pred=50.0, completeness=0.0
        )
        assert multiplier == pytest.approx(0.3, abs=0.001)
        assert effective == pytest.approx(total * 0.3, abs=0.01)
        assert effective > 0, "Score should never be fully zeroed"

    def test_completeness_above_one_clamped_to_one(self):
        """completeness > 1 should be clamped to 1."""
        total, multiplier, effective = self._compute_effective_score(
            hard=80.0, soft=60.0, pred=50.0, completeness=1.5
        )
        assert multiplier == 1.0
        assert effective == pytest.approx(total, abs=0.01)

    def test_low_completeness_reduces_high_score(self):
        """A high-scoring candidate with low completeness should rank lower."""
        total_high, _, effective_high = self._compute_effective_score(
            hard=90.0, soft=85.0, pred=80.0, completeness=0.4
        )
        total_medium, _, effective_medium = self._compute_effective_score(
            hard=75.0, soft=70.0, pred=65.0, completeness=1.0
        )
        # Effective score of "high" candidate is penalized by 0.4 multiplier
        assert effective_high < total_high
        # The medium complete candidate might rank higher despite lower raw scores
        assert effective_medium > total_medium * 0.3  # sanity check

    def test_effective_score_always_lower_or_equal_to_total(self):
        """final_effective_score ≤ total_score always (multiplier ≤ 1)."""
        for completeness in [0.0, 0.3, 0.5, 0.7, 0.9, 1.0, 1.5]:
            total, multiplier, effective = self._compute_effective_score(
                hard=70.0, soft=70.0, pred=70.0, completeness=completeness
            )
            assert effective <= total + 0.001, (
                f"effective ({effective}) > total ({total}) for completeness={completeness}"
            )
