"""Admin API

GET  /api/v1/admin/model-metrics              — Active predictive model AUC, training samples, last retrain date (B9.2.3)
GET  /api/v1/admin/fairness-reports           — List of monthly fairness audit report dates (B10.2.3)
GET  /api/v1/admin/fairness-reports/{date}    — Detail for a specific fairness audit report (B10.2.4)
GET  /api/v1/admin/companies                  — List all companies with stats
POST /api/v1/admin/companies                  — Create a new company (+ optional first admin user)
PATCH /api/v1/admin/companies/{company_id}    — Update company status / verification
"""
from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_company_admin, get_platform_admin
from app.core.database import get_db
from app.core.security import get_password_hash
from app.models.company import Company
from app.models.job import Job
from app.models.pipeline import DEFAULT_PIPELINE_STAGES, PipelineTemplate
from app.models.user import CompanyRole, User, UserRole

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Admin"])


# ---------------------------------------------------------------------------
# Schemas (local to admin — no need to pollute global schemas)
# ---------------------------------------------------------------------------


class AdminCompanyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    size: Optional[str] = None
    location: Optional[str] = None
    # Optional: create the first admin user in one shot
    admin_email: Optional[EmailStr] = None
    admin_password: Optional[str] = None
    admin_full_name: Optional[str] = None


class AdminCompanyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    size: Optional[str] = None
    location: Optional[str] = None
    is_active: Optional[bool] = None
    is_verified: Optional[bool] = None


class AdminCompanyListItem(BaseModel):
    id: uuid.UUID
    name: str
    industry: Optional[str]
    size: Optional[str]
    location: Optional[str]
    is_active: bool
    is_verified: bool
    job_count: int
    user_count: int
    created_at: str

    class Config:
        from_attributes = True


class AdminCompanyDetail(AdminCompanyListItem):
    description: Optional[str]
    website: Optional[str]


# ---------------------------------------------------------------------------
# Company management (Platform Admin only)
# ---------------------------------------------------------------------------


@router.get(
    "/admin/companies",
    summary="List all companies",
)
async def list_companies(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return all companies with job and user counts."""
    result = await db.execute(
        select(
            Company,
            func.count(Job.id.distinct()).label("job_count"),
            func.count(User.id.distinct()).label("user_count"),
        )
        .outerjoin(Job, Job.company_id == Company.id)
        .outerjoin(User, User.company_id == Company.id)
        .group_by(Company.id)
        .order_by(Company.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = result.all()

    total_result = await db.execute(select(func.count()).select_from(Company))
    total = total_result.scalar_one()

    items = [
        {
            "id": str(row.Company.id),
            "name": row.Company.name,
            "description": row.Company.description,
            "website": row.Company.website,
            "industry": row.Company.industry,
            "size": row.Company.size,
            "location": row.Company.location,
            "is_active": row.Company.is_active,
            "is_verified": row.Company.is_verified,
            "job_count": row.job_count,
            "user_count": row.user_count,
            "created_at": row.Company.created_at.isoformat() if row.Company.created_at else None,
        }
        for row in rows
    ]
    return {"items": items, "total": total}


@router.post(
    "/admin/companies",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new company",
)
async def create_company(
    payload: AdminCompanyCreate,
    current_user: User = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a company. Optionally creates the first COMPANY_ADMIN user."""
    # Check name uniqueness
    existing = await db.execute(select(Company).where(Company.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A company named '{payload.name}' already exists.",
        )

    company = Company(
        id=uuid.uuid4(),
        name=payload.name,
        description=payload.description,
        website=payload.website,
        industry=payload.industry,
        size=payload.size,
        location=payload.location,
        is_verified=True,  # Platform-created companies are pre-verified
    )
    db.add(company)
    await db.flush()

    # Seed default pipeline template
    db.add(
        PipelineTemplate(
            id=uuid.uuid4(),
            company_id=company.id,
            name="Default Pipeline",
            stages=DEFAULT_PIPELINE_STAGES,
            is_default=True,
        )
    )

    admin_user = None
    if payload.admin_email and payload.admin_password:
        # Check email uniqueness
        email_check = await db.execute(select(User).where(User.email == payload.admin_email))
        if email_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{payload.admin_email}' is already registered.",
            )
        admin_user = User(
            id=uuid.uuid4(),
            email=payload.admin_email,
            password_hash=get_password_hash(payload.admin_password),
            full_name=payload.admin_full_name,
            role=UserRole.COMPANY_ADMIN,
            company_id=company.id,
            company_role=CompanyRole.ADMIN,
            email_verified=True,  # Platform-created users skip email verification
        )
        db.add(admin_user)

    await db.commit()
    await db.refresh(company)

    return {
        "id": str(company.id),
        "name": company.name,
        "is_verified": company.is_verified,
        "is_active": company.is_active,
        "admin_user_id": str(admin_user.id) if admin_user else None,
        "admin_email": payload.admin_email if admin_user else None,
    }


@router.patch(
    "/admin/companies/{company_id}",
    summary="Update company status or details",
)
async def update_company(
    company_id: uuid.UUID,
    payload: AdminCompanyUpdate,
    current_user: User = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Activate/deactivate, verify, or update basic details of any company."""
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found.")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(company, field, value)

    await db.commit()
    await db.refresh(company)
    return {
        "id": str(company.id),
        "name": company.name,
        "is_active": company.is_active,
        "is_verified": company.is_verified,
    }


# ---------------------------------------------------------------------------
# ML / fairness endpoints (existing — kept as platform_admin now)
# ---------------------------------------------------------------------------


@router.get(
    "/admin/model-metrics",
    summary="Active predictive model metrics (B9.2.3)",
)
async def get_model_metrics(
    current_user: User = Depends(get_platform_admin),
) -> dict:
    """Return AUC-ROC, training sample count, and last-retrain timestamp for the active model.

    Reads from the Redis hash written by ``retrain_predictive_model``.
    Returns 404 if no model has been trained yet.
    """
    try:
        from app.core.cache import get_redis
        r = await get_redis()
        metrics = await r.hgetall("predictive_model:metrics")
    except Exception as e:
        logger.error("get_model_metrics: Redis error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not read model metrics from cache.",
        )

    if not metrics:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No trained model found. Run retrain_predictive_model first.",
        )

    # Redis values come back as bytes or str depending on decode_responses setting
    def _decode(v):
        return v.decode() if isinstance(v, bytes) else v

    decoded = {
        (_decode(k) if isinstance(k, bytes) else k): _decode(v)
        for k, v in metrics.items()
    }

    return {
        "auc_roc": float(decoded.get("auc", 0)),
        "n_training_samples": int(decoded.get("n_training_samples", 0)),
        "n_test_samples": int(decoded.get("n_test_samples", 0)),
        "retrained_at": decoded.get("retrained_at"),
        "model_path": decoded.get("model_path"),
        "threshold": 0.65,
    }


# ---------------------------------------------------------------------------
# B10.2.3 — List fairness reports
# ---------------------------------------------------------------------------

@router.get(
    "/admin/fairness-reports",
    summary="List monthly fairness audit reports (B10.2.3)",
)
async def list_fairness_reports(
    current_user: User = Depends(get_platform_admin),
) -> dict:
    """Return a list of dates for which a monthly fairness audit report exists.

    Dates are returned in descending order (most recent first).
    """
    import json as _json
    from app.tasks.fairness_tasks import FAIRNESS_REPORT_INDEX_KEY

    try:
        from app.core.cache import get_redis
        r = await get_redis()
        # Sorted set is scored as YYYYMMDD int — fetch in reverse order
        dates = await r.zrevrange(FAIRNESS_REPORT_INDEX_KEY, 0, -1)
    except Exception as e:
        logger.error("list_fairness_reports: Redis error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not read fairness report index from cache.",
        )

    return {"reports": list(dates)}


# ---------------------------------------------------------------------------
# B10.2.4 — Fairness report detail
# ---------------------------------------------------------------------------

@router.get(
    "/admin/fairness-reports/{report_date}",
    summary="Fairness audit report detail (B10.2.4)",
)
async def get_fairness_report(
    report_date: str,
    current_user: User = Depends(get_platform_admin),
) -> dict:
    """Return the full fairness audit report for a given date (YYYY-MM-DD).

    Each job entry contains disparate_impact metrics per protected group,
    flagged status (4/5 rule), and selection rates per group value.
    """
    import json as _json
    import re
    from app.tasks.fairness_tasks import FAIRNESS_REPORT_PREFIX

    # Basic format validation to prevent cache-key injection
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="report_date must be in YYYY-MM-DD format.",
        )

    try:
        from app.core.cache import get_redis
        r = await get_redis()
        raw = await r.get(f"{FAIRNESS_REPORT_PREFIX}{report_date}")
    except Exception as e:
        logger.error("get_fairness_report: Redis error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not read fairness report from cache.",
        )

    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No fairness report found for {report_date}.",
        )

    try:
        return _json.loads(raw)
    except Exception as e:
        logger.error("get_fairness_report: JSON decode error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fairness report data is corrupt.",
        )
