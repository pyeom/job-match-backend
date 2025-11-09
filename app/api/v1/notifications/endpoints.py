"""
API endpoints for user notifications.

This module provides endpoints for job seekers to:
- Retrieve their notifications with pagination and filters
- Mark notifications as read
- Mark all notifications as read
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import uuid

from app.core.database import get_db
from app.api.deps import get_current_user, get_job_seeker
from app.models.user import User
from app.services.notification_service import NotificationService
from app.schemas.notification import (
    NotificationListResponse,
    NotificationResponse,
    MarkReadResponse,
    JobPreview,
    ApplicantPreview
)

router = APIRouter()


def _enrich_notification(notification) -> dict:
    """
    Convert notification model to enriched response dict.

    Args:
        notification: Notification model instance

    Returns:
        Dictionary with notification data and enriched job info
    """
    data = {
        "id": notification.id,
        "user_id": notification.user_id,
        "company_id": notification.company_id,
        "title": notification.title,
        "message": notification.message,
        "type": notification.type.value,
        "is_read": notification.is_read,
        "job_id": notification.job_id,
        "application_id": notification.application_id,
        "created_at": notification.created_at,
        "read_at": notification.read_at,
        "job": None,
        "applicant": None
    }

    # Enrich with job data if available
    if notification.job:
        company_name = notification.job.company.name if notification.job.company else "Unknown Company"
        data["job"] = {
            "id": notification.job.id,
            "title": notification.job.title,
            "company": company_name
        }

    # Enrich with applicant data if available (for company notifications)
    if notification.user:
        data["applicant"] = {
            "id": notification.user.id,
            "full_name": notification.user.full_name,
            "email": notification.user.email,
            "headline": notification.user.headline
        }

    return data


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    is_read: Optional[bool] = Query(None, description="Filter by read status"),
    type: Optional[str] = Query(None, description="Filter by notification type"),
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Get paginated notifications for the current user.

    Query parameters:
    - page: Page number (default: 1)
    - limit: Items per page (default: 50, max: 100)
    - is_read: Filter by read status (optional)
    - type: Filter by notification type (optional)

    Returns paginated list with unread count.
    """
    service = NotificationService()
    result = await service.get_user_notifications(
        db,
        current_user.id,
        page=page,
        limit=limit,
        is_read=is_read,
        notification_type=type
    )

    # Enrich notifications
    enriched_items = [_enrich_notification(n) for n in result["items"]]

    return {
        "items": enriched_items,
        "total": result["total"],
        "page": result["page"],
        "pages": result["pages"],
        "unread_count": result["unread_count"]
    }


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Mark a specific notification as read.

    Returns the updated notification.
    """
    service = NotificationService()
    notification = await service.mark_notification_read(
        db,
        notification_id,
        current_user.id
    )

    await db.commit()

    return _enrich_notification(notification)


@router.patch("/read-all", response_model=MarkReadResponse)
async def mark_all_notifications_read(
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Mark all notifications as read for the current user.

    Returns the count of notifications updated.
    """
    service = NotificationService()
    result = await service.mark_all_read_for_user(db, current_user.id)

    await db.commit()

    return {
        "updated_count": result["updated_count"],
        "success": True
    }
