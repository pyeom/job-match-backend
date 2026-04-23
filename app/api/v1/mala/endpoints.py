from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_job_seeker
from app.core.arq import get_arq_pool
from app.core.database import get_db
from app.data.archetype_metadata import ARCHETYPE_METADATA
from app.data.mala_questions import (
    MALA_QUESTIONS,
    get_next_question,
    get_question_by_code,
    get_questions_by_block,
)
from app.models.mala import CandidateMalaResponse, CandidatePUCProfile
from app.models.user import User
from app.repositories.mala_response_repository import MalaResponseRepository
from app.repositories.puc_profile_repository import PUCProfileRepository
from app.schemas.mala import (
    ArchetypeDataSchema,
    ArchetypeResponseSchema,
    BigFiveSchema,
    BlockStatus,
    MalaProgressSchema,
    MalaResponseCreate,
    MalaResponseRead,
    MalaResponseSubmitResult,
    QuestionBlock,
    QuestionSchema,
)
from app.services.nlp.text_quality import TextQualityValidator

logger = logging.getLogger(__name__)

router = APIRouter()

_mala_repo = MalaResponseRepository()
_puc_repo = PUCProfileRepository()
_text_validator = TextQualityValidator()


def _build_progress(
    responses: list[CandidateMalaResponse],
    puc_profile: Optional[CandidatePUCProfile],
) -> MalaProgressSchema:
    answered_codes = [r.question_code for r in responses]
    answered_set = set(answered_codes)
    questions_answered = len(answered_set)
    questions_total = 12

    blocks_status: dict[str, BlockStatus] = {}
    for block in QuestionBlock:
        block_questions = get_questions_by_block(block)
        block_total = len(block_questions)
        block_answered = sum(1 for q in block_questions if q.code in answered_set)
        blocks_status[block.value] = BlockStatus(
            answered=block_answered,
            total=block_total,
            is_complete=block_answered == block_total,
        )

    completion_percentage = round((questions_answered / questions_total) * 100, 1)

    puc_completeness = 0.0
    confidence_level = "low"
    if puc_profile:
        puc_completeness = puc_profile.completeness_score or 0.0
        confidence_level = puc_profile.confidence_level or "low"
    elif questions_answered >= 8:
        confidence_level = "medium"
    elif questions_answered >= 4:
        confidence_level = "low"

    next_q = get_next_question(answered_codes)
    next_code = next_q.code if next_q else None

    return MalaProgressSchema(
        questions_answered=questions_answered,
        questions_total=questions_total,
        completion_percentage=completion_percentage,
        puc_completeness=puc_completeness,
        confidence_level=confidence_level,
        blocks_status=blocks_status,
        next_recommended_question=next_code,
    )


@router.get("/questions", response_model=list[QuestionSchema])
async def list_questions(
    block: Optional[QuestionBlock] = Query(None),
    current_user: User = Depends(get_job_seeker),
) -> list[QuestionSchema]:
    if block is not None:
        return get_questions_by_block(block)
    return MALA_QUESTIONS


@router.get("/questions/progress", response_model=MalaProgressSchema)
async def get_progress(
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db),
) -> MalaProgressSchema:
    responses = await _mala_repo.get_by_user_id(db, current_user.id)
    puc_profile = await _puc_repo.get_by_user_id(db, current_user.id)
    return _build_progress(responses, puc_profile)


@router.post("/responses", response_model=MalaResponseSubmitResult)
async def submit_response(
    body: MalaResponseCreate,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db),
) -> MalaResponseSubmitResult:
    question = get_question_by_code(body.question_code)
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question {body.question_code} not found.",
        )

    quality_result = _text_validator.validate(body.response_text, body.question_code)
    if quality_result.is_too_short:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=quality_result.feedback_message,
        )

    saved = await _mala_repo.upsert(
        db,
        current_user.id,
        body.question_code,
        {
            "question_block": question.block.value,
            "response_text": body.response_text,
            "token_count": quality_result.token_count,
            "word_count": quality_result.word_count,
            "quality_score": quality_result.quality_score,
            "processing_status": "pending",
            "processing_error": None,
        },
    )
    await db.commit()

    arq_pool = await get_arq_pool()
    job = await arq_pool.enqueue_job(
        "analyze_mala_response",
        str(current_user.id),
        body.question_code,
        body.response_text,
    )
    processing_job_id = job.job_id if job is not None and hasattr(job, "job_id") else "queued"

    responses = await _mala_repo.get_by_user_id(db, current_user.id)
    puc_profile = await _puc_repo.get_by_user_id(db, current_user.id)
    progress = _build_progress(responses, puc_profile)

    answered_codes = [r.question_code for r in responses]
    next_q = get_next_question(answered_codes)

    return MalaResponseSubmitResult(
        response_id=saved.id,
        quality_result=quality_result,
        processing_job_id=processing_job_id,
        next_question_code=next_q.code if next_q else None,
        progress=progress,
    )


@router.get("/responses", response_model=list[MalaResponseRead])
async def list_responses(
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db),
) -> list[MalaResponseRead]:
    responses = await _mala_repo.get_by_user_id(db, current_user.id)
    result = []
    for r in responses:
        read = MalaResponseRead.model_validate(r)
        read.layer_results = None
        result.append(read)
    return result


@router.get("/responses/{question_code}/status")
async def get_response_status(
    question_code: str,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db),
) -> dict:
    response = await _mala_repo.get_by_user_and_question(db, current_user.id, question_code)
    if response is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No response found for question {question_code}.",
        )
    return {
        "status": response.processing_status,
        "processing_error": response.processing_error,
    }


@router.delete("/responses/{question_code}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_response(
    question_code: str,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db),
) -> None:
    response = await _mala_repo.get_by_user_and_question(db, current_user.id, question_code)
    if response is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No response found for question {question_code}.",
        )
    await _mala_repo.delete(db, response.id)
    await _puc_repo.upsert(db, current_user.id, {"puc_vector": None})
    await db.commit()


@router.get("/archetype", response_model=ArchetypeResponseSchema)
async def get_archetype(
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the computed archetype for the authenticated job seeker.

    Display strings (name, strengths, risks, ideal_cultures, matching_note)
    are intentionally absent from the response — the frontend resolves them
    from i18n keys ``archetypes.<primary_archetype>.*``.
    Only non-translatable visual properties (emoji, color) are included in
    ``archetype_data``.
    """
    puc_profile = await _puc_repo.get_by_user_id(db, current_user.id)
    if not puc_profile or not puc_profile.primary_archetype:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archetype not computed yet. Complete more assessment questions.",
        )

    archetype_id = puc_profile.primary_archetype
    # Fall back to a known entry if an unexpected id slips through.
    visual = ARCHETYPE_METADATA.get(
        archetype_id,
        ARCHETYPE_METADATA["ejecutor_alto_impacto"],
    )

    probs: dict[str, float] = puc_profile.archetype_probabilities or {archetype_id: 1.0}

    # Hybrid: top-two archetypes within 15 percentage points of each other.
    sorted_probs = sorted(probs.values(), reverse=True)
    is_hybrid = len(sorted_probs) >= 2 and (sorted_probs[0] - sorted_probs[1]) < 0.15
    hybrid_description: Optional[str] = None
    if is_hybrid:
        second_id = next(
            (k for k, v in sorted(probs.items(), key=lambda x: x[1], reverse=True) if k != archetype_id),
            None,
        )
        if second_id:
            # Return both archetype IDs so the frontend can translate them.
            hybrid_description = f"{archetype_id}+{second_id}"

    stability_warning = (puc_profile.completeness_score or 0.0) < 0.5

    big_five = None
    if puc_profile.openness is not None:
        big_five = BigFiveSchema(
            openness=(puc_profile.openness or 0.5) * 100,
            conscientiousness=(puc_profile.conscientiousness or 0.5) * 100,
            extraversion=(puc_profile.extraversion or 0.5) * 100,
            agreeableness=(puc_profile.agreeableness or 0.5) * 100,
            emotional_stability=(puc_profile.emotional_stability or 0.5) * 100,
        )

    return {
        "primary_archetype": archetype_id,
        "probabilities": probs,
        "is_hybrid": is_hybrid,
        "hybrid_description": hybrid_description,
        "stability_warning": stability_warning,
        "archetype_data": ArchetypeDataSchema(emoji=visual["emoji"], color=visual["color"]),
        "big_five": big_five,
        "completeness_score": puc_profile.completeness_score or 0.0,
    }
