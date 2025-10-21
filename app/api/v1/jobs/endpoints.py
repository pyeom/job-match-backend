from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, not_, exists
from sqlalchemy.orm import selectinload
from typing import List, Optional
from app.core.database import get_db
from app.api.deps import get_current_user, get_job_seeker
from app.models.user import User, UserRole
from app.models.job import Job
from app.models.company import Company
from app.schemas.job import Job as JobSchema, JobWithCompany, DiscoverResponse
import uuid
import base64
import json
from datetime import datetime

router = APIRouter()


def encode_cursor(score: int, job_id: str, created_at: datetime) -> str:
    """Encode cursor for pagination using score, job_id, and created_at"""
    cursor_data = {
        "score": score,
        "job_id": str(job_id),
        "created_at": created_at.isoformat()
    }
    cursor_json = json.dumps(cursor_data)
    return base64.b64encode(cursor_json.encode()).decode()


def decode_cursor(cursor: str) -> tuple[int, str, datetime]:
    """Decode cursor to get score, job_id, and created_at"""
    try:
        cursor_json = base64.b64decode(cursor.encode()).decode()
        cursor_data = json.loads(cursor_json)
        return (
            cursor_data["score"],
            cursor_data["job_id"],
            datetime.fromisoformat(cursor_data["created_at"])
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


@router.get("/discover", response_model=DiscoverResponse)
async def discover_jobs(
    limit: int = Query(20, ge=1, le=50),
    cursor: Optional[str] = None,
    current_user: User = Depends(get_job_seeker),  # Only job seekers can discover jobs
    db: AsyncSession = Depends(get_db)
):
    """Get personalized job recommendations (discover feed)

    This endpoint implements ML-driven job recommendations using:
    - Vector similarity search with pgvector
    - Hybrid scoring combining embeddings + rule-based factors
    - Filtering out already swiped jobs
    - Complex ranking algorithm as described in CLAUDE.md
    """
    from app.models.swipe import Swipe
    from app.services.scoring_service import scoring_service
    from app.services.embedding_service import embedding_service

    # Parse cursor if provided
    cursor_score = None
    cursor_job_id = None
    cursor_created_at = None
    if cursor:
        cursor_score, cursor_job_id, cursor_created_at = decode_cursor(cursor)

    # Get jobs that user hasn't swiped on, using vector similarity if user has profile embedding
    base_query = (
        select(Job)
        .options(selectinload(Job.company))
        .where(
            and_(
                Job.is_active == True,
                not_(exists().where(
                    and_(
                        Swipe.job_id == Job.id,
                        Swipe.user_id == current_user.id
                    )
                ))
            )
        )
    )

    # If user has a profile embedding, use vector similarity search with larger pool
    if current_user.profile_embedding is not None:
        # Get larger candidate pool using vector similarity (e.g., top 300)
        # Increase pool size to account for cursor filtering
        candidate_limit = min(500, limit * 25)  # Get 25x more candidates for re-ranking

        # Use vector similarity ordering
        stmt = base_query.order_by(
            current_user.profile_embedding.cosine_distance(Job.job_embedding)
        ).limit(candidate_limit)

        result = await db.execute(stmt)
        candidate_jobs = result.scalars().all()

        # Re-rank using ML scoring
        scored_jobs = []
        for job in candidate_jobs:
            if job.job_embedding:  # Only score jobs with embeddings
                try:
                    score = scoring_service.calculate_job_score(
                        user_embedding=current_user.profile_embedding,
                        job_embedding=job.job_embedding,
                        user_skills=current_user.skills,
                        user_seniority=current_user.seniority,
                        user_preferences=current_user.preferred_locations,
                        job_tags=job.tags,
                        job_seniority=job.seniority,
                        job_location=job.location,
                        job_remote=job.remote or False,
                        job_created_at=job.created_at
                    )
                    scored_jobs.append((job, score))
                except Exception as e:
                    # Fallback score if ML scoring fails
                    print(f"ML scoring failed for job {job.id}: {e}")
                    scored_jobs.append((job, 70))
            else:
                # Default score for jobs without embeddings
                scored_jobs.append((job, 60))

        # Sort by score (descending), then by created_at (descending) for stable ordering
        scored_jobs.sort(key=lambda x: (x[1], x[0].created_at), reverse=True)

        # Apply cursor filtering if provided
        if cursor_score is not None:
            filtered_jobs = []
            for job, score in scored_jobs:
                # Include jobs with lower score, or same score but older/different id
                if (score < cursor_score or
                    (score == cursor_score and job.created_at < cursor_created_at) or
                    (score == cursor_score and job.created_at == cursor_created_at and str(job.id) > cursor_job_id)):
                    filtered_jobs.append((job, score))
            scored_jobs = filtered_jobs

        # Take requested limit + 1 to check if there are more results
        top_jobs = scored_jobs[:limit + 1]

    else:
        # Fallback for users without profile embeddings - use recency with cursor
        if cursor:
            # For non-ML users, cursor contains created_at for simple pagination
            stmt = base_query.where(Job.created_at < cursor_created_at).order_by(Job.created_at.desc()).limit(limit + 1)
        else:
            stmt = base_query.order_by(Job.created_at.desc()).limit(limit + 1)

        result = await db.execute(stmt)
        jobs = result.scalars().all()

        # Give all jobs a baseline score
        top_jobs = [(job, 65) for job in jobs]

    # Determine if there are more results and prepare items
    has_more = len(top_jobs) > limit
    items_to_return = top_jobs[:limit]  # Remove the extra item used for has_more check

    # Convert to response format
    job_results = []
    for job, score in items_to_return:
        job_data = {
            "id": job.id,
            "title": job.title,
            "company_id": job.company_id,
            "location": job.location,
            "short_description": job.short_description,
            "description": job.description,
            "tags": job.tags,
            "seniority": job.seniority,
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "remote": job.remote,
            "is_active": job.is_active,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "company": {
                "id": job.company.id,
                "name": job.company.name,
                "description": job.company.description,
                "website": job.company.website,
                "industry": job.company.industry,
                "size": job.company.size,
                "location": job.company.location,
                "is_verified": job.company.is_verified
            } if job.company else None,
            "score": score
        }

        job_results.append(JobWithCompany(**job_data))

    # Generate next_cursor if there are more results
    next_cursor = None
    if has_more and items_to_return:
        last_job, last_score = items_to_return[-1]
        next_cursor = encode_cursor(last_score, last_job.id, last_job.created_at)

    return DiscoverResponse(
        items=job_results,
        next_cursor=next_cursor
    )


@router.get("/{job_id}", response_model=JobWithCompany)
async def get_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific job by ID with company information

    Available to all authenticated users (job seekers can view job details as part of discovery process)
    """
    result = await db.execute(
        select(Job)
        .options(selectinload(Job.company))
        .where(Job.id == job_id, Job.is_active == True)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return job
