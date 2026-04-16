"""
B6.3.3 — POST /api/v1/companies/jobs/{job_id}/match-config
B6.3.4 — GET  /api/v1/companies/jobs/{job_id}/match-config/preview
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import get_company_user_with_verification, require_company_access
from app.core.database import get_db
from app.models.job import Job
from app.models.user import User
from app.schemas.company_profile import (
    JobMatchConfigCreate,
    JobMatchConfigRead,
    JobVectorPreview,
)
from app.services.company_profile_service import (
    create_or_update_match_config,
    get_match_config,
    get_job_vector_preview,
    infer_big_five_from_job_description,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Job Match Config"])


async def _verify_job_ownership(
    job_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
) -> Job:
    """Ensure the job exists and belongs to the current user's company."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    require_company_access(current_user, job.company_id)
    return job


@router.post(
    "/jobs/{job_id}/match-config",
    response_model=JobMatchConfigRead,
    summary="Set match configuration for a job offer (E5–E9 + hard filters + weights)",
)
async def set_match_config(
    job_id: uuid.UUID,
    payload: JobMatchConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_company_user_with_verification),
):
    """B6.3.3 — Persist E5–E9 texts, auto-adjust weights from E5, build anti-profile from E9.

    Returns the final configuration including the preview of the Job Vector.
    """
    await _verify_job_ownership(job_id, current_user, db)

    config = await create_or_update_match_config(db, job_id, payload)
    return JobMatchConfigRead.model_validate(config)


@router.get(
    "/jobs/{job_id}/match-config",
    response_model=JobMatchConfigRead,
    summary="Get current match configuration for a job",
)
async def get_job_match_config(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_company_user_with_verification),
):
    await _verify_job_ownership(job_id, current_user, db)

    config = await get_match_config(db, job_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No match config found for this job",
        )
    return JobMatchConfigRead.model_validate(config)


@router.get(
    "/jobs/{job_id}/match-config/preview",
    response_model=JobVectorPreview,
    summary="Preview the Job Vector before activating the job offer",
)
async def preview_job_vector(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_company_user_with_verification),
):
    """B6.3.4 — Returns the full Job Vector and archetype advantages preview.

    Useful to see which candidate archetypes would have a scoring advantage
    before publishing the job offer.
    """
    await _verify_job_ownership(job_id, current_user, db)

    preview = await get_job_vector_preview(db, job_id)
    if not preview:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No match config found. Call POST /match-config first.",
        )
    return preview


@router.post(
    "/jobs/{job_id}/match-config/infer-description",
    summary="Infer Big Five minimums from a job description text (live, debounced)",
)
async def infer_big_five_endpoint(
    job_id: uuid.UUID,
    description: str,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db),
):
    """Infer Big Five minimums from a free-text description.

    Called with debounce from the F6.3 wizard while the recruiter types.
    Does NOT persist — returns a preview for the slider component.
    """
    await _verify_job_ownership(job_id, current_user, db)
    minimums = await infer_big_five_from_job_description(description)
    return minimums.model_dump()
