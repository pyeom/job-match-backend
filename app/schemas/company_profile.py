from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# B6.1.1  OrgProfileCreate — raw text inputs from the company wizard (E1–E4)
# ---------------------------------------------------------------------------

class OrgProfileCreate(BaseModel):
    e1_culture_text: str = Field(..., min_length=50, max_length=3000)
    e2_no_fit_text: str = Field(..., min_length=30, max_length=2000)
    e3_decision_style_text: str = Field(..., min_length=30, max_length=2000)
    e4_best_hire_text: str = Field(..., min_length=30, max_length=2000)


# ---------------------------------------------------------------------------
# B6.1.2  OrgProfileRead — full inferred profile returned to the client
# ---------------------------------------------------------------------------

class OrgProfileRead(BaseModel):
    id: UUID
    company_id: UUID

    # Raw inputs (echo back for review/editing)
    e1_culture_text: Optional[str] = None
    e2_no_fit_text: Optional[str] = None
    e3_decision_style_text: Optional[str] = None
    e4_best_hire_text: Optional[str] = None

    # Analysis status
    status: Literal["analyzing", "completed", "failed"] = "analyzing"

    # E1 → culture & sentiment
    culture_valence: Optional[float] = None          # -1 negative → +1 positive
    affiliation_vs_achievement: Optional[float] = None  # -1 affiliation → +1 achievement
    hierarchy_score: Optional[float] = None          # 0 flat → 1 hierarchical

    # E3 → management style
    management_archetype: Optional[str] = None       # autocrático | consultivo | democrático | laissez

    # Big Five organizational implicit profile (0–100)
    org_openness: Optional[float] = None
    org_conscientiousness: Optional[float] = None
    org_extraversion: Optional[float] = None
    org_agreeableness: Optional[float] = None
    org_stability: Optional[float] = None

    # E2 → deal-breakers derived from anti-fit text
    cultural_deal_breakers: Optional[list[str]] = None
    anti_profile_signals: Optional[dict] = None     # {trait: max_threshold}

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# B6.1.3  JobMatchConfigCreate — E5–E9 + hard filters + weights
# ---------------------------------------------------------------------------

class JobMatchConfigCreate(BaseModel):
    # Qualitative answers
    e5_skills_vs_attitude: str = Field(..., min_length=30, max_length=2000)
    e6_team_description: str = Field(..., min_length=30, max_length=2000)
    e7_first_90_days: str = Field(..., min_length=30, max_length=2000)
    e8_success_signal: str = Field(..., min_length=30, max_length=2000)
    e9_failure_profile: str = Field(..., min_length=30, max_length=2000)

    # Hard match filters
    min_experience_years: int = Field(0, ge=0, le=30)
    required_education_level: Optional[str] = None
    required_languages: list[str] = []
    hard_skills_required: list[str] = []
    hard_skills_desired: list[str] = []

    # Interview config
    interview_type: Literal["técnica", "conductual", "panel"] = "conductual"
    portfolio_required: bool = False

    # Match weights (auto-adjusted from E5, but caller can override)
    weight_hard: float = Field(0.50, ge=0.0, le=1.0)
    weight_soft: float = Field(0.30, ge=0.0, le=1.0)
    weight_predictive: float = Field(0.20, ge=0.0, le=1.0)

    # Optional Big Five minimums (0–100) — set manually or via infer endpoint
    req_openness_min: float = Field(0.0, ge=0.0, le=100.0)
    req_conscientiousness_min: float = Field(0.0, ge=0.0, le=100.0)
    req_extraversion_min: float = Field(0.0, ge=0.0, le=100.0)
    req_agreeableness_min: float = Field(0.0, ge=0.0, le=100.0)
    req_stability_min: float = Field(0.0, ge=0.0, le=100.0)

    @field_validator("weight_predictive")
    @classmethod
    def weights_must_sum_to_one(cls, v: float, info) -> float:
        w_hard = info.data.get("weight_hard", 0.0)
        w_soft = info.data.get("weight_soft", 0.0)
        total = w_hard + w_soft + v
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0 (got {total:.2f})")
        return v


# ---------------------------------------------------------------------------
# JobMatchConfigRead — full config + preview of inferred job vector
# ---------------------------------------------------------------------------

class BigFiveMinimums(BaseModel):
    openness: float = 0.0
    conscientiousness: float = 0.0
    extraversion: float = 0.0
    agreeableness: float = 0.0
    stability: float = 0.0


class JobMatchConfigRead(BaseModel):
    id: UUID
    job_id: UUID

    # Raw E5–E9 texts
    e5_skills_vs_attitude: Optional[str] = None
    e6_team_description: Optional[str] = None
    e7_first_90_days: Optional[str] = None
    e8_success_signal: Optional[str] = None
    e9_failure_profile: Optional[str] = None

    # Big Five minimums (inferred or manually set)
    req_openness_min: float = 0.0
    req_conscientiousness_min: float = 0.0
    req_extraversion_min: float = 0.0
    req_agreeableness_min: float = 0.0
    req_stability_min: float = 0.0

    # Weights
    weight_hard: float = 0.50
    weight_soft: float = 0.30
    weight_predictive: float = 0.20

    # Hard filters
    min_experience_years: int = 0
    required_education_level: Optional[str] = None
    required_languages: list[str] = []
    hard_skills_required: list[str] = []
    hard_skills_desired: list[str] = []

    # Interview
    interview_type: str = "conductual"
    portfolio_required: bool = False

    # Derived
    ideal_archetype: Optional[str] = None
    anti_profile_vector: Optional[dict] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Preview — returned by GET /match-config/preview
# ---------------------------------------------------------------------------

class ArchetypeAdvantage(BaseModel):
    archetype: str
    score_boost: str   # e.g. "+15 pts"
    reason: str


class JobVectorPreview(BaseModel):
    job_id: UUID
    big_five_minimums: BigFiveMinimums
    weight_hard: float
    weight_soft: float
    weight_predictive: float
    ideal_archetype: Optional[str]
    archetype_advantages: list[ArchetypeAdvantage] = []
    anti_profile_summary: Optional[str] = None
    config: JobMatchConfigRead
