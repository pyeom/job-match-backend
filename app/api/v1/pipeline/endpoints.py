import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from app.core.database import get_db
from app.api.deps import (
    get_company_user_with_verification,
    require_company_access,
    require_company_role,
)
from app.models.user import User
from app.models.pipeline import PipelineTemplate, ApplicationStageHistory
from app.models.application import Application
from app.models.job import Job

router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class StageItem(BaseModel):
    order: int
    name: str
    color: Optional[str] = None


class PipelineTemplateCreate(BaseModel):
    name: str
    stages: List[StageItem]
    is_default: bool = False


class PipelineTemplateUpdate(BaseModel):
    name: Optional[str] = None
    stages: Optional[List[StageItem]] = None
    is_default: Optional[bool] = None


class PipelineTemplateResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    stages: list
    is_default: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class StageMoveRequest(BaseModel):
    stage_order: int
    stage_name: str
    notes: Optional[str] = None


class BulkActionRequest(BaseModel):
    action: str  # "move" | "reject" | "hold"
    ids: List[uuid.UUID]
    stage_order: Optional[int] = None
    stage_name: Optional[str] = None
    notes: Optional[str] = None


class CandidateResponse(BaseModel):
    application_id: uuid.UUID
    user_id: uuid.UUID
    job_id: uuid.UUID
    stage: str
    status: str
    score: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── Pipeline template endpoints ───────────────────────────────────────────────

@router.get("/companies/{company_id}/pipeline-templates", response_model=List[PipelineTemplateResponse])
async def list_pipeline_templates(
    company_id: uuid.UUID,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db),
):
    require_company_access(current_user, company_id)
    result = await db.execute(
        select(PipelineTemplate).where(PipelineTemplate.company_id == company_id)
    )
    return result.scalars().all()


@router.post(
    "/companies/{company_id}/pipeline-templates",
    response_model=PipelineTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_pipeline_template(
    company_id: uuid.UUID,
    body: PipelineTemplateCreate,
    current_user: User = Depends(require_company_role(["admin"])),
    db: AsyncSession = Depends(get_db),
):
    require_company_access(current_user, company_id)
    template = PipelineTemplate(
        id=uuid.uuid4(),
        company_id=company_id,
        name=body.name,
        stages=[s.model_dump() for s in body.stages],
        is_default=body.is_default,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


@router.put("/pipeline-templates/{template_id}", response_model=PipelineTemplateResponse)
async def update_pipeline_template(
    template_id: uuid.UUID,
    body: PipelineTemplateUpdate,
    current_user: User = Depends(require_company_role(["admin", "recruiter"])),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PipelineTemplate).where(PipelineTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline template not found")
    require_company_access(current_user, template.company_id)
    if body.name is not None:
        template.name = body.name
    if body.stages is not None:
        template.stages = [s.model_dump() for s in body.stages]
    if body.is_default is not None:
        template.is_default = body.is_default
    template.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(template)
    return template


@router.delete("/pipeline-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pipeline_template(
    template_id: uuid.UUID,
    current_user: User = Depends(require_company_role(["admin"])),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PipelineTemplate).where(PipelineTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline template not found")
    require_company_access(current_user, template.company_id)
    await db.delete(template)
    await db.commit()


# ── Candidate / application endpoints ────────────────────────────────────────

@router.get("/jobs/{job_id}/candidates", response_model=List[CandidateResponse])
async def list_candidates(
    job_id: uuid.UUID,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db),
):
    job_result = await db.execute(select(Job).where(Job.id == job_id))
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    require_company_access(current_user, job.company_id)

    result = await db.execute(
        select(Application)
        .where(Application.job_id == job_id)
        .order_by(desc(Application.score), desc(Application.created_at))
    )
    applications = result.scalars().all()

    return [
        CandidateResponse(
            application_id=app.id,
            user_id=app.user_id,
            job_id=app.job_id,
            stage=app.stage,
            status=app.status,
            score=app.score,
            created_at=app.created_at,
        )
        for app in applications
    ]


@router.put("/applications/{application_id}/stage")
async def move_application_stage(
    application_id: uuid.UUID,
    body: StageMoveRequest,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Application).where(Application.id == application_id)
    )
    application = result.scalar_one_or_none()
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    # Verify the job belongs to the current user's company
    job_result = await db.execute(select(Job).where(Job.id == application.job_id))
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    require_company_access(current_user, job.company_id)

    # Close the previous open history entry
    open_entry_result = await db.execute(
        select(ApplicationStageHistory).where(
            ApplicationStageHistory.application_id == application_id,
            ApplicationStageHistory.exited_at == None,  # noqa: E711
        )
    )
    open_entry = open_entry_result.scalar_one_or_none()
    if open_entry:
        open_entry.exited_at = datetime.now(timezone.utc)

    # Update application stage
    application.stage = body.stage_name
    application.stage_updated_at = datetime.now(timezone.utc)

    # Insert history record
    history = ApplicationStageHistory(
        id=uuid.uuid4(),
        application_id=application_id,
        stage_order=body.stage_order,
        stage_name=body.stage_name,
        notes=body.notes,
        moved_by=current_user.id,
    )
    db.add(history)
    await db.commit()
    await db.refresh(application)

    return {
        "application_id": str(application_id),
        "stage": application.stage,
        "stage_updated_at": application.stage_updated_at.isoformat() if application.stage_updated_at else None,
    }


@router.post("/applications/bulk-action")
async def bulk_action(
    body: BulkActionRequest,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db),
):
    if body.action not in ("move", "reject", "hold"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="action must be 'move', 'reject', or 'hold'")

    if body.action == "move" and (body.stage_order is None or body.stage_name is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="stage_order and stage_name are required for 'move' action",
        )

    updated_ids: list[str] = []
    for app_id in body.ids:
        result = await db.execute(select(Application).where(Application.id == app_id))
        application = result.scalar_one_or_none()
        if not application:
            continue

        job_result = await db.execute(select(Job).where(Job.id == application.job_id))
        job = job_result.scalar_one_or_none()
        if not job or job.company_id != current_user.company_id:
            continue

        if body.action == "reject":
            application.status = "REJECTED"
        elif body.action == "hold":
            application.status = "HOLD"
        elif body.action == "move":
            # Close open history entry
            open_entry_result = await db.execute(
                select(ApplicationStageHistory).where(
                    ApplicationStageHistory.application_id == app_id,
                    ApplicationStageHistory.exited_at == None,  # noqa: E711
                )
            )
            open_entry = open_entry_result.scalar_one_or_none()
            if open_entry:
                open_entry.exited_at = datetime.now(timezone.utc)

            application.stage = body.stage_name
            application.stage_updated_at = datetime.now(timezone.utc)

            history = ApplicationStageHistory(
                id=uuid.uuid4(),
                application_id=app_id,
                stage_order=body.stage_order,
                stage_name=body.stage_name,
                notes=body.notes,
                moved_by=current_user.id,
            )
            db.add(history)

        updated_ids.append(str(app_id))

    await db.commit()
    return {"updated": updated_ids, "count": len(updated_ids)}
