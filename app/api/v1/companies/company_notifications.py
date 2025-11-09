"""
API endpoints for company notifications.

This module provides endpoints for companies to:
- Retrieve their notifications with pagination and filters
- Mark notifications as read
- Mark all notifications as read
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import uuid

from app.core.database import get_db
from app.api.deps import get_current_user, get_company_user
from app.models.user import User
from app.services.notification_service import NotificationService
from app.schemas.notification import (
    NotificationListResponse,
    NotificationResponse,
    MarkReadResponse
)

router = APIRouter()


def _enrich_company_notification(notification) -> dict:
    """
    Convert notification model to enriched response dict for companies.

    Args:
        notification: Notification model instance

    Returns:
        Dictionary with notification data and enriched applicant/job info
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

    # Enrich with applicant data if available
    if notification.user:
        data["applicant"] = {
            "id": notification.user.id,
            "full_name": notification.user.full_name,
            "email": notification.user.email,
            "headline": notification.user.headline
        }

    return data


@router.get("/{company_id}/notifications", response_model=NotificationListResponse)
async def get_company_notifications(
    company_id: uuid.UUID,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    is_read: Optional[bool] = Query(None, description="Filter by read status"),
    filter: Optional[str] = Query(None, description="Time range filter: '7d' or '30d'"),
    current_user: User = Depends(get_company_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get paginated notifications for a company.

    Query parameters:
    - page: Page number (default: 1)
    - limit: Items per page (default: 50, max: 100)
    - is_read: Filter by read status (optional)
    - filter: Time range filter - '7d' or '30d' (optional)

    Returns paginated list with unread count.
    """
    # Verify user belongs to this company
    if current_user.company_id != company_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. You can only access your company's notifications"
        )

    service = NotificationService()
    result = await service.get_company_notifications(
        db,
        company_id,
        page=page,
        limit=limit,
        is_read=is_read,
        time_filter=filter
    )

    # Enrich notifications
    enriched_items = [_enrich_company_notification(n) for n in result["items"]]

    return {
        "items": enriched_items,
        "total": result["total"],
        "page": result["page"],
        "pages": result["pages"],
        "unread_count": result["unread_count"]
    }


@router.patch("/{company_id}/notifications/{notification_id}/read", response_model=NotificationResponse)
async def mark_company_notification_read(
    company_id: uuid.UUID,
    notification_id: uuid.UUID,
    current_user: User = Depends(get_company_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Mark a specific company notification as read.

    Returns the updated notification.
    """
    # Verify user belongs to this company
    if current_user.company_id != company_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. You can only access your company's notifications"
        )

    service = NotificationService()
    notification = await service.mark_company_notification_read(
        db,
        notification_id,
        company_id
    )

    await db.commit()

    return _enrich_company_notification(notification)


@router.patch("/{company_id}/notifications/read-all", response_model=MarkReadResponse)
async def mark_all_company_notifications_read(
    company_id: uuid.UUID,
    current_user: User = Depends(get_company_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Mark all notifications as read for a company.

    Returns the count of notifications updated.
    """
    # Verify user belongs to this company
    if current_user.company_id != company_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. You can only access your company's notifications"
        )

    service = NotificationService()
    result = await service.mark_all_read_for_company(db, company_id)

    await db.commit()

    return {
        "updated_count": result["updated_count"],
        "success": True
    }
