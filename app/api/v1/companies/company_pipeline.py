"""
Company Pipeline Management

Provides simplified endpoints for managing a company's default pipeline stages.
These endpoints complement (and do not replace) the generic pipeline-template
CRUD at /api/v1/pipeline/.
"""

import uuid
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.api.deps import (
    get_company_user_with_verification,
    require_company_access,
    require_company_role,
)
from app.models.user import User
from app.models.pipeline import PipelineTemplate, DEFAULT_PIPELINE_STAGES

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas (inline, specific to this simplified pipeline API)
# ---------------------------------------------------------------------------

class PipelineStage(BaseModel):
    key: str
    order: int
    label: str
    description: str = ""
    color: str = "#6366f1"

    @field_validator("key")
    @classmethod
    def key_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Stage key cannot be empty")
        return v.strip().upper()


class PipelineUpdate(BaseModel):
    stages: List[PipelineStage]

    @field_validator("stages")
    @classmethod
    def validate_stages(cls, stages: List[PipelineStage]) -> List[PipelineStage]:
        if len(stages) < 2:
            raise ValueError("Pipeline must have at least 2 stages")
        if len(stages) > 15:
            raise ValueError("Pipeline cannot have more than 15 stages")

        keys = [s.key for s in stages]
        if len(keys) != len(set(keys)):
            raise ValueError("Stage keys must be unique within the pipeline")

        # Validate sequential ordering starting at 1
        sorted_orders = sorted(s.order for s in stages)
        expected = list(range(1, len(stages) + 1))
        if sorted_orders != expected:
            raise ValueError("Stage order must be sequential starting at 1")

        return stages


class CompanyPipelineResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    stages: List[PipelineStage]
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_stage(s: dict) -> dict:
    """Normalize old {order,name,color} format to new {key,order,label,description,color} format."""
    if "key" in s:
        return s
    name = s.get("name", "unknown")
    return {
        "key": name.lower().replace(" ", "_"),
        "order": s.get("order", 0),
        "label": name,
        "description": "",
        "color": s.get("color", "#6b7280"),
    }


def _stages_to_response(template: PipelineTemplate) -> CompanyPipelineResponse:
    """Convert a PipelineTemplate ORM object to CompanyPipelineResponse."""
    raw_stages = sorted(template.stages or [], key=lambda s: s.get("order", 0))
    stages = [PipelineStage(**_normalize_stage(s)) for s in raw_stages]
    return CompanyPipelineResponse(
        id=template.id,
        company_id=template.company_id,
        stages=stages,
        updated_at=template.updated_at,
    )


async def _get_or_create_default_pipeline(
    company_id: uuid.UUID,
    db: AsyncSession,
) -> PipelineTemplate:
    """Fetch the company's default PipelineTemplate, creating one if absent."""
    result = await db.execute(
        select(PipelineTemplate).where(
            PipelineTemplate.company_id == company_id,
            PipelineTemplate.is_default == True,  # noqa: E712
        )
    )
    template = result.scalar_one_or_none()

    if template is None:
        logger.info("Auto-creating default pipeline for company %s", company_id)
        template = PipelineTemplate(
            id=uuid.uuid4(),
            company_id=company_id,
            name="Default",
            stages=DEFAULT_PIPELINE_STAGES,
            is_default=True,
        )
        db.add(template)
        await db.commit()
        await db.refresh(template)

    return template


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/{company_id}/pipeline", response_model=CompanyPipelineResponse)
async def get_company_pipeline(
    company_id: uuid.UUID,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db),
) -> CompanyPipelineResponse:
    """Return the company's default pipeline, auto-creating it from defaults if it doesn't exist yet."""
    require_company_access(current_user, company_id)
    template = await _get_or_create_default_pipeline(company_id, db)
    return _stages_to_response(template)


@router.put("/{company_id}/pipeline", response_model=CompanyPipelineResponse)
async def update_company_pipeline(
    company_id: uuid.UUID,
    body: PipelineUpdate,
    current_user: User = Depends(require_company_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> CompanyPipelineResponse:
    """Full replace of the company's default pipeline stages.

    Stages must be unique by key and sequentially ordered starting at 1.
    Min 2 stages, max 15.
    """
    require_company_access(current_user, company_id)
    template = await _get_or_create_default_pipeline(company_id, db)

    template.stages = [s.model_dump() for s in body.stages]
    template.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(template)

    logger.info(
        "Pipeline updated for company %s by user %s (%d stages)",
        company_id, current_user.id, len(body.stages),
    )
    return _stages_to_response(template)


@router.post(
    "/{company_id}/pipeline/reset",
    response_model=CompanyPipelineResponse,
    status_code=status.HTTP_200_OK,
)
async def reset_company_pipeline(
    company_id: uuid.UUID,
    current_user: User = Depends(require_company_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> CompanyPipelineResponse:
    """Reset the company pipeline to the system defaults."""
    require_company_access(current_user, company_id)
    template = await _get_or_create_default_pipeline(company_id, db)

    template.stages = DEFAULT_PIPELINE_STAGES
    template.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(template)

    logger.info(
        "Pipeline reset to defaults for company %s by user %s",
        company_id, current_user.id,
    )
    return _stages_to_response(template)
