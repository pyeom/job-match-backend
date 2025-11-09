from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, desc
from sqlalchemy.orm import selectinload
from typing import Optional
from app.core.database import get_db
from app.api.deps import (
    get_current_user,
    get_company_user_with_verification,
    require_company_access
)
from app.models.user import User
from app.models.company import Company
from app.models.job import Job
from app.models.application import Application
from app.schemas.company import PaginatedResponse
from app.schemas.job import Job as JobSchema, JobCreate, JobUpdate
from app.schemas.application import UserBasicInfo, JobBasicInfo
from app.services.embedding_service import EmbeddingService
from pydantic import BaseModel
from datetime import datetime, timedelta
import uuid


class JobApplicationStats(BaseModel):
    """Application statistics for a specific job"""
    job_id: uuid.UUID
    job_title: str
    total_applications: int
    pending_applications: int
    in_review_applications: int
    hired_applications: int
    rejected_applications: int
    created_at: datetime


class CompanyApplicationMetrics(BaseModel):
    """Overall application metrics for the company"""
    total_applications: int
    applications_last_30_days: int
    applications_last_7_days: int
    avg_applications_per_job: float
    most_applied_job: Optional[JobApplicationStats] = None
    conversion_rate: float  # hired / total applications
    jobs_with_applications: list[JobApplicationStats]


class JobApplicationCount(BaseModel):
    """Simple job application count for dashboard widgets"""
    job_id: uuid.UUID
    job_title: str
    application_count: int
    is_active: bool


class ApplicationCounts(BaseModel):
    """Application counts by status for a job"""
    total: int
    pending: int
    accepted: int
    rejected: int


class JobWithApplications(BaseModel):
    """Job information with application stage and status counts"""
    id: uuid.UUID
    title: str
    location: Optional[str] = None
    created_at: datetime
    is_active: bool
    needs_attention: bool  # True if there are pending applications
    total_applications: int
    stage_counts: dict[str, int]  # SUBMITTED, REVIEW, INTERVIEW, TECHNICAL, DECISION
    status_counts: dict[str, int]  # ACTIVE, HIRED, REJECTED


class JobsWithApplicationsResponse(BaseModel):
    """Response for jobs-with-applications endpoint"""
    items: list[JobWithApplications]  # Changed from "jobs" to match frontend
    total: int  # Changed from "total_jobs" to match frontend
    page: int
    limit: int
    has_more: bool


router = APIRouter()


@router.post("/{company_id}/jobs", response_model=JobSchema)
async def create_job(
    company_id: uuid.UUID,
    job_data: JobCreate,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """Create a new job posting for the company"""
    # Verify company access
    require_company_access(current_user, company_id)

    # Create job with company_id
    job = Job(
        id=uuid.uuid4(),
        company_id=company_id,
        **job_data.dict()
    )

    db.add(job)
    await db.flush()  # Get the job ID

    # Generate job embedding
    try:
        # Get company information for embedding
        company_result = await db.execute(
            select(Company).where(Company.id == company_id)
        )
        company = company_result.scalar_one()

        embedding_service = EmbeddingService()
        # Use short_description for embedding, fallback to description
        job_text = f"{job.title} {company.name} {' '.join(job.tags or [])} {job.short_description or job.description or ''}"
        job.job_embedding = await embedding_service.generate_job_embedding(job_text)
    except Exception as e:
        # Log error but don't fail job creation
        print(f"Failed to generate embedding for job {job.id}: {e}")

    await db.commit()
    await db.refresh(job)

    # Load the job with company relationship explicitly to avoid serialization issues
    result = await db.execute(
        select(Job)
        .options(selectinload(Job.company))
        .where(Job.id == job.id)
    )
    refreshed_job = result.scalar_one()

    return refreshed_job


@router.get("/{company_id}/jobs", response_model=PaginatedResponse[JobSchema])
async def get_company_jobs(
    company_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=50),
    page: int = Query(1, ge=1),
    offset: Optional[int] = Query(None, ge=0),
    active_only: bool = Query(True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all jobs for the company with pagination - accessible by job seekers and company users"""
    # Job seekers can only see active jobs, company users can see all based on active_only param
    is_company_user = (current_user.company_id == company_id)

    if is_company_user:
        # Company users can see all jobs based on active_only parameter
        pass
    else:
        # Job seekers can only see active jobs
        active_only = True

    # Calculate offset from page if not provided directly
    if offset is None:
        offset = (page - 1) * limit

    # Build base query
    base_query = select(Job).where(Job.company_id == company_id)

    if active_only:
        base_query = base_query.where(Job.is_active == True)

    # Get total count
    count_result = await db.execute(
        select(func.count(Job.id)).select_from(base_query.subquery())
    )
    total = count_result.scalar() or 0

    # Get paginated jobs
    jobs_query = (
        base_query
        .options(selectinload(Job.company))
        .order_by(desc(Job.created_at))
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(jobs_query)
    jobs = result.scalars().all()

    return PaginatedResponse(
        items=jobs,
        total=total,
        page=page,
        limit=limit
    )


@router.get("/{company_id}/jobs/{job_id}", response_model=JobSchema)
async def get_company_job(
    company_id: uuid.UUID,
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific job for the company - accessible by job seekers and company users"""
    # Check if user is a company user for this company
    is_company_user = (current_user.company_id == company_id)

    # Build query based on user type
    query = select(Job).options(selectinload(Job.company)).where(
        Job.id == job_id,
        Job.company_id == company_id
    )

    # Job seekers can only see active jobs
    if not is_company_user:
        query = query.where(Job.is_active == True)

    result = await db.execute(query)
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return job


@router.patch("/{company_id}/jobs/{job_id}", response_model=JobSchema)
async def update_company_job(
    company_id: uuid.UUID,
    job_id: uuid.UUID,
    job_update: JobUpdate,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """Update a specific job for the company"""
    # Verify company access
    require_company_access(current_user, company_id)

    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.company_id == company_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Update job fields
    update_data = job_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(job, field, value)

    # Regenerate embedding if content changed
    if any(field in update_data for field in ['title', 'short_description', 'description', 'tags']):
        try:
            # Get company information for embedding
            company_result = await db.execute(
                select(Company).where(Company.id == company_id)
            )
            company = company_result.scalar_one()

            embedding_service = EmbeddingService()
            # Use short_description for embedding, fallback to description
            job_text = f"{job.title} {company.name} {' '.join(job.tags or [])} {job.short_description or job.description or ''}"
            job.job_embedding = await embedding_service.generate_job_embedding(job_text)
        except Exception as e:
            print(f"Failed to regenerate embedding for job {job.id}: {e}")

    await db.commit()
    await db.refresh(job, ['company'])

    return job


@router.delete("/{company_id}/jobs/{job_id}")
async def delete_company_job(
    company_id: uuid.UUID,
    job_id: uuid.UUID,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """Deactivate a job (soft delete)"""
    # Verify company access
    require_company_access(current_user, company_id)

    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.company_id == company_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Soft delete by setting is_active to False
    job.is_active = False
    await db.commit()

    return {"message": "Job deactivated successfully"}


@router.get("/{company_id}/jobs/application-stats", response_model=list[JobApplicationStats])
async def get_jobs_application_stats(
    company_id: uuid.UUID,
    active_only: bool = Query(True),
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """Get application statistics for all company jobs"""
    # Verify company access
    require_company_access(current_user, company_id)

    # Build query to get job application stats
    from sqlalchemy import case

    jobs_filter = [Job.company_id == company_id]
    if active_only:
        jobs_filter.append(Job.is_active == True)

    result = await db.execute(
        select(
            Job.id,
            Job.title,
            Job.created_at,
            func.count(Application.id).label("total_applications"),
            func.count(case((Application.status == "SUBMITTED", 1))).label("pending_applications"),
            func.count(case((Application.status.in_(["WAITING_FOR_REVIEW", "HR_MEETING", "TECHNICAL_INTERVIEW", "FINAL_INTERVIEW"]), 1))).label("in_review_applications"),
            func.count(case((Application.status == "HIRED", 1))).label("hired_applications"),
            func.count(case((Application.status == "REJECTED", 1))).label("rejected_applications")
        )
        .select_from(Job)
        .outerjoin(Application, Application.job_id == Job.id)
        .where(and_(*jobs_filter))
        .group_by(Job.id, Job.title, Job.created_at)
        .order_by(desc(Job.created_at))
    )

    rows = result.all()

    job_stats = []
    for row in rows:
        job_stats.append(JobApplicationStats(
            job_id=row.id,
            job_title=row.title,
            total_applications=row.total_applications or 0,
            pending_applications=row.pending_applications or 0,
            in_review_applications=row.in_review_applications or 0,
            hired_applications=row.hired_applications or 0,
            rejected_applications=row.rejected_applications or 0,
            created_at=row.created_at
        ))

    return job_stats


@router.get("/{company_id}/jobs/application-counts", response_model=list[JobApplicationCount])
async def get_simple_job_application_counts(
    company_id: uuid.UUID,
    active_only: bool = Query(True),
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """Get simple application counts per job for dashboard widgets"""
    # Verify company access
    require_company_access(current_user, company_id)

    # Build query for simple counts
    jobs_filter = [Job.company_id == company_id]
    if active_only:
        jobs_filter.append(Job.is_active == True)

    result = await db.execute(
        select(
            Job.id,
            Job.title,
            Job.is_active,
            func.count(Application.id).label("application_count")
        )
        .select_from(Job)
        .outerjoin(Application, Application.job_id == Job.id)
        .where(and_(*jobs_filter))
        .group_by(Job.id, Job.title, Job.is_active)
        .order_by(desc(func.count(Application.id)))
    )

    rows = result.all()

    job_counts = []
    for row in rows:
        job_counts.append(JobApplicationCount(
            job_id=row.id,
            job_title=row.title,
            application_count=row.application_count or 0,
            is_active=row.is_active
        ))

    return job_counts


@router.get("/{company_id}/jobs-with-applications", response_model=JobsWithApplicationsResponse)
async def get_jobs_with_applications(
    company_id: uuid.UUID,
    filter: str = Query("all", regex="^(all|active|needs_attention)$"),
    sort_by: str = Query("newest_applications", regex="^(most_applications|newest_applications|created_date)$"),
    limit: int = Query(20, ge=1, le=100),  # Changed default from 50 to 20
    page: int = Query(1, ge=1),
    offset: Optional[int] = Query(None, ge=0),
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """
    Get jobs with their application counts and recent applicants for company applications management.

    This endpoint implements the correct business logic for company application management:
    - Returns jobs organized with application counts (total, pending, accepted, rejected)
    - Includes up to 3 recent applicants per job for quick overview
    - Supports pagination and filtering by active/inactive jobs
    - Optimized with efficient SQL queries to avoid N+1 problems

    Use this endpoint for the main Applications tab in the company dashboard.
    For detailed applications of a specific job, use: GET /companies/{company_id}/jobs/{job_id}/applications
    """
    # Verify company access
    require_company_access(current_user, company_id)

    # Calculate offset from page if not provided directly
    if offset is None:
        offset = (page - 1) * limit

    # Build base query for jobs
    from sqlalchemy import case, text

    jobs_filter = [Job.company_id == company_id]

    # Apply filter parameter
    if filter == "active":
        jobs_filter.append(Job.is_active == True)
    # filter == "all" doesn't add additional filter
    # filter == "needs_attention" will be handled after we get the results (needs pending applications > 0)

    # Main query to get jobs with aggregated application counts by stage and status
    # Using efficient SQL to avoid N+1 queries
    jobs_query = (
        select(
            Job.id,
            Job.title,
            Job.location,
            Job.created_at,
            Job.is_active,
            func.count(Application.id).label("total_applications"),
            # Stage counts
            func.count(case((Application.stage == "SUBMITTED", 1))).label("stage_submitted"),
            func.count(case((Application.stage == "REVIEW", 1))).label("stage_review"),
            func.count(case((Application.stage == "INTERVIEW", 1))).label("stage_interview"),
            func.count(case((Application.stage == "TECHNICAL", 1))).label("stage_technical"),
            func.count(case((Application.stage == "DECISION", 1))).label("stage_decision"),
            # Status counts
            func.count(case((Application.status == "ACTIVE", 1))).label("status_active"),
            func.count(case((Application.status == "HIRED", 1))).label("status_hired"),
            func.count(case((Application.status == "REJECTED", 1))).label("status_rejected"),
            func.max(Application.created_at).label("most_recent_application_at")
        )
        .select_from(Job)
        .outerjoin(Application, Application.job_id == Job.id)
        .where(and_(*jobs_filter))
        .group_by(Job.id, Job.title, Job.location, Job.created_at, Job.is_active)
    )

    # Apply sorting based on sort_by parameter
    if sort_by == "most_applications":
        jobs_query = jobs_query.order_by(desc(func.count(Application.id)), desc(Job.created_at))
    elif sort_by == "newest_applications":
        jobs_query = jobs_query.order_by(desc(func.max(Application.created_at)), desc(Job.created_at))
    else:  # created_date
        jobs_query = jobs_query.order_by(desc(Job.created_at))

    jobs_query = jobs_query.offset(offset).limit(limit)

    job_results = await db.execute(jobs_query)
    job_rows = job_results.all()

    # Get total count of jobs for pagination metadata
    count_query = select(func.count(Job.id)).where(and_(*jobs_filter))
    count_result = await db.execute(count_query)
    total_jobs = count_result.scalar() or 0

    # Prepare jobs list with application data
    jobs_with_applications = []

    for row in job_rows:
        total_apps = row.total_applications or 0

        # Build stage counts dictionary
        stage_counts = {
            "SUBMITTED": row.stage_submitted or 0,
            "REVIEW": row.stage_review or 0,
            "INTERVIEW": row.stage_interview or 0,
            "TECHNICAL": row.stage_technical or 0,
            "DECISION": row.stage_decision or 0
        }

        # Build status counts dictionary
        status_counts = {
            "ACTIVE": row.status_active or 0,
            "HIRED": row.status_hired or 0,
            "REJECTED": row.status_rejected or 0
        }

        # Needs attention if there are any ACTIVE applications (regardless of stage)
        needs_attention = status_counts["ACTIVE"] > 0

        job_with_apps = JobWithApplications(
            id=row.id,
            title=row.title,
            location=row.location,
            created_at=row.created_at,
            is_active=row.is_active,
            needs_attention=needs_attention,
            total_applications=total_apps,
            stage_counts=stage_counts,
            status_counts=status_counts
        )

        jobs_with_applications.append(job_with_apps)

    # Apply "needs_attention" filter if specified (after building all jobs)
    if filter == "needs_attention":
        jobs_with_applications = [job for job in jobs_with_applications if job.needs_attention]

    # Calculate has_more for pagination
    has_more = total_jobs > (offset + limit)

    return JobsWithApplicationsResponse(
        items=jobs_with_applications,  # Changed from "jobs" to "items"
        total=total_jobs,  # Changed from "total_jobs" to "total"
        page=page,
        limit=limit,
        has_more=has_more
    )


@router.get("/{company_id}/application-metrics", response_model=CompanyApplicationMetrics)
async def get_company_application_metrics(
    company_id: uuid.UUID,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """Get comprehensive application metrics for the company"""
    # Verify company access
    require_company_access(current_user, company_id)

    # Get overall metrics
    from sqlalchemy import case

    thirty_days_ago = datetime.now() - timedelta(days=30)
    seven_days_ago = datetime.now() - timedelta(days=7)

    # Total applications and time-based counts
    metrics_result = await db.execute(
        select(
            func.count(Application.id).label("total_applications"),
            func.count(case((Application.created_at >= thirty_days_ago, 1))).label("last_30_days"),
            func.count(case((Application.created_at >= seven_days_ago, 1))).label("last_7_days"),
            func.count(case((Application.status == "HIRED", 1))).label("hired_count")
        )
        .select_from(Application)
        .join(Job, Application.job_id == Job.id)
        .where(Job.company_id == company_id)
    )
    metrics_row = metrics_result.first()

    total_applications = metrics_row.total_applications or 0
    applications_last_30_days = metrics_row.last_30_days or 0
    applications_last_7_days = metrics_row.last_7_days or 0
    hired_count = metrics_row.hired_count or 0

    # Calculate conversion rate
    conversion_rate = (hired_count / total_applications * 100) if total_applications > 0 else 0.0

    # Get job count for average calculation
    job_count_result = await db.execute(
        select(func.count(Job.id)).where(Job.company_id == company_id, Job.is_active == True)
    )
    job_count = job_count_result.scalar() or 1

    # Calculate average applications per job
    avg_applications_per_job = total_applications / job_count if job_count > 0 else 0.0

    # Get most applied job
    most_applied_result = await db.execute(
        select(
            Job.id,
            Job.title,
            Job.created_at,
            func.count(Application.id).label("total_applications"),
            func.count(case((Application.status == "SUBMITTED", 1))).label("pending_applications"),
            func.count(case((Application.status.in_(["WAITING_FOR_REVIEW", "HR_MEETING", "TECHNICAL_INTERVIEW", "FINAL_INTERVIEW"]), 1))).label("in_review_applications"),
            func.count(case((Application.status == "HIRED", 1))).label("hired_applications"),
            func.count(case((Application.status == "REJECTED", 1))).label("rejected_applications")
        )
        .select_from(Job)
        .join(Application, Application.job_id == Job.id)
        .where(Job.company_id == company_id)
        .group_by(Job.id, Job.title, Job.created_at)
        .order_by(desc(func.count(Application.id)))
        .limit(1)
    )
    most_applied_row = most_applied_result.first()

    most_applied_job = None
    if most_applied_row and most_applied_row.total_applications > 0:
        most_applied_job = JobApplicationStats(
            job_id=most_applied_row.id,
            job_title=most_applied_row.title,
            total_applications=most_applied_row.total_applications,
            pending_applications=most_applied_row.pending_applications or 0,
            in_review_applications=most_applied_row.in_review_applications or 0,
            hired_applications=most_applied_row.hired_applications or 0,
            rejected_applications=most_applied_row.rejected_applications or 0,
            created_at=most_applied_row.created_at
        )

    # Get all jobs with applications for detailed view
    jobs_with_apps_result = await db.execute(
        select(
            Job.id,
            Job.title,
            Job.created_at,
            func.count(Application.id).label("total_applications"),
            func.count(case((Application.status == "SUBMITTED", 1))).label("pending_applications"),
            func.count(case((Application.status.in_(["WAITING_FOR_REVIEW", "HR_MEETING", "TECHNICAL_INTERVIEW", "FINAL_INTERVIEW"]), 1))).label("in_review_applications"),
            func.count(case((Application.status == "HIRED", 1))).label("hired_applications"),
            func.count(case((Application.status == "REJECTED", 1))).label("rejected_applications")
        )
        .select_from(Job)
        .join(Application, Application.job_id == Job.id)
        .where(Job.company_id == company_id, Job.is_active == True)
        .group_by(Job.id, Job.title, Job.created_at)
        .having(func.count(Application.id) > 0)
        .order_by(desc(func.count(Application.id)))
    )

    jobs_with_applications = []
    for row in jobs_with_apps_result.all():
        jobs_with_applications.append(JobApplicationStats(
            job_id=row.id,
            job_title=row.title,
            total_applications=row.total_applications,
            pending_applications=row.pending_applications or 0,
            in_review_applications=row.in_review_applications or 0,
            hired_applications=row.hired_applications or 0,
            rejected_applications=row.rejected_applications or 0,
            created_at=row.created_at
        ))

    return CompanyApplicationMetrics(
        total_applications=total_applications,
        applications_last_30_days=applications_last_30_days,
        applications_last_7_days=applications_last_7_days,
        avg_applications_per_job=round(avg_applications_per_job, 2),
        most_applied_job=most_applied_job,
        conversion_rate=round(conversion_rate, 2),
        jobs_with_applications=jobs_with_applications
    )
