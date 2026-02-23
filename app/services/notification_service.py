"""
Notification service for business logic related to notifications.

This module handles notification management including creation, retrieval,
marking as read, and generating notification messages for different events.
"""

from __future__ import annotations
from typing import Optional
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog
import math
from datetime import datetime

from app.models.notification import NotificationType
from app.models.application import Application
from app.models.job import Job
from app.models.user import User
from app.repositories.notification_repository import NotificationRepository
from app.repositories.application_repository import ApplicationRepository
from app.repositories.job_repository import JobRepository
from app.core.websocket_manager import connection_manager
from app.services.push_notification_service import PushNotificationService

logger = structlog.get_logger(__name__)


class NotificationService:
    """
    Service for managing notifications.

    This service coordinates notification operations including:
    - Creating notifications for application events
    - Retrieving user and company notifications
    - Marking notifications as read
    - Generating notification messages
    """

    def __init__(
        self,
        notification_repo: Optional[NotificationRepository] = None,
        application_repo: Optional[ApplicationRepository] = None,
        job_repo: Optional[JobRepository] = None,
        push_service: Optional[PushNotificationService] = None
    ):
        """
        Initialize service with repositories.

        Args:
            notification_repo: NotificationRepository instance
            application_repo: ApplicationRepository instance
            job_repo: JobRepository instance
            push_service: PushNotificationService instance
        """
        self.notification_repo = notification_repo or NotificationRepository()
        self.application_repo = application_repo or ApplicationRepository()
        self.job_repo = job_repo or JobRepository()
        self.push_service = push_service or PushNotificationService()

    async def get_user_notifications(
        self,
        db: AsyncSession,
        user_id: UUID,
        page: int = 1,
        limit: int = 50,
        is_read: Optional[bool] = None,
        notification_type: Optional[str] = None
    ) -> dict:
        """
        Get paginated notifications for a user.

        Args:
            db: Active database session
            user_id: UUID of the user
            page: Page number (1-indexed)
            limit: Items per page
            is_read: Optional filter by read status
            notification_type: Optional filter by notification type

        Returns:
            Dictionary with items, total, page, pages, unread_count

        Example:
            result = await service.get_user_notifications(
                db, user_id, page=1, limit=20, is_read=False
            )
        """
        try:
            skip = (page - 1) * limit

            # Convert string type to enum if provided
            type_filter = None
            if notification_type:
                try:
                    type_filter = NotificationType(notification_type)
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid notification type: {notification_type}"
                    )

            # Get notifications
            notifications, total = await self.notification_repo.get_user_notifications(
                db, user_id, skip=skip, limit=limit, is_read=is_read, notification_type=type_filter
            )

            # Get unread count
            unread_count = await self.notification_repo.get_unread_count_for_user(db, user_id)

            pages = math.ceil(total / limit) if limit > 0 else 0

            return {
                "items": notifications,
                "total": total,
                "page": page,
                "pages": pages,
                "unread_count": unread_count
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error("get_notifications_failed", user_id=str(user_id), error=str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve notifications"
            )

    async def get_company_notifications(
        self,
        db: AsyncSession,
        company_id: UUID,
        page: int = 1,
        limit: int = 50,
        is_read: Optional[bool] = None,
        time_filter: Optional[str] = None
    ) -> dict:
        """
        Get paginated notifications for a company.

        Args:
            db: Active database session
            company_id: UUID of the company
            page: Page number (1-indexed)
            limit: Items per page
            is_read: Optional filter by read status
            time_filter: Optional time range filter ('7d' or '30d')

        Returns:
            Dictionary with items, total, page, pages, unread_count

        Example:
            result = await service.get_company_notifications(
                db, company_id, page=1, limit=50, time_filter='7d'
            )
        """
        try:
            if time_filter and time_filter not in ['7d', '30d']:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid time filter. Must be '7d' or '30d'"
                )

            skip = (page - 1) * limit

            # Get notifications
            notifications, total = await self.notification_repo.get_company_notifications(
                db, company_id, skip=skip, limit=limit, is_read=is_read, time_filter=time_filter
            )

            # Get unread count
            unread_count = await self.notification_repo.get_unread_count_for_company(db, company_id)

            pages = math.ceil(total / limit) if limit > 0 else 0

            return {
                "items": notifications,
                "total": total,
                "page": page,
                "pages": pages,
                "unread_count": unread_count
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error("get_notifications_failed", company_id=str(company_id), error=str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve notifications"
            )

    async def mark_notification_read(
        self,
        db: AsyncSession,
        notification_id: UUID,
        user_id: UUID
    ) -> dict:
        """
        Mark a notification as read (with authorization check).

        Args:
            db: Active database session
            notification_id: UUID of the notification
            user_id: UUID of the user (for authorization)

        Returns:
            Updated notification

        Raises:
            HTTPException: 404 if not found, 403 if unauthorized

        Example:
            notification = await service.mark_notification_read(
                db, notification_id, user_id
            )
            await db.commit()
        """
        try:
            notification = await self.notification_repo.get_with_relations(db, notification_id)
            if not notification:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Notification {notification_id} not found"
                )

            # Verify user owns the notification
            if notification.user_id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied. You can only mark your own notifications as read"
                )

            if not notification.is_read:
                notification.is_read = True
                notification.read_at = datetime.utcnow()
                await db.flush()

            return notification

        except HTTPException:
            raise
        except Exception as e:
            logger.error("mark_read_failed", notification_id=str(notification_id), error=str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to mark notification as read"
            )

    async def mark_company_notification_read(
        self,
        db: AsyncSession,
        notification_id: UUID,
        company_id: UUID
    ) -> dict:
        """
        Mark a company notification as read (with authorization check).

        Args:
            db: Active database session
            notification_id: UUID of the notification
            company_id: UUID of the company (for authorization)

        Returns:
            Updated notification

        Raises:
            HTTPException: 404 if not found, 403 if unauthorized
        """
        try:
            notification = await self.notification_repo.get_with_relations(db, notification_id)
            if not notification:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Notification {notification_id} not found"
                )

            # Verify company owns the notification
            if notification.company_id != company_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied. You can only mark your company's notifications as read"
                )

            if not notification.is_read:
                notification.is_read = True
                notification.read_at = datetime.utcnow()
                await db.flush()

            return notification

        except HTTPException:
            raise
        except Exception as e:
            logger.error("mark_read_failed", notification_id=str(notification_id), error=str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to mark notification as read"
            )

    async def mark_all_read_for_user(
        self,
        db: AsyncSession,
        user_id: UUID
    ) -> dict:
        """
        Mark all notifications as read for a user.

        Args:
            db: Active database session
            user_id: UUID of the user

        Returns:
            Dictionary with updated_count

        Example:
            result = await service.mark_all_read_for_user(db, user_id)
            await db.commit()
            print(f"Marked {result['updated_count']} notifications as read")
        """
        try:
            count = await self.notification_repo.mark_all_as_read_for_user(db, user_id)
            return {"updated_count": count}

        except Exception as e:
            logger.error("mark_all_read_failed", user_id=str(user_id), error=str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to mark all notifications as read"
            )

    async def mark_all_read_for_company(
        self,
        db: AsyncSession,
        company_id: UUID
    ) -> dict:
        """
        Mark all notifications as read for a company.

        Args:
            db: Active database session
            company_id: UUID of the company

        Returns:
            Dictionary with updated_count
        """
        try:
            count = await self.notification_repo.mark_all_as_read_for_company(db, company_id)
            return {"updated_count": count}

        except Exception as e:
            logger.error("mark_all_read_failed", company_id=str(company_id), error=str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to mark all notifications as read"
            )

    async def create_application_status_notification(
        self,
        db: AsyncSession,
        application_id: UUID,
        old_stage: str,
        new_stage: str
    ):
        """
        Create a notification when application status changes.

        This is triggered by the application service after status update.
        Notification failures are logged but don't block the main operation.

        Args:
            db: Active database session
            application_id: UUID of the application
            old_stage: Previous stage
            new_stage: New stage

        Example:
            await service.create_application_status_notification(
                db, app_id, "SUBMITTED", "REVIEW"
            )
            await db.commit()
        """
        try:
            logger.info("creating_status_notification", application_id=str(application_id), old_stage=old_stage, new_stage=new_stage)

            # Get application with related data
            application = await self.application_repo.get(db, application_id)
            if not application:
                logger.error("notification_skipped", reason="application_not_found", application_id=str(application_id))
                return None

            # Get job details
            job = await self.job_repo.get(db, application.job_id)
            if not job:
                logger.error("notification_skipped", reason="job_not_found", job_id=str(application.job_id))
                return None

            # Verify company relationship is loaded
            if not job.company:
                logger.error("notification_skipped", reason="company_not_loaded", job_id=str(job.id))
                return None

            # Generate notification message based on stage transition
            message = self._generate_stage_change_message(job.title, job.company.name, old_stage, new_stage)

            # Deduplication: skip if an identical notification was created recently
            duplicate = await self.notification_repo.find_recent_duplicate(
                db,
                notification_type=NotificationType.APPLICATION_UPDATE,
                within_seconds=60,
                user_id=application.user_id,
                application_id=application.id,
            )
            if duplicate:
                logger.info("notification_deduplicated", type="APPLICATION_UPDATE", application_id=str(application_id), existing_id=str(duplicate.id))
                return duplicate

            # Create notification for the job seeker
            notification_data = {
                "user_id": application.user_id,
                "title": "Application Status Updated",
                "message": message,
                "type": NotificationType.APPLICATION_UPDATE,
                "job_id": job.id,
                "application_id": application.id,
                "is_read": False
            }

            notification = await self.notification_repo.create_notification(db, notification_data)

            logger.info("notification_created", notification_id=str(notification.id), user_id=str(application.user_id), application_id=str(application_id))

            # Send real-time WebSocket notification
            try:
                ws_payload = {
                    "type": "notification",
                    "data": {
                        "id": str(notification.id),
                        "user_id": str(application.user_id),
                        "title": notification_data["title"],
                        "message": notification_data["message"],
                        "type": notification_data["type"].value,  # Changed from notification_type to type
                        "job_id": str(job.id) if job else None,
                        "application_id": str(application.id),
                        "created_at": notification.created_at.isoformat(),
                        "is_read": False
                    }
                }
                await connection_manager.send_to_user(
                    application.user_id,
                    ws_payload
                )
            except Exception as ws_error:
                logger.error("websocket_send_failed", user_id=str(application.user_id), error=str(ws_error))

            # Enqueue push notification (avoids blocking request thread on Expo API)
            try:
                from app.core.arq import get_arq_pool
                arq = await get_arq_pool()
                await arq.enqueue_job(
                    "deliver_push_notification",
                    "user",
                    str(application.user_id),
                    notification_data["title"],
                    message,
                    {
                        "notification_id": str(notification.id),
                        "job_id": str(job.id) if job else None,
                        "application_id": str(application.id),
                        "type": notification_data["type"].value,
                    },
                )
            except Exception as push_error:
                logger.warning("push_enqueue_failed", target="user", error=str(push_error))

            return notification

        except Exception as e:
            # Log but don't raise - notification failures shouldn't block the main operation
            logger.error("notification_failed", application_id=str(application_id), error=str(e), exc_info=True)
            return None

    async def create_new_application_notification(
        self,
        db: AsyncSession,
        application_id: UUID
    ):
        """
        Create a notification when a new application is submitted.

        This is triggered after a user swipes RIGHT on a job.
        Notification failures are logged but don't block the main operation.

        Args:
            db: Active database session
            application_id: UUID of the application

        Example:
            await service.create_new_application_notification(db, app_id)
            await db.commit()
        """
        try:
            logger.info("creating_new_application_notification", application_id=str(application_id))

            # Get application with related data - the repo loads user and job relationships
            application = await self.application_repo.get(db, application_id)
            if not application:
                logger.error("notification_skipped", reason="application_not_found", application_id=str(application_id))
                return None

            # Verify user relationship is loaded
            if not application.user:
                logger.error("notification_skipped", reason="user_not_loaded", application_id=str(application_id))
                return None

            # Get job and user details
            job = await self.job_repo.get(db, application.job_id)
            if not job:
                logger.error("notification_skipped", reason="job_not_found", job_id=str(application.job_id))
                return None

            # Verify company relationship is loaded
            if not job.company:
                logger.error("notification_skipped", reason="company_not_loaded", job_id=str(job.id))
                return None

            # Create notification for the company
            applicant_name = application.user.full_name or application.user.email
            message = f"{applicant_name} has applied to your job posting: {job.title}"

            # Deduplication: skip if an identical notification was created recently
            duplicate = await self.notification_repo.find_recent_duplicate(
                db,
                notification_type=NotificationType.NEW_APPLICATION,
                within_seconds=60,
                company_id=job.company_id,
                application_id=application.id,
            )
            if duplicate:
                logger.info("notification_deduplicated", type="NEW_APPLICATION", application_id=str(application_id), existing_id=str(duplicate.id))
                return duplicate

            notification_data = {
                "company_id": job.company_id,
                "title": "New Application Received",
                "message": message,
                "type": NotificationType.NEW_APPLICATION,
                "job_id": job.id,
                "application_id": application.id,
                "is_read": False
            }

            notification = await self.notification_repo.create_notification(db, notification_data)

            logger.info("notification_created", notification_id=str(notification.id), company_id=str(job.company_id), application_id=str(application_id))

            # Send real-time WebSocket notification to company
            try:
                ws_payload = {
                    "type": "notification",
                    "data": {
                        "id": str(notification.id),
                        "company_id": str(job.company_id),
                        "title": notification_data["title"],
                        "message": notification_data["message"],
                        "type": notification_data["type"].value,  # Changed from notification_type to type
                        "job_id": str(job.id),
                        "application_id": str(application.id),
                        "created_at": notification.created_at.isoformat(),
                        "is_read": False
                    }
                }
                await connection_manager.send_to_company(
                    job.company_id,
                    ws_payload
                )
            except Exception as ws_error:
                logger.error("websocket_send_failed", company_id=str(job.company_id), error=str(ws_error))

            # Enqueue push notification to company (avoids blocking request thread on Expo API)
            try:
                from app.core.arq import get_arq_pool
                arq = await get_arq_pool()
                await arq.enqueue_job(
                    "deliver_push_notification",
                    "company",
                    str(job.company_id),
                    notification_data["title"],
                    message,
                    {
                        "notification_id": str(notification.id),
                        "job_id": str(job.id),
                        "application_id": str(application.id),
                        "type": notification_data["type"].value,
                    },
                )
            except Exception as push_error:
                logger.warning("push_enqueue_failed", target="company", error=str(push_error))

            return notification

        except Exception as e:
            # Log but don't raise - notification failures shouldn't block the main operation
            logger.error("notification_failed", application_id=str(application_id), error=str(e), exc_info=True)
            return None

    def _generate_stage_change_message(
        self,
        job_title: str,
        company_name: str,
        old_stage: str,
        new_stage: str
    ) -> str:
        """
        Generate human-readable message for stage transitions.

        Args:
            job_title: Title of the job
            company_name: Name of the company
            old_stage: Previous stage
            new_stage: New stage

        Returns:
            Formatted message string
        """
        stage_messages = {
            "REVIEW": "is now under review",
            "INTERVIEW": "has moved to the interview stage",
            "TECHNICAL": "has progressed to technical interview",
            "DECISION": "is in the final decision stage"
        }

        stage_description = stage_messages.get(new_stage, f"has moved to {new_stage} stage")
        return f"Your application for {job_title} at {company_name} {stage_description}."
