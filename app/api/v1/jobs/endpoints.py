from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, not_, exists
from sqlalchemy.orm import selectinload
from typing import List, Optional
from app.core.database import get_db
from app.core.cache import (
    get_cached_discover,
    set_cached_discover,
    get_swiped_set,
    populate_swiped_set,
)
from app.api.deps import get_current_user, get_job_seeker
from app.models.user import User, UserRole
from app.models.job import Job
from app.models.company import Company
from app.schemas.job import Job as JobSchema, JobWithCompany, DiscoverResponse
from app.schemas.search import JobSearchRequest, JobSearchResponse
from app.services.search_service import search_service
from app.services.rate_limit_service import rate_limit_service
import uuid
import base64
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

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
    request: Request,
    limit: int = Query(20, ge=1, le=50),
    cursor: Optional[str] = None,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """Get personalized job recommendations (discover feed).

    Candidate retrieval uses Elasticsearch kNN vector search (limit x 5
    candidates) instead of the previous 25x PostgreSQL multiplier.  The
    small candidate pool is then re-ranked in Python with the full hybrid
    ML scoring algorithm (55% embedding + skill/seniority/recency/location
    factors).  A PostgreSQL fallback is used when ES is unavailable or the
    user has no profile embedding.
    """
    # Rate limit: 30 discover requests per minute per user
    is_allowed, retry_after = await rate_limit_service.check_rate_limit(
        key=f"discover:user:{current_user.id}",
        max_requests=30,
        window_seconds=60,
    )
    if not is_allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many discover requests. Please slow down.",
            headers={"Retry-After": str(retry_after)},
        )

    # ------------------------------------------------------------------
    # 0. Cache check — first-page requests only (no cursor)
    # ------------------------------------------------------------------
    if cursor is None:
        cached_json = await get_cached_discover(str(current_user.id))
        if cached_json:
            return DiscoverResponse.model_validate_json(cached_json)

    from app.models.swipe import Swipe
    from app.services.scoring_service import scoring_service
    from app.services.elasticsearch_service import elasticsearch_service

    # Parse cursor if provided
    cursor_score = cursor_job_id = cursor_created_at = None
    if cursor:
        cursor_score, cursor_job_id, cursor_created_at = decode_cursor(cursor)

    # ------------------------------------------------------------------
    # 1. Swiped job set — Redis first, rebuild from PG on cache miss
    # ------------------------------------------------------------------
    # We maintain a Redis Set `swiped:{user_id}` so we never pass a large
    # `must_not: terms` list into the ES kNN query (which forces expensive
    # post-filtering for active users).  Instead, ES returns the top-k
    # active candidates and we filter in Python against the small Redis set.
    swiped_set = await get_swiped_set(str(current_user.id))
    if swiped_set is None:
        # Cache miss — fetch all swiped IDs from PG and populate Redis
        swiped_result = await db.execute(
            select(Swipe.job_id)
            .where(
                Swipe.user_id == current_user.id,
                Swipe.is_undone == False,  # noqa: E712
            )
        )
        swiped_job_ids_list = [str(row[0]) for row in swiped_result.all()]
        swiped_set = set(swiped_job_ids_list)
        await populate_swiped_set(str(current_user.id), swiped_job_ids_list)

    # ------------------------------------------------------------------
    # 2. Candidate retrieval
    # ------------------------------------------------------------------
    if current_user.profile_embedding is not None:
        # --- Elasticsearch kNN path ---
        candidate_limit = limit * 5  # <= 5x instead of the old 25x

        es_job_ids = await elasticsearch_service.knn_discover(
            user_embedding=list(current_user.profile_embedding),
            k=candidate_limit,
        )

        # Post-filter: remove already-swiped jobs (O(n) on the small candidate list)
        if swiped_set:
            es_job_ids = [jid for jid in es_job_ids if jid not in swiped_set]

        if es_job_ids:
            # Fetch only the ES-returned jobs from PostgreSQL
            import uuid as _uuid
            uuid_ids = [_uuid.UUID(jid) for jid in es_job_ids]
            result = await db.execute(
                select(Job)
                .options(selectinload(Job.company))
                .where(Job.id.in_(uuid_ids), Job.is_active == True)  # noqa: E712
            )
            candidate_jobs = result.scalars().all()
        else:
            # ES miss (cold start / ES down) — fall back to pgvector ordering
            logger.warning(
                "Elasticsearch returned no results for user %s — falling back to PostgreSQL",
                current_user.id,
            )
            pg_fallback_stmt = (
                select(Job)
                .options(selectinload(Job.company))
                .where(
                    and_(
                        Job.is_active == True,  # noqa: E712
                        not_(exists().where(
                            and_(
                                Swipe.job_id == Job.id,
                                Swipe.user_id == current_user.id,
                                Swipe.is_undone == False,  # noqa: E712
                            )
                        )),
                    )
                )
                .order_by(Job.job_embedding.cosine_distance(current_user.profile_embedding))
                .limit(limit * 5)
            )
            result = await db.execute(pg_fallback_stmt)
            candidate_jobs = result.scalars().all()

        # Re-rank the small candidate pool with the full hybrid ML scorer
        scored_jobs = []
        for job in candidate_jobs:
            if job.job_embedding is not None:
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
                        job_created_at=job.created_at,
                    )
                    scored_jobs.append((job, score))
                except Exception as e:
                    logger.warning("ML scoring failed for job %s: %s", job.id, e)
                    scored_jobs.append((job, 70))
            else:
                scored_jobs.append((job, 60))

        # Sort by score descending, then created_at descending for stability
        scored_jobs.sort(key=lambda x: (x[1], x[0].created_at), reverse=True)

        # Apply cursor filtering if provided
        if cursor_score is not None:
            scored_jobs = [
                (job, score) for job, score in scored_jobs
                if (
                    score < cursor_score
                    or (score == cursor_score and job.created_at < cursor_created_at)
                    or (
                        score == cursor_score
                        and job.created_at == cursor_created_at
                        and str(job.id) > cursor_job_id
                    )
                )
            ]

        top_jobs = scored_jobs[:limit + 1]

    else:
        # ------------------------------------------------------------------
        # Fallback for users without profile embeddings — simple recency
        # ------------------------------------------------------------------
        base_no_embed = (
            select(Job)
            .options(selectinload(Job.company))
            .where(
                and_(
                    Job.is_active == True,  # noqa: E712
                    not_(exists().where(
                        and_(
                            Swipe.job_id == Job.id,
                            Swipe.user_id == current_user.id,
                            Swipe.is_undone == False,  # noqa: E712
                        )
                    )),
                )
            )
        )

        if cursor:
            stmt = (
                base_no_embed
                .where(Job.created_at < cursor_created_at)
                .order_by(Job.created_at.desc())
                .limit(limit + 1)
            )
        else:
            stmt = base_no_embed.order_by(Job.created_at.desc()).limit(limit + 1)

        result = await db.execute(stmt)
        jobs = result.scalars().all()
        top_jobs = [(job, 65) for job in jobs]

    # ------------------------------------------------------------------
    # 3. Format and return
    # ------------------------------------------------------------------
    has_more = len(top_jobs) > limit
    items_to_return = top_jobs[:limit]

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
            "currency": job.currency,
            "salary_negotiable": job.salary_negotiable,
            "work_arrangement": job.work_arrangement,
            "job_type": job.job_type,
            "remote": job.remote,
            "is_active": job.is_active,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "company": {
                "id": job.company.id,
                "name": job.company.name,
                "description": job.company.description,
                "website": job.company.website,
                "logo_url": job.company.logo_url,
                "industry": job.company.industry,
                "size": job.company.size,
                "location": job.company.location,
                "founded_year": job.company.founded_year,
                "is_verified": job.company.is_verified,
            } if job.company else None,
            "score": score,
        }
        job_results.append(JobWithCompany(**job_data))

    next_cursor = None
    if has_more and items_to_return:
        last_job, last_score = items_to_return[-1]
        next_cursor = encode_cursor(last_score, last_job.id, last_job.created_at)

    response = DiscoverResponse(items=job_results, next_cursor=next_cursor)

    # Cache first-page results to avoid re-running kNN + reranking on rapid refreshes
    if cursor is None:
        await set_cached_discover(str(current_user.id), response.model_dump_json())

    return response


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


@router.post("/search", response_model=JobSearchResponse)
async def search_jobs(
    request: Request,
    search_request: JobSearchRequest,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Advanced job search with comprehensive filters.

    This endpoint provides powerful search and filtering capabilities:
    - Keyword search across job title, company name, and description
    - Salary range filtering with currency support
    - Multi-select location filtering
    - Work arrangement filtering (Remote/Hybrid/On-site)
    - Seniority level filtering
    - Job type filtering (Full-time/Part-time/Contract/etc.)
    - Skills/tags filtering
    - Multiple sort options (match score, posted date, salary)
    - ML-powered match scoring for personalized results

    The search automatically saves to the user's recent searches.
    """
    # Rate limit: 60 search requests per minute per user
    is_allowed, retry_after = await rate_limit_service.check_rate_limit(
        key=f"search:user:{current_user.id}",
        max_requests=60,
        window_seconds=60,
    )
    if not is_allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many search requests. Please slow down.",
            headers={"Retry-After": str(retry_after)},
        )

    # Extract filter parameters from request
    filters_used = search_request.model_dump(exclude_unset=True, exclude={"skip", "limit", "sort_by", "sort_order"})

    # Perform search
    scored_jobs, total = await search_service.search_jobs(
        db=db,
        user=current_user,
        keyword=search_request.keyword,
        salary_min=search_request.salary_min,
        salary_max=search_request.salary_max,
        currency=search_request.currency,
        salary_negotiable=search_request.salary_negotiable,
        locations=search_request.locations,
        work_arrangement=[w.value for w in search_request.work_arrangement] if search_request.work_arrangement else None,
        seniority_levels=[s.value for s in search_request.seniority_levels] if search_request.seniority_levels else None,
        job_types=[j.value for j in search_request.job_types] if search_request.job_types else None,
        skills=search_request.skills,
        sort_by=search_request.sort_by.value if search_request.sort_by else "match_score",
        sort_order=search_request.sort_order.value if search_request.sort_order else "desc",
        skip=search_request.skip,
        limit=search_request.limit
    )

    # Save to recent searches (async, don't wait)
    try:
        await search_service.save_recent_search(
            db=db,
            user_id=current_user.id,
            query=search_request.keyword,
            filters_used=filters_used if filters_used else None
        )
        await db.commit()
    except Exception as e:
        # Don't fail the search if saving recent search fails
        logger.error(f"Failed to save recent search: {e}")

    # Convert to response format
    job_results = []
    for job, score in scored_jobs:
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
            "currency": job.currency,
            "remote": job.remote,
            "work_arrangement": job.work_arrangement,
            "job_type": job.job_type,
            "is_active": job.is_active,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "company": {
                "id": job.company.id,
                "name": job.company.name,
                "description": job.company.description,
                "website": job.company.website,
                "logo_url": job.company.logo_url,
                "industry": job.company.industry,
                "size": job.company.size,
                "location": job.company.location,
                "founded_year": job.company.founded_year,
                "is_verified": job.company.is_verified
            } if job.company else None,
            "score": score
        }
        job_results.append(job_data)

    return JobSearchResponse(
        items=job_results,
        total=total,
        skip=search_request.skip,
        limit=search_request.limit
    )
