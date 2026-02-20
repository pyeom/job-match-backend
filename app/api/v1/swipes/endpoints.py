from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import Optional
from app.core.database import get_db
from app.api.deps import get_current_user, get_job_seeker
from app.models.user import User
from app.models.job import Job
from app.models.swipe import Swipe
from app.models.application import Application
from app.schemas.swipe import (
    SwipeCreate,
    Swipe as SwipeSchema,
    SwipeWithUndoWindow,
    UndoResponse,
    UndoLimitInfo,
    RejectedJobsResponse,
    RejectedJobItem
)
from app.schemas.job import JobWithCompany
from app.services.swipe_service import SwipeService
from app.core.arq import get_arq_pool
from app.services.scoring_service import ScoringService
import base64
import json
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_model=SwipeSchema)
async def create_swipe(
    swipe_data: SwipeCreate,
    current_user: User = Depends(get_job_seeker),  # Only job seekers can swipe
    db: AsyncSession = Depends(get_db)
):
    """Create a new swipe (and application if RIGHT)"""

    # Validate job exists
    result = await db.execute(select(Job).where(Job.id == swipe_data.job_id, Job.is_active == True))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Validate direction
    if swipe_data.direction not in ["LEFT", "RIGHT"]:
        raise HTTPException(status_code=400, detail="Direction must be LEFT or RIGHT")

    # Check if swipe already exists and is not undone (update if so)
    result = await db.execute(select(Swipe).where(
        Swipe.user_id == current_user.id,
        Swipe.job_id == swipe_data.job_id,
        Swipe.is_undone == False
    ))
    existing_swipe = result.scalar_one_or_none()

    application = None

    if existing_swipe:
        # Update existing swipe direction
        existing_swipe.direction = swipe_data.direction
        await db.flush()
        swipe = existing_swipe
    else:
        # Stage new swipe (no commit yet)
        swipe = Swipe(
            user_id=current_user.id,
            job_id=swipe_data.job_id,
            direction=swipe_data.direction
        )
        db.add(swipe)
        await db.flush()  # assigns swipe.id without committing

    # If RIGHT swipe, stage application in the same transaction
    if swipe_data.direction == "RIGHT":
        result = await db.execute(select(Application).where(
            Application.user_id == current_user.id,
            Application.job_id == swipe_data.job_id
        ))
        existing_application = result.scalar_one_or_none()

        if not existing_application:
            score = ScoringService.calculate_job_score(
                user_embedding=list(current_user.profile_embedding) if current_user.profile_embedding is not None else [],
                job_embedding=list(job.job_embedding) if job.job_embedding is not None else [],
                user_skills=current_user.skills,
                user_seniority=current_user.seniority,
                user_preferences=current_user.preferred_locations,
                job_tags=job.tags,
                job_seniority=job.seniority,
                job_location=job.location,
                job_remote=(job.work_arrangement == "Remote"),
                job_created_at=job.created_at
            )
            logger.info(f"Staging application with server-calculated score {score} for user {current_user.id} on job {job.id}")

            application = Application(
                user_id=current_user.id,
                job_id=swipe_data.job_id,
                status="ACTIVE",
                score=score
            )
            db.add(application)
            await db.flush()  # assigns application.id without committing

    # Single atomic commit covering swipe + application
    await db.commit()
    await db.refresh(swipe)

    if application is not None:
        logger.info(f"Created new application {application.id} for user {current_user.id} on job {swipe_data.job_id}")

        # Notify the company about the new application (best-effort, after commit)
        try:
            from app.services.notification_service import NotificationService

            logger.info(f"Attempting to create notification for application {application.id}")
            notification_service = NotificationService()
            notification = await notification_service.create_new_application_notification(db, application.id)

            if notification:
                await db.commit()
                logger.info(f"Successfully created notification {notification.id} for application {application.id}")
            else:
                logger.warning(f"Notification service returned None for application {application.id}")

        except Exception as e:
            logger.error(f"Failed to create notification for application {application.id}: {e}", exc_info=True)
            await db.rollback()

    # Enqueue user embedding update (threshold check done inside the task)
    if swipe_data.direction == "RIGHT":
        if await _should_update_embedding(current_user.id, db):
            try:
                arq = await get_arq_pool()
                await arq.enqueue_job("update_user_embedding", str(current_user.id))
            except Exception as e:
                logger.warning(f"Failed to enqueue embedding update for user {current_user.id}: {e}")

    return swipe


async def _should_update_embedding(user_id, db) -> bool:
    """Return True when the right-swipe count crosses the update threshold."""
    result = await db.execute(
        select(func.count(Swipe.id)).where(
            Swipe.user_id == user_id,
            Swipe.direction == "RIGHT",
            Swipe.is_undone == False,
        )
    )
    count = result.scalar() or 0
    return count == 5 or (count > 5 and (count - 5) % 3 == 0)


def encode_rejected_cursor(created_at: datetime, swipe_id: str) -> str:
    """Encode cursor for rejected jobs pagination using created_at and swipe_id"""
    cursor_data = {
        "created_at": created_at.isoformat(),
        "swipe_id": str(swipe_id)
    }
    cursor_json = json.dumps(cursor_data)
    return base64.b64encode(cursor_json.encode()).decode()


def decode_rejected_cursor(cursor: str) -> tuple[datetime, str]:
    """Decode cursor to get created_at and swipe_id"""
    try:
        cursor_json = base64.b64decode(cursor.encode()).decode()
        cursor_data = json.loads(cursor_json)
        return (
            datetime.fromisoformat(cursor_data["created_at"]),
            cursor_data["swipe_id"]
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


@router.get("/rejected", response_model=RejectedJobsResponse)
async def get_rejected_jobs(
    limit: int = Query(20, ge=1, le=50, description="Number of items per page"),
    cursor: Optional[str] = Query(None, description="Pagination cursor"),
    current_user: User = Depends(get_job_seeker),  # Only job seekers can view rejected jobs
    db: AsyncSession = Depends(get_db)
):
    """Get all jobs the user has rejected (swiped LEFT on) with full job and company details

    This endpoint returns rejected jobs in reverse chronological order (newest first)
    with cursor-based pagination for optimal performance.

    Features:
    - Returns full job and company details
    - Handles deleted jobs gracefully (job field will be null)
    - Includes inactive jobs with is_active flag
    - Efficient cursor-based pagination
    - Optimized with joinedload to avoid N+1 queries

    Query Parameters:
    - limit: Number of items per page (1-50, default: 20)
    - cursor: Base64-encoded pagination cursor for fetching next page

    Response includes:
    - items: List of rejected job items with swipe and job details
    - total: Total count of rejected jobs
    - has_more: Whether more results are available
    - next_cursor: Cursor for fetching next page (if has_more is true)
    """

    # Parse cursor if provided
    cursor_created_at = None
    cursor_swipe_id = None
    if cursor:
        cursor_created_at, cursor_swipe_id = decode_rejected_cursor(cursor)

    # First, get total count of rejected jobs for this user
    count_stmt = (
        select(func.count(Swipe.id))
        .where(
            Swipe.user_id == current_user.id,
            Swipe.direction == "LEFT"
        )
    )
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    # Build query for rejected swipes with eager loading of job and company
    query = (
        select(Swipe)
        .options(
            selectinload(Swipe.job).selectinload(Job.company)
        )
        .where(
            Swipe.user_id == current_user.id,
            Swipe.direction == "LEFT"
        )
    )

    # Apply cursor filtering if provided
    if cursor_created_at and cursor_swipe_id:
        # For pagination: get records older than cursor (created_at < cursor_created_at)
        # or same created_at but with id > cursor_id for stable ordering
        query = query.where(
            (Swipe.created_at < cursor_created_at) |
            ((Swipe.created_at == cursor_created_at) & (Swipe.id > cursor_swipe_id))
        )

    # Order by created_at DESC (newest first), then by id for stable ordering
    query = query.order_by(Swipe.created_at.desc(), Swipe.id.asc())

    # Fetch limit + 1 to determine if there are more results
    query = query.limit(limit + 1)

    result = await db.execute(query)
    swipes = result.scalars().all()

    # Determine if there are more results
    has_more = len(swipes) > limit
    items_to_return = swipes[:limit]  # Remove extra item used for has_more check

    # Convert to response format
    rejected_items = []
    for swipe in items_to_return:
        # Build job data if job exists
        job_data = None
        if swipe.job:
            job_data = {
                "id": swipe.job.id,
                "title": swipe.job.title,
                "company_id": swipe.job.company_id,
                "location": swipe.job.location,
                "short_description": swipe.job.short_description,
                "description": swipe.job.description,
                "tags": swipe.job.tags,
                "seniority": swipe.job.seniority,
                "salary_min": swipe.job.salary_min,
                "salary_max": swipe.job.salary_max,
                "remote": swipe.job.remote,
                "is_active": swipe.job.is_active,
                "created_at": swipe.job.created_at,
                "updated_at": swipe.job.updated_at,
                "company": None,
                "score": None  # No score for rejected jobs
            }

            # Add company data if available
            if swipe.job.company:
                job_data["company"] = {
                    "id": swipe.job.company.id,
                    "name": swipe.job.company.name,
                    "description": swipe.job.company.description,
                    "website": swipe.job.company.website,
                    "logo_url": swipe.job.company.logo_url,
                    "industry": swipe.job.company.industry,
                    "size": swipe.job.company.size,
                    "location": swipe.job.company.location,
                    "founded_year": swipe.job.company.founded_year,
                    "is_verified": swipe.job.company.is_verified
                }

            job_data = JobWithCompany(**job_data)

        rejected_item = RejectedJobItem(
            swipe_id=swipe.id,
            job_id=swipe.job_id,
            rejected_at=swipe.created_at,
            job=job_data
        )
        rejected_items.append(rejected_item)

    # Generate next_cursor if there are more results
    next_cursor = None
    if has_more and items_to_return:
        last_swipe = items_to_return[-1]
        next_cursor = encode_rejected_cursor(last_swipe.created_at, last_swipe.id)

    return RejectedJobsResponse(
        items=rejected_items,
        total=total,
        has_more=has_more,
        next_cursor=next_cursor
    )


@router.get("/last", response_model=Optional[SwipeWithUndoWindow])
async def get_last_swipe(
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """Get the user's last swipe within the undo window

    This endpoint returns the most recent swipe if it's within the 5-second
    undo window, along with information about whether it can be undone and
    how much time remains.

    Features:
    - Returns None if no recent swipe within undo window
    - Includes remaining undo time in seconds
    - Checks daily undo limit eligibility
    - Only returns non-undone swipes

    Response includes:
    - Swipe details (id, job_id, direction, created_at)
    - can_undo: Whether the swipe can be undone
    - remaining_undo_time: Seconds remaining in undo window
    """
    swipe_service = SwipeService()

    # Re-fetch user so service mutations are tracked by the session
    user = await db.get(User, current_user.id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Reset daily counter if needed
    await swipe_service.check_and_reset_daily_counter(db, user)

    # Get last swipe with window info
    result = await swipe_service.get_last_swipe_with_window(db, user)

    if not result:
        return None

    swipe, remaining_time = result

    # Check if user can undo (considering daily limit)
    can_undo, _ = await swipe_service.check_undo_eligibility(db, user, swipe)

    return SwipeWithUndoWindow(
        id=swipe.id,
        user_id=swipe.user_id,
        job_id=swipe.job_id,
        direction=swipe.direction,
        created_at=swipe.created_at,
        is_undone=swipe.is_undone,
        can_undo=can_undo,
        remaining_undo_time=remaining_time if remaining_time > 0 else None
    )


@router.delete("/{swipe_id}", response_model=UndoResponse)
async def undo_swipe(
    swipe_id: str,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """Undo a swipe (soft delete)

    This endpoint allows users to undo their last swipe within a 5-second window.
    The operation marks the swipe as undone and removes any associated application
    if it was a RIGHT swipe.

    Constraints:
    - Swipe must be within 5-second undo window
    - Swipe must belong to the current user
    - Swipe must not be already undone
    - User must not exceed daily undo limit (3 for free, 10 for premium)

    The operation:
    1. Validates swipe ownership and eligibility
    2. Marks swipe as undone with timestamp
    3. Increments user's daily undo counter
    4. Deletes associated application (if RIGHT swipe)

    Returns:
    - Confirmation message
    - Swipe and job IDs
    - Timestamp of undo
    - Remaining daily undos
    """
    from uuid import UUID

    try:
        swipe_uuid = UUID(swipe_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid swipe ID format")

    swipe_service = SwipeService()

    # Re-fetch user so the daily_undo_count mutation is tracked by the session
    user = await db.get(User, current_user.id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Undo the swipe
    swipe = await swipe_service.undo_swipe(db, user, swipe_uuid)

    # Commit transaction
    await db.commit()
    await db.refresh(swipe)

    # Get remaining undos
    remaining = swipe_service.get_remaining_daily_undos(user)

    return UndoResponse(
        message="Swipe undone successfully",
        swipe_id=swipe.id,
        job_id=swipe.job_id,
        undone_at=swipe.undone_at,
        remaining_daily_undos=remaining
    )


@router.get("/undo-limits", response_model=UndoLimitInfo)
async def get_undo_limits(
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """Get information about the user's undo limits and usage

    This endpoint returns information about:
    - Daily undo limit (3 for free users, 10 for premium)
    - Number of undos used today
    - Number of undos remaining today
    - Premium status

    The daily counter resets at midnight UTC.
    """
    swipe_service = SwipeService()

    # Re-fetch user so the counter reset mutation is tracked by the session
    user = await db.get(User, current_user.id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Reset daily counter if needed
    await swipe_service.check_and_reset_daily_counter(db, user)
    await db.commit()

    # Get limit info
    info = swipe_service.get_undo_limit_info(user)

    return UndoLimitInfo(**info)
