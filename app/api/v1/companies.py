from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, desc, case, text
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime, timedelta
from app.core.database import get_db
from app.api.deps import (
    get_current_user, 
    get_company_user_with_verification, 
    get_company_admin,
    require_company_access
)
from app.models.user import User
from app.models.company import Company
from app.models.job import Job
from app.models.application import Application
from app.schemas.company import (
    Company as CompanySchema,
    CompanyPublic,
    CompanyUpdate,
    CompanyDashboardStats,
    PaginatedResponse
)
from app.schemas.application import ApplicationWithDetails, UserBasicInfo, JobBasicInfo
from app.schemas.job import Job as JobSchema, JobCreate, JobUpdate
from app.services.embedding_service import EmbeddingService
from pydantic import BaseModel
import uuid

router = APIRouter()


@router.get("/", response_model=List[CompanyPublic])
async def get_companies(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """Get list of all active companies (for browsing)"""
    result = await db.execute(
        select(Company)
        .where(Company.is_active == True)
        .order_by(Company.name)
        .offset(offset)
        .limit(limit)
    )
    companies = result.scalars().all()
    return companies


@router.get("/public/{company_id}", response_model=CompanyPublic)
async def get_company_public(
    company_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get public company information by ID (no authentication required)"""
    result = await db.execute(
        select(Company).where(
            and_(
                Company.id == company_id,
                Company.is_active == True
            )
        )
    )
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    return company


@router.get("/{company_id}", response_model=CompanyPublic)
async def get_company_details(
    company_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get company information by ID - available to all authenticated users"""
    result = await db.execute(
        select(Company).where(
            and_(
                Company.id == company_id,
                Company.is_active == True
            )
        )
    )
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    return company


class CompanyEmployeesResponse(BaseModel):
    """Response model for company employees endpoint"""
    employees: List[dict] = []
    message: str

@router.get("/{company_id}/employees", response_model=CompanyEmployeesResponse)
async def get_company_employees(
    company_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get company employees information - placeholder endpoint for future implementation"""
    # Verify company exists and is active
    result = await db.execute(
        select(Company).where(
            and_(
                Company.id == company_id,
                Company.is_active == True
            )
        )
    )
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # For now, return empty list since employee management is not implemented
    # Future implementation would return actual employee data based on privacy settings
    return CompanyEmployeesResponse(
        employees=[],
        message="Employee information not available or privacy restricted"
    )


@router.get("/{company_id}/admin", response_model=CompanySchema)
async def get_company_admin_details(
    company_id: uuid.UUID,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """Get company information with admin statistics (company users only)"""
    # Verify company access
    require_company_access(current_user, company_id)

    # Load company with statistics
    result = await db.execute(
        select(
            Company,
            func.count(Job.id).label("job_count"),
            func.count(User.id).label("user_count")
        )
        .outerjoin(Job, and_(Job.company_id == Company.id, Job.is_active == True))
        .outerjoin(User, User.company_id == Company.id)
        .where(Company.id == company_id)
        .group_by(Company.id)
    )

    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Company not found")

    company = row[0]
    company_dict = CompanySchema.from_orm(company).dict()
    company_dict["job_count"] = row[1] or 0
    company_dict["user_count"] = row[2] or 0

    return CompanySchema(**company_dict)


@router.patch("/{company_id}", response_model=CompanySchema)
async def update_company(
    company_id: uuid.UUID,
    company_update: CompanyUpdate,
    current_user: User = Depends(get_company_admin),  # Only admins can update company
    db: AsyncSession = Depends(get_db)
):
    """Update company information by ID"""
    # Verify company access
    require_company_access(current_user, company_id)

    result = await db.execute(
        select(Company).where(Company.id == company_id)
    )
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Update company fields
    update_data = company_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(company, field, value)

    await db.commit()
    await db.refresh(company)

    return company


# Legacy endpoints for backward compatibility (deprecated)
@router.get("/me", response_model=CompanySchema, deprecated=True)
async def get_my_company_legacy(
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """
    DEPRECATED: Get current user's company information
    Use GET /companies/{company_id} instead
    """
    # Load company with statistics
    result = await db.execute(
        select(
            Company,
            func.count(Job.id).label("job_count"),
            func.count(User.id).label("user_count")
        )
        .outerjoin(Job, and_(Job.company_id == Company.id, Job.is_active == True))
        .outerjoin(User, User.company_id == Company.id)
        .where(Company.id == current_user.company_id)
        .group_by(Company.id)
    )

    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Company not found")

    company = row[0]
    company_dict = CompanySchema.from_orm(company).dict()
    company_dict["job_count"] = row[1] or 0
    company_dict["user_count"] = row[2] or 0

    return CompanySchema(**company_dict)


@router.patch("/me", response_model=CompanySchema, deprecated=True)
async def update_my_company_legacy(
    company_update: CompanyUpdate,
    current_user: User = Depends(get_company_admin),  # Only admins can update company
    db: AsyncSession = Depends(get_db)
):
    """
    DEPRECATED: Update current user's company information
    Use PATCH /companies/{company_id} instead
    """
    result = await db.execute(
        select(Company).where(Company.id == current_user.company_id)
    )
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Update company fields
    update_data = company_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(company, field, value)

    await db.commit()
    await db.refresh(company)

    return company


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


# REMOVED: Job-specific applications endpoint (unused by frontend)


class ApplicationStatusUpdate(BaseModel):
    status: str

@router.patch("/applications/{application_id}")
async def update_application_status(
    application_id: uuid.UUID,
    status_update: ApplicationStatusUpdate,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """Update application status"""
    # Get application with job and verify company access
    result = await db.execute(
        select(Application)
        .options(selectinload(Application.job))
        .where(Application.id == application_id)
    )
    application = result.scalar_one_or_none()

    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    require_company_access(current_user, application.job.company_id)

    # Map frontend status to backend status
    status_mapping = {
        'ACCEPTED': 'HIRED',
        'REJECTED': 'REJECTED',
        'HIRED': 'HIRED',
        'SUBMITTED': 'SUBMITTED',
        'WAITING_FOR_REVIEW': 'WAITING_FOR_REVIEW',
        'HR_MEETING': 'HR_MEETING',
        'TECHNICAL_INTERVIEW': 'TECHNICAL_INTERVIEW',
        'FINAL_INTERVIEW': 'FINAL_INTERVIEW'
    }

    backend_status = status_mapping.get(status_update.status, status_update.status)

    # Update status
    application.status = backend_status
    await db.commit()

    return {"message": "Application status updated successfully", "status": backend_status}


# REMOVED: Complex company stats endpoint (unused by frontend)


@router.get("/dashboard/stats", response_model=CompanyDashboardStats)
async def get_company_dashboard_stats(
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """Get simple dashboard statistics for frontend"""
    company_id = current_user.company_id

    # Get total and active jobs
    jobs_query = await db.execute(
        select(
            func.count(Job.id).label("total_jobs"),
            func.count(case((Job.is_active == True, 1))).label("active_jobs")
        )
        .where(Job.company_id == company_id)
    )
    jobs_row = jobs_query.first()

    total_jobs = jobs_row.total_jobs or 0
    active_jobs = jobs_row.active_jobs or 0

    # Get application statistics
    applications_query = await db.execute(
        select(
            func.count(Application.id).label("total_applications"),
            func.count(case((Application.status == "SUBMITTED", 1))).label("pending_applications"),
            func.count(case((Application.status == "HIRED", 1))).label("accepted_applications"),
            func.count(case((Application.status == "REJECTED", 1))).label("rejected_applications")
        )
        .select_from(Application)
        .join(Job, Application.job_id == Job.id)
        .where(Job.company_id == company_id)
    )
    apps_row = applications_query.first()

    total_applications = apps_row.total_applications or 0
    pending_applications = apps_row.pending_applications or 0
    accepted_applications = apps_row.accepted_applications or 0
    rejected_applications = apps_row.rejected_applications or 0

    return CompanyDashboardStats(
        total_jobs=total_jobs,
        active_jobs=active_jobs,
        total_applications=total_applications,
        pending_applications=pending_applications,
        accepted_applications=accepted_applications,
        rejected_applications=rejected_applications
    )


# REMOVED: Jobs with metrics endpoint (unused by frontend)


# REMOVED: Bulk job status update endpoint (unused by frontend)


@router.get("/applications", response_model=PaginatedResponse[ApplicationWithDetails])
async def get_all_company_applications(
    limit: int = Query(50, ge=1, le=100),
    page: int = Query(1, ge=1),
    offset: Optional[int] = Query(None, ge=0),
    status_filter: Optional[str] = Query(None),
    seniority_filter: Optional[str] = Query(None),
    location_filter: Optional[str] = Query(None),
    created_after: Optional[datetime] = Query(None),
    created_before: Optional[datetime] = Query(None),
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """Get all applications for the company with filtering and search capabilities"""
    company_id = current_user.company_id

    # Calculate offset from page if not provided directly
    if offset is None:
        offset = (page - 1) * limit

    # Build base query with joins
    base_query = (
        select(Application, User, Job)
        .select_from(Application)
        .join(Job, Application.job_id == Job.id)
        .join(User, Application.user_id == User.id)
        .where(Job.company_id == company_id)
    )

    # Apply filters
    if status_filter:
        base_query = base_query.where(Application.status == status_filter)

    if seniority_filter:
        base_query = base_query.where(User.seniority == seniority_filter)

    if location_filter:
        base_query = base_query.where(Job.location == location_filter)

    if created_after:
        base_query = base_query.where(Application.created_at >= created_after)

    if created_before:
        base_query = base_query.where(Application.created_at <= created_before)

    # Get total count
    count_query = select(func.count()).select_from(base_query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Get paginated results
    paginated_query = base_query.order_by(desc(Application.created_at)).offset(offset).limit(limit)
    result = await db.execute(paginated_query)
    rows = result.all()

    # Transform to response format
    applications_with_details = []
    for app, user, job in rows:
        user_info = UserBasicInfo(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            skills=user.skills,
            seniority=user.seniority,
            location=user.preferred_locations[0] if user.preferred_locations else None
        )

        job_info = JobBasicInfo(
            id=job.id,
            title=job.title,
            location=job.location,
            seniority=job.seniority
        )

        app_dict = ApplicationWithDetails.from_orm(app).dict()
        app_dict["user"] = user_info
        app_dict["job"] = job_info

        applications_with_details.append(ApplicationWithDetails(**app_dict))

    return PaginatedResponse(
        items=applications_with_details,
        total=total,
        page=page,
        limit=limit
    )


# REMOVED: Bulk application status update endpoint (unused by frontend)


# REMOVED: Application export endpoint (unused by frontend)


# REMOVED: Team management endpoints (unused by frontend)






