"""B9.1 — Hiring Outcomes API

POST /api/v1/hiring-outcomes  — Submit a hiring outcome for a match score
GET  /api/v1/hiring-outcomes/{match_score_id}  — Read an existing outcome
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_company_admin
from app.core.database import get_db
from app.models.mala import HiringOutcome, MatchScore
from app.models.user import User
from app.schemas.match_score import HiringOutcomeCreate, HiringOutcomeRead
from app.repositories.hiring_outcome_repository import HiringOutcomeRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Hiring Outcomes"])

_outcome_repo = HiringOutcomeRepository()


def _derive_success(body: HiringOutcomeCreate) -> bool | None:
    """Heuristic: successful hire if performance_6m >= 3.0 and retention_6m is True."""
    if body.performance_6m is not None and body.retention_6m is not None:
        return body.performance_6m >= 3.0 and body.retention_6m
    if body.performance_3m is not None and body.retention_3m is not None:
        return body.performance_3m >= 3.0 and body.retention_3m
    return None


@router.post(
    "/hiring-outcomes",
    response_model=HiringOutcomeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a hiring outcome for a match score (B9.1.1)",
)
async def create_hiring_outcome(
    body: HiringOutcomeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_company_admin),
) -> HiringOutcomeRead:
    """Record a post-hire outcome for a previously scored candidate.

    Requires COMPANY_ADMIN role.  Derives ``was_successful_hire`` from the
    performance / retention fields when both are provided.
    """
    # Load the MatchScore to verify it exists and belongs to the admin's company
    score_stmt = select(MatchScore).where(MatchScore.id == body.match_score_id)
    score_result = await db.execute(score_stmt)
    match_score = score_result.scalar_one_or_none()
    if match_score is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MatchScore not found.")

    # Guard: company_id on MatchScore must belong to the current user's company
    if current_user.company_id and match_score.job_id:
        from app.models.job import Job
        job_result = await db.execute(select(Job).where(Job.id == match_score.job_id))
        job = job_result.scalar_one_or_none()
        if job and job.company_id != current_user.company_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    # Idempotency: return existing outcome if already submitted
    existing = await _outcome_repo.get_by_match_score_id(db, body.match_score_id)
    if existing:
        return HiringOutcomeRead.model_validate(existing)

    was_successful = _derive_success(body)

    outcome = await _outcome_repo.create(db, {
        "match_score_id": body.match_score_id,
        "user_id": match_score.user_id,
        "job_id": match_score.job_id,
        "company_id": current_user.company_id,
        "performance_3m": body.performance_3m,
        "retention_3m": body.retention_3m,
        "notes_3m": body.notes_3m,
        "performance_6m": body.performance_6m,
        "retention_6m": body.retention_6m,
        "notes_6m": body.notes_6m,
        "was_successful_hire": was_successful,
        "failure_reason": body.failure_reason,
    })
    await db.commit()
    await db.refresh(outcome)

    logger.info(
        "HiringOutcome created: match_score=%s was_successful=%s by=%s",
        body.match_score_id, was_successful, current_user.id,
    )
    return HiringOutcomeRead.model_validate(outcome)


@router.get(
    "/hiring-outcomes/{match_score_id}",
    response_model=HiringOutcomeRead,
    summary="Get hiring outcome for a match score (B9.1.1)",
)
async def get_hiring_outcome(
    match_score_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_company_admin),
) -> HiringOutcomeRead:
    outcome = await _outcome_repo.get_by_match_score_id(db, match_score_id)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outcome not found.")
    return HiringOutcomeRead.model_validate(outcome)
