import base64
import uuid
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, desc, or_, nullslast
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.api.deps import (
    get_company_user_with_verification,
    require_company_access
)
from app.models.user import User
from app.models.job import Job
from app.models.application import Application
from app.models.company import Company
from app.schemas.company import PaginatedResponse, CursorPaginatedResponse
from app.schemas.application import (
    ApplicationUpdate,
    ApplicationWithDetails,
    ApplicationWithUserResponse,
    UserBasicInfo,
    JobDetails,
    CompanyDetails
)
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stage transition helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Cursor helpers for application pagination
#
# Sort order: score DESC NULLS LAST, created_at DESC, id DESC
# Cursor encodes: "{score_or_None}|{created_at.isoformat()}|{id}"
# ---------------------------------------------------------------------------

def _encode_application_cursor(
    score: Optional[int],
    created_at: datetime,
    app_id: uuid.UUID,
) -> str:
    """Encode an application cursor as base64."""
    raw = f"{score}|{created_at.isoformat()}|{app_id}"
    return base64.b64encode(raw.encode()).decode()


def _decode_application_cursor(
    cursor: str,
) -> tuple[Optional[float], datetime, uuid.UUID]:
    """Decode an application cursor.  Raises HTTP 400 on invalid input."""
    try:
        raw = base64.b64decode(cursor.encode()).decode()
        score_str, created_at_str, id_str = raw.split("|", 2)
        c_score: Optional[float] = None if score_str == "None" else float(score_str)
        c_created_at = datetime.fromisoformat(created_at_str)
        c_id = uuid.UUID(id_str)
        return c_score, c_created_at, c_id
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid pagination cursor")


def _apply_application_cursor_filter(query, c_score: Optional[float], c_created_at: datetime, c_id: uuid.UUID):
    """Append a WHERE clause that implements the keyset after the given cursor position.

    Sort order is: score DESC NULLS LAST, created_at DESC, id DESC

    Rows that come *after* the cursor satisfy at least one of:
      1. score <  c_score                                          (lower score)
      2. score == c_score AND created_at < c_created_at            (same score, older)
      3. score == c_score AND created_at == c_created_at AND id < c_id   (tiebreak)
      4. score IS NULL  (NULLs sort last — always after any non-NULL score)
    """
    if c_score is not None:
        return query.where(
            or_(
                # Rows with a strictly lower score
                Application.score < c_score,
                # Same score, but older created_at
                and_(
                    Application.score == c_score,
                    Application.created_at < c_created_at,
                ),
                # Same score, same created_at, smaller id (tiebreak)
                and_(
                    Application.score == c_score,
                    Application.created_at == c_created_at,
                    Application.id < c_id,
                ),
                # NULL scores come after all non-NULL scores
                Application.score.is_(None),
            )
        )
    else:
        # The cursor itself has a NULL score — only rows with NULL score and
        # an earlier position remain.
        return query.where(
            and_(
                Application.score.is_(None),
                or_(
                    Application.created_at < c_created_at,
                    and_(
                        Application.created_at == c_created_at,
                        Application.id < c_id,
                    ),
                ),
            )
        )


router = APIRouter()


@router.get("/{company_id}/jobs/{job_id}/applications", response_model=CursorPaginatedResponse[ApplicationWithUserResponse])
async def get_job_applications(
    company_id: uuid.UUID,
    job_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque cursor from the previous page"),
    stage_filter: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """Get all applications for a specific job with cursor-based pagination.

    Results are ordered ``score DESC NULLS LAST, created_at DESC, id DESC``.
    Provide ``cursor`` from the previous ``next_cursor`` to fetch the next page.
    """
    require_company_access(current_user, company_id)

    # Verify job belongs to company
    job_result = await db.execute(
        select(Job).where(Job.id == job_id, Job.company_id == company_id)
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Parse cursor
    c_score: Optional[float] = None
    c_created_at: Optional[datetime] = None
    c_id: Optional[uuid.UUID] = None
    if cursor:
        c_score, c_created_at, c_id = _decode_application_cursor(cursor)

    # Build query — join User and Company so we can populate the response
    query = (
        select(Application, User, Job, Company)
        .select_from(Application)
        .join(Job, Application.job_id == Job.id)
        .join(User, Application.user_id == User.id)
        .join(Company, Job.company_id == Company.id)
        .where(Application.job_id == job_id)
    )

    if stage_filter:
        query = query.where(Application.stage == stage_filter)

    if status_filter:
        query = query.where(Application.status == status_filter)

    # Apply keyset cursor filter
    if c_created_at is not None and c_id is not None:
        query = _apply_application_cursor_filter(query, c_score, c_created_at, c_id)

    # DB-level ordering: score DESC NULLS LAST, created_at DESC, id DESC
    query = query.order_by(
        nullslast(Application.score.desc()),
        Application.created_at.desc(),
        Application.id.desc(),
    ).limit(limit + 1)

    result = await db.execute(query)
    rows = list(result.all())

    has_next = len(rows) > limit
    if has_next:
        rows = rows[:limit]

    applications: list[ApplicationWithUserResponse] = []
    for app, user, job_info, company in rows:
        applications.append(
            ApplicationWithUserResponse(
                id=app.id,
                job_id=app.job_id,
                job_title=job_info.title,
                user_id=app.user_id,
                user_email=user.email,
                user_full_name=user.full_name,
                user_headline=user.headline,
                user_skills=user.skills,
                user_seniority=user.seniority,
                stage=app.stage,
                status=app.status,
                stage_updated_at=app.stage_updated_at,
                rejection_reason=app.rejection_reason,
                created_at=app.created_at,
                updated_at=app.updated_at or app.created_at,
                score=app.score,
            )
        )

    next_cursor: Optional[str] = None
    if has_next and applications:
        last = applications[-1]
        next_cursor = _encode_application_cursor(last.score, last.created_at, last.id)

    return CursorPaginatedResponse(
        items=applications,
        next_cursor=next_cursor,
        has_next=has_next,
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

    # Store old stage for notification BEFORE committing
    old_stage = (
        application.stage_history[-1]["from_stage"]
        if stage_changed and application.stage_history
        else application.stage
    )

    # Update stage_updated_at if stage changed
    if stage_changed:
        application.stage_updated_at = func.now()

    await db.commit()
    await db.refresh(application)

    # Create notification for user about status/stage change
    if stage_changed or update_data.status is not None:
        try:
            from app.services.notification_service import NotificationService
            from app.models.notification import NotificationType

            notification_service = NotificationService()

            logger.info(
                "Stage or status changed for application %s. Stage changed: %s, New status: %s",
                application.id, stage_changed, update_data.status,
            )

            # Determine notification type based on new status/stage
            if application.status == "REJECTED":
                notification_type = NotificationType.APPLICATION_REJECTED
            elif application.status == "HIRED":
                notification_type = NotificationType.APPLICATION_ACCEPTED
            else:
                notification_type = NotificationType.APPLICATION_UPDATE

            logger.debug("Notification type determined: %s", notification_type)

            # Create notification
            logger.info(
                "Attempting to create status notification for application %s: %s -> %s",
                application.id, old_stage, application.stage,
            )

            notification = await notification_service.create_application_status_notification(
                db=db,
                application_id=application.id,
                old_stage=old_stage,
                new_stage=application.stage
            )

            if notification:
                await db.commit()
                logger.info(
                    "Successfully created status notification %s for application %s",
                    notification.id, application.id,
                )
            else:
                logger.warning(
                    "Notification service returned None for application %s", application.id
                )

        except Exception as e:
            logger.error(
                "Failed to create status notification for application %s: %s",
                application.id, e, exc_info=True,
            )
            # Don't fail the request if notification fails
            await db.rollback()

    return ApplicationWithUserResponse(
        id=application.id,
        job_id=application.job_id,
        job_title=job.title,
        user_id=application.user_id,
        user_email=user.email,
        user_full_name=user.full_name,
        user_headline=user.headline,
        user_skills=user.skills,
        user_seniority=user.seniority,
        stage=application.stage,
        status=application.status,
        stage_updated_at=application.stage_updated_at,
        rejection_reason=application.rejection_reason,
        created_at=application.created_at,
        updated_at=application.updated_at or application.created_at,
        score=application.score,
    )


@router.get("/applications", response_model=CursorPaginatedResponse[ApplicationWithUserResponse])
async def get_all_company_applications(
    limit: int = Query(50, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque cursor from the previous page"),
    stage_filter: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    seniority_filter: Optional[str] = Query(None),
    location_filter: Optional[str] = Query(None),
    created_after: Optional[datetime] = Query(None),
    created_before: Optional[datetime] = Query(None),
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """Get all applications for the company with cursor-based pagination.

    Results are ordered ``score DESC NULLS LAST, created_at DESC, id DESC``.
    Provide ``cursor`` from the previous ``next_cursor`` to fetch the next page.
    """
    company_id = current_user.company_id

    # Parse cursor
    c_score: Optional[float] = None
    c_created_at: Optional[datetime] = None
    c_id: Optional[uuid.UUID] = None
    if cursor:
        c_score, c_created_at, c_id = _decode_application_cursor(cursor)

    # Build base query with joins
    query = (
        select(Application, User, Job)
        .select_from(Application)
        .join(Job, Application.job_id == Job.id)
        .join(User, Application.user_id == User.id)
        .where(Job.company_id == company_id)
    )

    # Apply filters
    if stage_filter:
        query = query.where(Application.stage == stage_filter)

    if status_filter:
        query = query.where(Application.status == status_filter)

    if seniority_filter:
        query = query.where(User.seniority == seniority_filter)

    if location_filter:
        query = query.where(Job.location == location_filter)

    if created_after:
        query = query.where(Application.created_at >= created_after)

    if created_before:
        query = query.where(Application.created_at <= created_before)

    # Apply keyset cursor filter
    if c_created_at is not None and c_id is not None:
        query = _apply_application_cursor_filter(query, c_score, c_created_at, c_id)

    # DB-level ordering: score DESC NULLS LAST, created_at DESC, id DESC
    query = query.order_by(
        nullslast(Application.score.desc()),
        Application.created_at.desc(),
        Application.id.desc(),
    ).limit(limit + 1)

    result = await db.execute(query)
    rows = list(result.all())

    has_next = len(rows) > limit
    if has_next:
        rows = rows[:limit]

    applications: list[ApplicationWithUserResponse] = []
    for app, user, job in rows:
        applications.append(
            ApplicationWithUserResponse(
                id=app.id,
                job_id=app.job_id,
                job_title=job.title,
                user_id=app.user_id,
                user_email=user.email,
                user_full_name=user.full_name,
                user_headline=user.headline,
                user_skills=user.skills,
                user_seniority=user.seniority,
                stage=app.stage,
                status=app.status,
                stage_updated_at=app.stage_updated_at,
                rejection_reason=app.rejection_reason,
                created_at=app.created_at,
                updated_at=app.updated_at or app.created_at,
                score=app.score,
            )
        )

    next_cursor: Optional[str] = None
    if has_next and applications:
        last = applications[-1]
        next_cursor = _encode_application_cursor(last.score, last.created_at, last.id)

    return CursorPaginatedResponse(
        items=applications,
        next_cursor=next_cursor,
        has_next=has_next,
    )
