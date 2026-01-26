from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid
from app.schemas.job import JobWithCompany


class SwipeCreate(BaseModel):
    job_id: uuid.UUID
    direction: str  # LEFT or RIGHT
    score: Optional[int] = None  # Match score from discover feed (0-100)


class Swipe(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    job_id: uuid.UUID
    direction: str
    created_at: datetime
    is_undone: bool = False
    undone_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SwipeWithUndoWindow(BaseModel):
    """Swipe response including undo window information"""
    id: uuid.UUID
    user_id: uuid.UUID
    job_id: uuid.UUID
    direction: str
    created_at: datetime
    is_undone: bool
    can_undo: bool
    remaining_undo_time: Optional[int] = None  # Seconds remaining in undo window

    class Config:
        from_attributes = True


class UndoResponse(BaseModel):
    """Response for successful undo operation"""
    message: str
    swipe_id: uuid.UUID
    job_id: uuid.UUID
    undone_at: datetime
    remaining_daily_undos: int


class UndoLimitInfo(BaseModel):
    """Information about user's undo limits and usage"""
    daily_limit: int
    used_today: int
    remaining_today: int
    is_premium: bool


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