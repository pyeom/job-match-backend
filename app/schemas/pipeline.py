from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Literal


class PipelineStage(BaseModel):
    order: int
    name: str
    color: str = "#6366f1"


class PipelineTemplateCreate(BaseModel):
    name: str
    stages: list[PipelineStage]
    is_default: bool = False


class PipelineTemplateUpdate(BaseModel):
    name: str | None = None
    stages: list[PipelineStage] | None = None
    is_default: bool | None = None


class PipelineTemplateResponse(BaseModel):
    id: UUID
    company_id: UUID
    name: str
    stages: list[PipelineStage]
    is_default: bool
    created_at: datetime

    class Config:
        from_attributes = True


class MoveStageRequest(BaseModel):
    stage_order: int
    stage_name: str
    notes: str | None = None


class BulkActionRequest(BaseModel):
    action: Literal["move", "reject", "hold"]
    application_ids: list[UUID]
    stage_order: int | None = None   # required when action = "move"
    stage_name: str | None = None
