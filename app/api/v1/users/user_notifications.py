"""
API endpoints for user notifications (per-user resource).

This module provides endpoints under /users/{user_id}/notifications for job seekers to:
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
)
from app.api.v1.notifications.endpoints import _enrich_notification

router = APIRouter()


def _verify_user_access(current_user: User, user_id: uuid.UUID):
    """Verify the authenticated user matches the requested user_id."""
    if current_user.id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. You can only access your own notifications"
        )


@router.get("/{user_id}/notifications", response_model=NotificationListResponse)
async def get_user_notifications(
    user_id: uuid.UUID,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    is_read: Optional[bool] = Query(None, description="Filter by read status"),
    type: Optional[str] = Query(None, description="Filter by notification type"),
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Get paginated notifications for a specific user.

    Query parameters:
    - page: Page number (default: 1)
    - limit: Items per page (default: 50, max: 100)
    - is_read: Filter by read status (optional)
    - type: Filter by notification type (optional)

    Returns paginated list with unread count.
    """
    _verify_user_access(current_user, user_id)

    service = NotificationService()
    result = await service.get_user_notifications(
        db,
        user_id,
        page=page,
        limit=limit,
        is_read=is_read,
        notification_type=type
    )

    enriched_items = [_enrich_notification(n) for n in result["items"]]

    return {
        "items": enriched_items,
        "total": result["total"],
        "page": result["page"],
        "pages": result["pages"],
        "unread_count": result["unread_count"]
    }


@router.patch("/{user_id}/notifications/{notification_id}/read", response_model=NotificationResponse)
async def mark_user_notification_read(
    user_id: uuid.UUID,
    notification_id: uuid.UUID,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Mark a specific notification as read for a user.

    Returns the updated notification.
    """
    _verify_user_access(current_user, user_id)

    service = NotificationService()
    notification = await service.mark_notification_read(
        db,
        notification_id,
        user_id
    )

    await db.commit()

    return _enrich_notification(notification)


@router.patch("/{user_id}/notifications/read-all", response_model=MarkReadResponse)
async def mark_all_user_notifications_read(
    user_id: uuid.UUID,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Mark all notifications as read for a user.

    Returns the count of notifications updated.
    """
    _verify_user_access(current_user, user_id)

    service = NotificationService()
    result = await service.mark_all_read_for_user(db, user_id)

    await db.commit()

    return {
        "updated_count": result["updated_count"],
        "success": True
    }
