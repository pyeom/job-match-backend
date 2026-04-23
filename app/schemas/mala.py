from __future__ import annotations
from enum import Enum
from typing import Optional, Literal
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

from app.services.nlp.text_quality import TextQualityResult


class QuestionBlock(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class QuestionSchema(BaseModel):
    code: str
    block: QuestionBlock
    block_name: str
    text: str
    guidance: str
    min_words_recommended: int
    time_guidance_seconds: int
    order_in_block: int


class MalaResponseCreate(BaseModel):
    question_code: str = Field(..., pattern=r"^P(1[0-2]|[1-9])$")
    response_text: str = Field(..., min_length=10, max_length=5000)

    @field_validator("response_text")
    @classmethod
    def strip_and_clean(cls, v: str) -> str:
        return v.strip()


class MalaResponseRead(BaseModel):
    id: UUID
    question_code: str
    question_block: str
    response_text: str
    quality_score: Optional[float] = None
    token_count: Optional[int] = None
    word_count: Optional[int] = None
    processing_status: str
    created_at: datetime
    updated_at: datetime
    layer_results: Optional[dict] = None

    model_config = {"from_attributes": True}


class BlockStatus(BaseModel):
    answered: int
    total: int
    is_complete: bool


class MalaProgressSchema(BaseModel):
    questions_answered: int
    questions_total: int = 12
    completion_percentage: float
    puc_completeness: float
    confidence_level: str
    blocks_status: dict[str, BlockStatus]
    next_recommended_question: Optional[str] = None


class MalaResponseSubmitResult(BaseModel):
    response_id: UUID
    quality_result: TextQualityResult
    processing_job_id: str
    next_question_code: Optional[str] = None
    progress: MalaProgressSchema


# ── Archetype endpoint schemas ─────────────────────────────────────────────────

class ArchetypeDataSchema(BaseModel):
    """Non-translatable visual metadata for an archetype.

    Display strings (name, strengths, risks, ideal_cultures, matching_note)
    are resolved client-side via i18n keys ``archetypes.<id>.*``.
    """

    emoji: str
    color: str


class BigFiveSchema(BaseModel):
    openness: float
    conscientiousness: float
    extraversion: float
    agreeableness: float
    emotional_stability: float


class ArchetypeResponseSchema(BaseModel):
    primary_archetype: str
    probabilities: dict[str, float]
    is_hybrid: bool
    hybrid_description: Optional[str] = None
    stability_warning: bool
    archetype_data: ArchetypeDataSchema
    big_five: Optional[BigFiveSchema] = None
    completeness_score: float
