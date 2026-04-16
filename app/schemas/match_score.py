"""
B7.1 — Match Score schemas

Pydantic models for the Match Score Engine API responses.
"""
from __future__ import annotations

from typing import Optional, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class InsightItem(BaseModel):
    title: str
    evidence: str
    confidence: float
    source_layer: int


class InterviewQuestion(BaseModel):
    question: str
    rationale: str
    what_to_look_for: str
    gap_addressed: str


class HardMatchDetail(BaseModel):
    score: float
    passed_filter: bool
    skills_coverage: float = 0.0
    experience_score: float = 0.0
    education_score: float = 0.0
    language_score: float = 0.0
    missing_required_skills: list[str] = []


class SoftMatchDetail(BaseModel):
    score: float
    big_five_fit: float = 0.0
    mcclelland_culture_fit: float = 0.0
    appraisal_values_fit: float = 0.0
    career_narrative_fit: float = 0.0
    personality_distance: float = 0.0


class PredictiveMatchDetail(BaseModel):
    score: float
    hire_probability: float = 0.5
    retention_12m_probability: float = 0.5
    is_heuristic: bool = True


class MatchScoreResult(BaseModel):
    user_id: UUID
    job_id: UUID
    total_score: float
    confidence_multiplier: float
    final_effective_score: float
    hard_match: HardMatchDetail
    soft_match: SoftMatchDetail
    predictive_match: PredictiveMatchDetail
    top_strengths: list[InsightItem] = []
    top_alerts: list[InsightItem] = []
    interview_guide: list[InterviewQuestion] = []
    explanation_text: str = ""


class RecruiterDecision(BaseModel):
    decision: Literal["avanza", "descarta", "en_espera"]
    notes: Optional[str] = None


class CandidateRankingItem(BaseModel):
    user_id: UUID
    candidate_name: str
    avatar_url: Optional[str] = None
    primary_archetype: Optional[str] = None
    archetype_emoji: Optional[str] = None
    final_effective_score: float
    hard_match_score: float
    soft_match_score: float
    predictive_match_score: float
    top_strength: Optional[str] = None
    top_alert: Optional[str] = None
    recruiter_decision: Optional[str] = None
    puc_completeness: float = 0.0


class RankingResponse(BaseModel):
    job_id: UUID
    total: int
    page: int
    page_size: int
    has_more: bool
    candidates: list[CandidateRankingItem]


class HiringOutcomeCreate(BaseModel):
    """B9.1.1 — Payload for submitting a hiring outcome for a match score."""
    match_score_id: UUID
    performance_3m: Optional[float] = Field(None, ge=1, le=5)
    retention_3m: Optional[bool] = None
    notes_3m: Optional[str] = None
    performance_6m: Optional[float] = Field(None, ge=1, le=5)
    retention_6m: Optional[bool] = None
    notes_6m: Optional[str] = None
    failure_reason: Optional[str] = None


class HiringOutcomeRead(BaseModel):
    id: UUID
    match_score_id: UUID
    user_id: UUID
    job_id: UUID
    company_id: UUID
    performance_3m: Optional[float] = None
    retention_3m: Optional[bool] = None
    notes_3m: Optional[str] = None
    performance_6m: Optional[float] = None
    retention_6m: Optional[bool] = None
    notes_6m: Optional[str] = None
    was_successful_hire: Optional[bool] = None
    tenure_months: Optional[int] = None
    failure_reason: Optional[str] = None

    class Config:
        from_attributes = True
