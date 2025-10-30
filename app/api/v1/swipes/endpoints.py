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
from app.schemas.swipe import SwipeCreate, Swipe as SwipeSchema, RejectedJobsResponse, RejectedJobItem
from app.schemas.job import JobWithCompany
import base64
import json
from datetime import datetime

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

    # Check if swipe already exists (update if so)
    result = await db.execute(select(Swipe).where(
        Swipe.user_id == current_user.id,
        Swipe.job_id == swipe_data.job_id
    ))
    existing_swipe = result.scalar_one_or_none()

    if existing_swipe:
        # Update existing swipe
        existing_swipe.direction = swipe_data.direction
        await db.commit()
        await db.refresh(existing_swipe)
        swipe = existing_swipe
    else:
        # Create new swipe
        swipe = Swipe(
            user_id=current_user.id,
            job_id=swipe_data.job_id,
            direction=swipe_data.direction
        )
        db.add(swipe)
        await db.commit()
        await db.refresh(swipe)

    # If RIGHT swipe, create or update application and potentially update user embedding
    if swipe_data.direction == "RIGHT":
        result = await db.execute(select(Application).where(
            Application.user_id == current_user.id,
            Application.job_id == swipe_data.job_id
        ))
        existing_application = result.scalar_one_or_none()

        if not existing_application:
            application = Application(
                user_id=current_user.id,
                job_id=swipe_data.job_id,
                status="ACTIVE"
            )
            db.add(application)
            await db.commit()

        # Update user embedding based on right swipe history (as per CLAUDE.md)
        await _update_user_embedding_if_needed(current_user, db)

    return swipe


async def _update_user_embedding_if_needed(user: User, db):
    """Update user embedding based on right swipe history after threshold"""
    from app.services.embedding_service import embedding_service

    # Count user's right swipes
    result = await db.execute(
        select(func.count(Swipe.id))
        .where(Swipe.user_id == user.id, Swipe.direction == "RIGHT")
    )
    right_swipe_count = result.scalar()

    # Update embedding after 5 right swipes, then every 3 additional swipes
    should_update = (
        (right_swipe_count == 5) or  # First update after 5 swipes
        (right_swipe_count > 5 and (right_swipe_count - 5) % 3 == 0)  # Every 3 swipes after
    )

    if not should_update:
        return

    try:
        # Get jobs from recent right swipes (limit to last 10 for performance)
        result = await db.execute(
            select(Job.job_embedding)
            .join(Swipe, Job.id == Swipe.job_id)
            .where(
                Swipe.user_id == user.id,
                Swipe.direction == "RIGHT",
                Job.job_embedding.isnot(None)
            )
            .order_by(Swipe.created_at.desc())
            .limit(10)
        )
        job_embeddings = [row[0] for row in result.all()]

        if not job_embeddings:
            return

        # Generate base embedding if user doesn't have one
        if not user.profile_embedding:
            user.profile_embedding = embedding_service.generate_user_embedding(
                headline=user.headline,
                skills=user.skills,
                preferences=user.preferred_locations
            )

        # Update embedding combining profile with right swipe history
        updated_embedding = embedding_service.update_user_embedding_with_history(
            base_embedding=user.profile_embedding,
            liked_job_embeddings=job_embeddings,
            alpha=0.3  # 30% profile, 70% history as per CLAUDE.md
        )

        user.profile_embedding = updated_embedding
        await db.commit()

        print(f"Updated user {user.id} embedding after {right_swipe_count} right swipes")

    except Exception as e:
        print(f"Failed to update user embedding for {user.id}: {e}")
        # Don't fail the swipe if embedding update fails


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
