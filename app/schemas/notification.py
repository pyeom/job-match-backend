from pydantic import BaseModel
from typing import Optional, List, Literal
from datetime import datetime
import uuid


# Type definitions
NotificationType = Literal[
    'APPLICATION_UPDATE',
    'NEW_APPLICATION',
    'JOB_MATCH',
    'MESSAGE',
    'SYSTEM',
    'PROMOTION'
]


class NotificationBase(BaseModel):
    """Base notification schema"""
    title: str
    message: str
    type: NotificationType
    job_id: Optional[uuid.UUID] = None
    application_id: Optional[uuid.UUID] = None


class NotificationCreate(NotificationBase):
    """Schema for creating a notification"""
    user_id: Optional[uuid.UUID] = None
    company_id: Optional[uuid.UUID] = None


class JobPreview(BaseModel):
    """Minimal job information for notifications"""
    id: uuid.UUID
    title: str
    company: str

    class Config:
        from_attributes = True


class ApplicantPreview(BaseModel):
    """Minimal applicant information for company notifications"""
    id: uuid.UUID
    full_name: Optional[str] = None
    email: str
    headline: Optional[str] = None

    class Config:
        from_attributes = True


class NotificationResponse(BaseModel):
    """Response schema for a single notification"""
    id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    company_id: Optional[uuid.UUID] = None
    title: str
    message: str
    type: NotificationType
    is_read: bool
    job_id: Optional[uuid.UUID] = None
    application_id: Optional[uuid.UUID] = None
    created_at: datetime
    read_at: Optional[datetime] = None

    # Enriched data
    job: Optional[JobPreview] = None
    applicant: Optional[ApplicantPreview] = None

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    """Paginated list of notifications"""
    items: List[NotificationResponse]
    total: int
    page: int
    pages: int
    unread_count: int


class MarkReadResponse(BaseModel):
    """Response when marking notification(s) as read"""
    updated_count: int
    success: bool = True
