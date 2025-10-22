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
    ApplicationUpdate,
    ApplicationWithDetails,
    ApplicationWithUserResponse,
    UserBasicInfo,
    JobDetails,
    CompanyDetails
)
from pydantic import BaseModel
import uuid


# Stage transition validation
VALID_STAGES = ['SUBMITTED', 'REVIEW', 'INTERVIEW', 'TECHNICAL', 'DECISION']

STAGE_TRANSITIONS = {
    'SUBMITTED': ['REVIEW'],
    'REVIEW': ['INTERVIEW', 'SUBMITTED'],  # Can go back
    'INTERVIEW': ['TECHNICAL', 'REVIEW'],  # Can go back
    'TECHNICAL': ['DECISION', 'INTERVIEW'],  # Can go back
    'DECISION': ['TECHNICAL']  # Can go back
}


def validate_stage_transition(current_stage: str, new_stage: str) -> bool:
    """Validate if stage transition is allowed"""
    if current_stage == new_stage:
        return True  # No change is valid

    # Forward progression
    if new_stage in STAGE_TRANSITIONS.get(current_stage, []):
        return True

    # Backward progression (allow going back to any previous stage)
    stage_order = VALID_STAGES
    current_idx = stage_order.index(current_stage)
    new_idx = stage_order.index(new_stage)
    if new_idx < current_idx:
        return True

    return False


router = APIRouter()


@router.get("/{company_id}/jobs/{job_id}/applications", response_model=PaginatedResponse[ApplicationWithDetails])
async def get_job_applications(
    company_id: uuid.UUID,
    job_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=100),
    page: int = Query(1, ge=1),
    offset: Optional[int] = Query(None, ge=0),
    stage_filter: Optional[str] = Query(None),  # NEW: Filter by stage
    status_filter: Optional[str] = Query(None),  # Updated: Filter by status (ACTIVE, HIRED, REJECTED)
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """Get all applications for a specific job with stage/status filtering"""
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

    # Apply stage filter (NEW)
    if stage_filter:
        base_query = base_query.where(Application.stage == stage_filter)

    # Apply status filter (UPDATED)
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
    update_data: ApplicationUpdate,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """
    Update application stage and/or status

    - **stage**: Move to new pipeline stage (SUBMITTED, REVIEW, INTERVIEW, TECHNICAL, DECISION)
    - **status**: Set final status (ACTIVE, HIRED, REJECTED)
    - **rejection_reason**: Required when status=REJECTED
    - **notes**: Internal notes

    Validation rules:
    - Cannot modify applications in terminal state (HIRED/REJECTED)
    - Stage transitions must be valid (can move forward sequentially or backward)
    - Rejection requires rejection_reason
    - Stage and status can be updated independently or together
    """
    # Get application with job and user
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

    # Validate: Cannot modify terminal state applications
    if application.status in ['HIRED', 'REJECTED']:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot modify application in terminal state ({application.status})"
        )

    # Track if stage changed for stage_updated_at
    stage_changed = False

    # Validate and update stage
    if update_data.stage is not None:
        if not validate_stage_transition(application.stage, update_data.stage):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid stage transition from {application.stage} to {update_data.stage}"
            )
        if application.stage != update_data.stage:
            stage_changed = True

            # Update stage_history
            if application.stage_history is None:
                application.stage_history = []

            application.stage_history.append({
                "from_stage": application.stage,
                "to_stage": update_data.stage,
                "timestamp": datetime.utcnow().isoformat(),
                "changed_by": str(current_user.id)
            })

            application.stage = update_data.stage

    # Update status
    if update_data.status is not None:
        if update_data.status == 'REJECTED' and not update_data.rejection_reason:
            raise HTTPException(
                status_code=400,
                detail="rejection_reason is required when status=REJECTED"
            )
        application.status = update_data.status
        if update_data.rejection_reason:
            application.rejection_reason = update_data.rejection_reason

    # Update other fields
    if update_data.notes is not None:
        application.notes = update_data.notes

    # Update stage_updated_at if stage changed
    if stage_changed:
        application.stage_updated_at = func.now()

    await db.commit()
    await db.refresh(application)

    # Return new format (no more status mapping)
    return ApplicationWithUserResponse(
        id=application.id,
        job_id=application.job_id,
        job_title=job.title,
        user_id=application.user_id,
        user_email=user.email,
        user_full_name=user.full_name,
        user_headline=user.headline,
        user_skills=user.skills,
        stage=application.stage,
        status=application.status,
        stage_updated_at=application.stage_updated_at,
        rejection_reason=application.rejection_reason,
        created_at=application.created_at,
        updated_at=application.updated_at or application.created_at
    )


@router.get("/applications", response_model=PaginatedResponse[ApplicationWithUserResponse])
async def get_all_company_applications(
    limit: int = Query(50, ge=1, le=100),
    page: int = Query(1, ge=1),
    offset: Optional[int] = Query(None, ge=0),
    stage_filter: Optional[str] = Query(None),  # NEW: Filter by stage
    status_filter: Optional[str] = Query(None),  # Updated: Filter by status (ACTIVE, HIRED, REJECTED)
    seniority_filter: Optional[str] = Query(None),
    location_filter: Optional[str] = Query(None),
    created_after: Optional[datetime] = Query(None),
    created_before: Optional[datetime] = Query(None),
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """Get all applications for company with stage/status filtering"""
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
    if stage_filter:
        base_query = base_query.where(Application.stage == stage_filter)

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

    # Transform to flattened response format - NO MORE STATUS MAPPING
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
            stage=app.stage,  # NEW: Direct stage
            status=app.status,  # NEW: Direct status
            stage_updated_at=app.stage_updated_at,  # NEW
            rejection_reason=app.rejection_reason,  # NEW
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
