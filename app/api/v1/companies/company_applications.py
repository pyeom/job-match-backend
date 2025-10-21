from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, desc
from typing import Optional
from datetime import datetime
from app.core.database import get_db
from app.api.deps import (
    get_company_user_with_verification,
    require_company_access
)
from app.models.user import User
from app.models.job import Job
from app.models.application import Application
from app.models.company import Company
from app.schemas.company import PaginatedResponse
from app.schemas.application import (
    ApplicationWithDetails,
    ApplicationWithUserResponse,
    UserBasicInfo,
    JobDetails,
    CompanyDetails
)
from pydantic import BaseModel
import uuid


class ApplicationStatusUpdate(BaseModel):
    status: str


router = APIRouter()


@router.get("/{company_id}/jobs/{job_id}/applications", response_model=PaginatedResponse[ApplicationWithDetails])
async def get_job_applications(
    company_id: uuid.UUID,
    job_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=100),
    page: int = Query(1, ge=1),
    offset: Optional[int] = Query(None, ge=0),
    status_filter: Optional[str] = Query(None),
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """Get all applications for a specific job"""
    # Verify company access
    require_company_access(current_user, company_id)

    # Verify job belongs to company
    job_result = await db.execute(
        select(Job).where(Job.id == job_id, Job.company_id == company_id)
    )
    job = job_result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Calculate offset from page if not provided directly
    if offset is None:
        offset = (page - 1) * limit

    # Build base query - need to join Company for JobDetails
    base_query = (
        select(Application, User, Job, Company)
        .select_from(Application)
        .join(Job, Application.job_id == Job.id)
        .join(User, Application.user_id == User.id)
        .join(Company, Job.company_id == Company.id)
        .where(Application.job_id == job_id)
    )

    # Apply status filter
    if status_filter:
        base_query = base_query.where(Application.status == status_filter)

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
    for app, user, job_info, company in rows:
        user_info = UserBasicInfo(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            skills=user.skills,
            seniority=user.seniority,
            location=user.preferred_locations[0] if user.preferred_locations else None
        )

        company_details = CompanyDetails(
            id=company.id,
            name=company.name,
            logo_url=company.logo_url,
            location=company.location,
            size=company.size,
            industry=company.industry
        )

        job_details = JobDetails(
            id=job_info.id,
            title=job_info.title,
            location=job_info.location,
            seniority=job_info.seniority,
            short_description=job_info.short_description,
            description=job_info.description,
            tags=job_info.tags,
            salary_min=job_info.salary_min,
            salary_max=job_info.salary_max,
            remote=job_info.remote,
            created_at=job_info.created_at,
            company=company_details
        )

        app_dict = ApplicationWithDetails.from_orm(app).dict()
        app_dict["user"] = user_info
        app_dict["job"] = job_details

        applications_with_details.append(ApplicationWithDetails(**app_dict))

    return PaginatedResponse(
        items=applications_with_details,
        total=total,
        page=page,
        limit=limit
    )


@router.patch("/applications/{application_id}", response_model=ApplicationWithUserResponse)
async def update_application_status(
    application_id: uuid.UUID,
    status_update: ApplicationStatusUpdate,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """Update application status"""
    # Get application with job, user and verify company access
    result = await db.execute(
        select(Application, User, Job)
        .select_from(Application)
        .join(Job, Application.job_id == Job.id)
        .join(User, Application.user_id == User.id)
        .where(Application.id == application_id)
    )
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Application not found")

    application, user, job = row
    require_company_access(current_user, job.company_id)

    # Map frontend status to backend status
    def map_status_to_backend(frontend_status: str) -> str:
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
        return status_mapping.get(frontend_status, frontend_status)

    def map_status_to_frontend(backend_status: str) -> str:
        status_mapping = {
            'HIRED': 'ACCEPTED',
            'REJECTED': 'REJECTED',
            'SUBMITTED': 'SUBMITTED',
            'WAITING_FOR_REVIEW': 'SUBMITTED',
            'HR_MEETING': 'SUBMITTED',
            'TECHNICAL_INTERVIEW': 'SUBMITTED',
            'FINAL_INTERVIEW': 'SUBMITTED'
        }
        return status_mapping.get(backend_status, backend_status)

    backend_status = map_status_to_backend(status_update.status)

    # Update status
    application.status = backend_status
    await db.commit()
    await db.refresh(application)

    # Return flattened response format
    return ApplicationWithUserResponse(
        id=application.id,
        job_id=application.job_id,
        job_title=job.title,
        user_id=application.user_id,
        user_email=user.email,
        user_full_name=user.full_name,
        user_headline=user.headline,
        user_skills=user.skills,
        status=map_status_to_frontend(application.status),
        created_at=application.created_at,
        updated_at=application.updated_at or application.created_at
    )


@router.get("/applications", response_model=PaginatedResponse[ApplicationWithUserResponse])
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

    # Transform to flattened response format expected by frontend
    def map_status_to_frontend(backend_status: str) -> str:
        """Map backend status to frontend status"""
        status_mapping = {
            'HIRED': 'ACCEPTED',
            'REJECTED': 'REJECTED',
            'SUBMITTED': 'SUBMITTED',
            'WAITING_FOR_REVIEW': 'SUBMITTED',
            'HR_MEETING': 'SUBMITTED',
            'TECHNICAL_INTERVIEW': 'SUBMITTED',
            'FINAL_INTERVIEW': 'SUBMITTED'
        }
        return status_mapping.get(backend_status, backend_status)

    applications_with_user_response = []
    for app, user, job in rows:
        flattened_app = ApplicationWithUserResponse(
            id=app.id,
            job_id=app.job_id,
            job_title=job.title,
            user_id=app.user_id,
            user_email=user.email,
            user_full_name=user.full_name,
            user_headline=user.headline,
            user_skills=user.skills,
            status=map_status_to_frontend(app.status),
            created_at=app.created_at,
            updated_at=app.updated_at or app.created_at
        )
        applications_with_user_response.append(flattened_app)

    return PaginatedResponse(
        items=applications_with_user_response,
        total=total,
        page=page,
        limit=limit
    )
