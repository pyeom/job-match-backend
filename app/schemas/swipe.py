from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid
from app.schemas.job import JobWithCompany


class SwipeCreate(BaseModel):
    job_id: uuid.UUID
    direction: str  # LEFT or RIGHT


class Swipe(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    job_id: uuid.UUID
    direction: str
    created_at: datetime

    class Config:
        from_attributes = True


class RejectedJobItem(BaseModel):
    """Single rejected job item with full job and company details"""
    swipe_id: uuid.UUID
    job_id: uuid.UUID
    rejected_at: datetime
    job: Optional[JobWithCompany] = None  # Nullable in case job is deleted

    class Config:
        from_attributes = True


class RejectedJobsResponse(BaseModel):
    """Response model for rejected jobs endpoint with cursor-based pagination"""
    items: List[RejectedJobItem]
    total: int
    has_more: bool
    next_cursor: Optional[str] = None