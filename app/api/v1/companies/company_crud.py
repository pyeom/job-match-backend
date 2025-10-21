from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, desc, case
from typing import List
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
from app.schemas.company import (
    Company as CompanySchema,
    CompanyPublic,
    CompanyUpdate,
    CompanyDashboardStats
)
from pydantic import BaseModel
import uuid


class CompanyEmployeesResponse(BaseModel):
    """Response model for company employees endpoint"""
    employees: List[dict] = []
    message: str


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
    from app.models.application import Application

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
