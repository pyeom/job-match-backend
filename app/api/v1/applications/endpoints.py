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
from app.schemas.application import Application as ApplicationSchema, ApplicationUpdate, ApplicationWithDetails
import uuid

router = APIRouter()


@router.get("/{user_id}/applications", response_model=List[ApplicationWithDetails])
async def get_user_applications(
    user_id: uuid.UUID,
    current_user: User = Depends(get_job_seeker),  # Only job seekers have applications
    db: AsyncSession = Depends(get_db)
):
    """Get all applications for specified user (must be current user)"""
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
        .where(Application.user_id == user_id)
        .order_by(Application.created_at.desc())
    )
    applications = result.scalars().all()

    return applications


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
            Application.user_id == user_id
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


# Legacy endpoints for backward compatibility (deprecated)
@router.get("/", response_model=List[ApplicationWithDetails], deprecated=True)
async def get_current_user_applications_legacy(
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    DEPRECATED: Get all applications for current user with job and company details
    Use GET /users/{user_id}/applications instead
    """
    result = await db.execute(
        select(Application)
        .options(
            selectinload(Application.job).selectinload(Job.company),
            selectinload(Application.user),
        )
        .where(Application.user_id == current_user.id)
        .order_by(Application.created_at.desc())
    )
    applications = result.scalars().all()

    return applications


@router.get("/{application_id}", response_model=ApplicationWithDetails, deprecated=True)
async def get_application_legacy(
    application_id: uuid.UUID,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    DEPRECATED: Get a specific application with job and company details
    Use GET /users/{user_id}/applications/{application_id} instead
    """
    result = await db.execute(
        select(Application)
        .options(
            selectinload(Application.job).selectinload(Job.company),
            selectinload(Application.user),
        )
        .where(
            Application.id == application_id,
            Application.user_id == current_user.id
        )
    )
    application = result.scalar_one_or_none()

    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    return application
