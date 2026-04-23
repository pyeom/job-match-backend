from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List
from app.core.database import get_db
from app.api.deps import get_current_user, get_job_seeker
from app.models.user import User
from app.models.application import Application
from app.models.job import Job
from app.models.company import Company
from app.models.pipeline import PipelineTemplate, DEFAULT_PIPELINE_STAGES
from app.schemas.application import Application as ApplicationSchema, ApplicationUpdate, ApplicationWithDetails
import uuid

router = APIRouter()


def _normalize_stage(s: dict) -> dict:
    """Normalize stage dict from old {order,name,color} or new {key,order,label,description,color} format."""
    if "key" in s:
        return s
    name = s.get("name", "unknown")
    return {
        "key": name.lower().replace(" ", "_"),
        "order": s.get("order", 0),
        "label": name,
        "description": "",
        "color": s.get("color", "#6b7280"),
    }


async def _batch_fetch_pipelines(
    company_ids: list[uuid.UUID],
    db: AsyncSession,
) -> dict[uuid.UUID, list[dict]]:
    """Batch-fetch pipeline stages for a set of company IDs to avoid N+1 queries.

    Returns a mapping of company_id → sorted list of normalized stage dicts.
    Companies with no custom pipeline fall back to DEFAULT_PIPELINE_STAGES.
    """
    if not company_ids:
        return {}

    result = await db.execute(
        select(PipelineTemplate).where(
            PipelineTemplate.company_id.in_(company_ids),
            PipelineTemplate.is_default == True,  # noqa: E712
        )
    )
    templates = result.scalars().all()
    pipeline_map: dict[uuid.UUID, list[dict]] = {
        t.company_id: sorted(
            [_normalize_stage(s) for s in (t.stages or [])],
            key=lambda s: s["order"],
        )
        for t in templates
        if t.stages
    }
    return pipeline_map


def _get_stage_info_from_map(
    stage_key: str,
    company_id: uuid.UUID,
    pipeline_map: dict[uuid.UUID, list[dict]],
) -> dict:
    """Look up stage metadata for a given company, falling back to defaults."""
    stages = pipeline_map.get(company_id, DEFAULT_PIPELINE_STAGES)
    for s in stages:
        if s["key"] == stage_key:
            return s
    return {
        "key": stage_key,
        "order": 0,
        "label": stage_key,
        "description": "",
        "color": "#6b7280",
    }


@router.get("/{user_id}/applications")
async def get_user_applications(
    user_id: uuid.UUID,
    current_user: User = Depends(get_job_seeker),  # Only job seekers have applications
    db: AsyncSession = Depends(get_db)
):
    """Get all applications for specified user (must be current user).

    Each application includes ``stage_info`` with the label, color, and order
    from the posting company's pipeline configuration.
    """
    # Ensure users can only access their own applications
    if current_user.id != user_id:
        raise HTTPException(
            status_code=403,
            detail="You can only access your own applications"
        )

    result = await db.execute(
        select(Application)
        .options(
            selectinload(Application.job).selectinload(Job.company),
            selectinload(Application.user),
        )
        .where(Application.user_id == user_id, Application.status != "PENDING")
        .order_by(Application.created_at.desc())
    )
    applications = result.scalars().all()

    # Batch-fetch pipelines for all unique companies to avoid N+1
    company_ids = list({
        app.job.company_id
        for app in applications
        if app.job and app.job.company_id
    })
    pipeline_map = await _batch_fetch_pipelines(company_ids, db)

    output: list[dict] = []
    for app in applications:
        app_dict = ApplicationWithDetails.model_validate(app).model_dump()
        company_id = app.job.company_id if app.job else None
        if company_id:
            app_dict["stage_info"] = _get_stage_info_from_map(app.stage, company_id, pipeline_map)
        output.append(app_dict)

    return output


@router.get("/{user_id}/applications/{application_id}", response_model=ApplicationWithDetails)
async def get_user_application(
    user_id: uuid.UUID,
    application_id: uuid.UUID,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific application for specified user (must be current user)"""
    # Ensure users can only access their own applications
    if current_user.id != user_id:
        raise HTTPException(
            status_code=403,
            detail="You can only access your own applications"
        )

    result = await db.execute(
        select(Application)
        .options(
            selectinload(Application.job).selectinload(Job.company),
            selectinload(Application.user),
        )
        .where(
            Application.id == application_id,
            Application.user_id == user_id,
            Application.status != "PENDING"
        )
    )
    application = result.scalar_one_or_none()

    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    return application


@router.patch("/{user_id}/applications/{application_id}", response_model=ApplicationSchema)
async def update_user_application(
    user_id: uuid.UUID,
    application_id: uuid.UUID,
    application_update: ApplicationUpdate,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """Update application status or notes for specified user (must be current user)"""
    # Ensure users can only update their own applications
    if current_user.id != user_id:
        raise HTTPException(
            status_code=403,
            detail="You can only update your own applications"
        )

    result = await db.execute(select(Application).where(
        Application.id == application_id,
        Application.user_id == user_id
    ))
    application = result.scalar_one_or_none()

    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    update_data = application_update.dict(exclude_unset=True)

    for field, value in update_data.items():
        setattr(application, field, value)

    await db.commit()
    await db.refresh(application)

    return application
