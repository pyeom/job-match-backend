"""
Notification repository for managing notification data.

This module provides specialized queries for notifications, including
filtering by user/company, read status, type, and eager loading of
related entities for enriched responses.
"""

from __future__ import annotations
from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta
from sqlalchemy import select, func, and_, or_, update as sql_update, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.exc import SQLAlchemyError
import logging

from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.models.job import Job
from app.models.application import Application
from app.models.company import Company
from .base import BaseRepository

logger = logging.getLogger(__name__)


class NotificationRepository(BaseRepository[Notification]):
    """
    Repository for Notification model with specialized queries.

    Provides methods for:
    - Filtering notifications by user or company
    - Read status filtering and updates
    - Type-based filtering
    - Eager loading of related entities (job, user, company)
    - Unread count queries
    """

    def __init__(self):
        """Initialize with Notification model."""
        super().__init__(Notification)

    async def get_user_notifications(
        self,
        db: AsyncSession,
        user_id: UUID,
        skip: int = 0,
        limit: int = 50,
        is_read: Optional[bool] = None,
        notification_type: Optional[NotificationType] = None
    ) -> tuple[list[Notification], int]:
        """
        Get paginated notifications for a user with job enrichment.

        Args:
            db: Active database session
            user_id: UUID of the user
            skip: Number of records to skip (offset)
            limit: Maximum number of records to return
            is_read: Optional filter by read status
            notification_type: Optional filter by notification type

        Returns:
            Tuple of (list of notifications with job/application loaded, total count)

        Example:
            notifications, total = await repo.get_user_notifications(
                db, user_id, skip=0, limit=20, is_read=False
            )
        """
        try:
            # Build base query with eager loading
            query = (
                select(Notification)
                .where(Notification.user_id == user_id)
                .options(
                    joinedload(Notification.job).joinedload(Job.company),
                    joinedload(Notification.application)
                )
                .order_by(desc(Notification.created_at))
            )

            # Add filters
            if is_read is not None:
                query = query.where(Notification.is_read == is_read)

            if notification_type is not None:
                query = query.where(Notification.type == notification_type)

            # Get paginated results
            paginated_query = query.offset(skip).limit(limit)
            result = await db.execute(paginated_query)
            notifications = list(result.unique().scalars().all())

            # Get total count with same filters
            count_query = (
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == user_id)
            )

            if is_read is not None:
                count_query = count_query.where(Notification.is_read == is_read)

            if notification_type is not None:
                count_query = count_query.where(Notification.type == notification_type)

            count_result = await db.execute(count_query)
            total = count_result.scalar_one()

            return notifications, total

        except SQLAlchemyError as e:
            logger.error(f"Error fetching notifications for user {user_id}: {e}")
            raise

    async def get_company_notifications(
        self,
        db: AsyncSession,
        company_id: UUID,
        skip: int = 0,
        limit: int = 50,
        is_read: Optional[bool] = None,
        time_filter: Optional[str] = None
    ) -> tuple[list[Notification], int]:
        """
        Get paginated notifications for a company with applicant/job enrichment.

        Args:
            db: Active database session
            company_id: UUID of the company
            skip: Number of records to skip
            limit: Maximum number of records to return
            is_read: Optional filter by read status
            time_filter: Optional time range filter ('7d' or '30d')

        Returns:
            Tuple of (list of notifications with user/job loaded, total count)

        Example:
            notifications, total = await repo.get_company_notifications(
                db, company_id, skip=0, limit=50, time_filter='7d'
            )
        """
        try:
            # Build base query with eager loading
            query = (
                select(Notification)
                .where(Notification.company_id == company_id)
                .options(
                    joinedload(Notification.user),
                    joinedload(Notification.job),
                    joinedload(Notification.application)
                )
                .order_by(desc(Notification.created_at))
            )

            # Add filters
            if is_read is not None:
                query = query.where(Notification.is_read == is_read)

            # Time range filter
            if time_filter:
                now = datetime.utcnow()
                if time_filter == '7d':
                    cutoff = now - timedelta(days=7)
                    query = query.where(Notification.created_at >= cutoff)
                elif time_filter == '30d':
                    cutoff = now - timedelta(days=30)
                    query = query.where(Notification.created_at >= cutoff)

            # Get paginated results
            paginated_query = query.offset(skip).limit(limit)
            result = await db.execute(paginated_query)
            notifications = list(result.unique().scalars().all())

            # Get total count with same filters
            count_query = (
                select(func.count())
                .select_from(Notification)
                .where(Notification.company_id == company_id)
            )

            if is_read is not None:
                count_query = count_query.where(Notification.is_read == is_read)

            if time_filter:
                now = datetime.utcnow()
                if time_filter == '7d':
                    cutoff = now - timedelta(days=7)
                    count_query = count_query.where(Notification.created_at >= cutoff)
                elif time_filter == '30d':
                    cutoff = now - timedelta(days=30)
                    count_query = count_query.where(Notification.created_at >= cutoff)

            count_result = await db.execute(count_query)
            total = count_result.scalar_one()

            return notifications, total

        except SQLAlchemyError as e:
            logger.error(f"Error fetching notifications for company {company_id}: {e}")
            raise

    async def get_with_relations(
        self,
        db: AsyncSession,
        notification_id: UUID
    ) -> Optional[Notification]:
        """
        Retrieve a notification by ID with job, company, and user relations eagerly loaded.

        Args:
            db: Active database session
            notification_id: UUID of the notification

        Returns:
            Notification with relations loaded, or None if not found
        """
        try:
            stmt = (
                select(Notification)
                .where(Notification.id == notification_id)
                .options(
                    joinedload(Notification.job).joinedload(Job.company),
                    joinedload(Notification.application),
                    joinedload(Notification.user),
                )
            )
            result = await db.execute(stmt)
            return result.unique().scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching notification {notification_id} with relations: {e}")
            raise

    async def mark_as_read(
        self,
        db: AsyncSession,
        notification_id: UUID
    ) -> Optional[Notification]:
        """
        Mark a single notification as read.

        Args:
            db: Active database session
            notification_id: UUID of the notification

        Returns:
            Updated notification with relations loaded, or None if not found

        Example:
            notification = await repo.mark_as_read(db, notification_id)
            if notification:
                await db.commit()
        """
        try:
            notification = await self.get_with_relations(db, notification_id)
            if notification and not notification.is_read:
                notification.is_read = True
                notification.read_at = datetime.utcnow()
                await db.flush()

            return notification

        except SQLAlchemyError as e:
            logger.error(f"Error marking notification {notification_id} as read: {e}")
            raise

    async def mark_all_as_read_for_user(
        self,
        db: AsyncSession,
        user_id: UUID
    ) -> int:
        """
        Mark all unread notifications for a user as read.

        Args:
            db: Active database session
            user_id: UUID of the user

        Returns:
            Number of notifications updated

        Example:
            count = await repo.mark_all_as_read_for_user(db, user_id)
            await db.commit()
            print(f"Marked {count} notifications as read")
        """
        try:
            stmt = (
                sql_update(Notification)
                .where(
                    and_(
                        Notification.user_id == user_id,
                        Notification.is_read == False
                    )
                )
                .values(
                    is_read=True,
                    read_at=datetime.utcnow()
                )
            )

            result = await db.execute(stmt)
            await db.flush()
            return result.rowcount

        except SQLAlchemyError as e:
            logger.error(f"Error marking all notifications as read for user {user_id}: {e}")
            raise

    async def mark_all_as_read_for_company(
        self,
        db: AsyncSession,
        company_id: UUID
    ) -> int:
        """
        Mark all unread notifications for a company as read.

        Args:
            db: Active database session
            company_id: UUID of the company

        Returns:
            Number of notifications updated

        Example:
            count = await repo.mark_all_as_read_for_company(db, company_id)
            await db.commit()
        """
        try:
            stmt = (
                sql_update(Notification)
                .where(
                    and_(
                        Notification.company_id == company_id,
                        Notification.is_read == False
                    )
                )
                .values(
                    is_read=True,
                    read_at=datetime.utcnow()
                )
            )

            result = await db.execute(stmt)
            await db.flush()
            return result.rowcount

        except SQLAlchemyError as e:
            logger.error(f"Error marking all notifications as read for company {company_id}: {e}")
            raise

    async def get_unread_count_for_user(
        self,
        db: AsyncSession,
        user_id: UUID
    ) -> int:
        """
        Get count of unread notifications for a user.

        Args:
            db: Active database session
            user_id: UUID of the user

        Returns:
            Count of unread notifications

        Example:
            unread = await repo.get_unread_count_for_user(db, user_id)
            print(f"User has {unread} unread notifications")
        """
        try:
            stmt = (
                select(func.count())
                .select_from(Notification)
                .where(
                    and_(
                        Notification.user_id == user_id,
                        Notification.is_read == False
                    )
                )
            )

            result = await db.execute(stmt)
            return result.scalar_one()

        except SQLAlchemyError as e:
            logger.error(f"Error getting unread count for user {user_id}: {e}")
            raise

    async def get_unread_count_for_company(
        self,
        db: AsyncSession,
        company_id: UUID
    ) -> int:
        """
        Get count of unread notifications for a company.

        Args:
            db: Active database session
            company_id: UUID of the company

        Returns:
            Count of unread notifications

        Example:
            unread = await repo.get_unread_count_for_company(db, company_id)
        """
        try:
            stmt = (
                select(func.count())
                .select_from(Notification)
                .where(
                    and_(
                        Notification.company_id == company_id,
                        Notification.is_read == False
                    )
                )
            )

            result = await db.execute(stmt)
            return result.scalar_one()

        except SQLAlchemyError as e:
            logger.error(f"Error getting unread count for company {company_id}: {e}")
            raise

    async def create_notification(
        self,
        db: AsyncSession,
        data: dict
    ) -> Notification:
        """
        Create a new notification (internal use).

        Args:
            db: Active database session
            data: Dictionary with notification data

        Returns:
            Created notification

        Example:
            notification = await repo.create_notification(db, {
                "user_id": user_id,
                "title": "New Application",
                "message": "You have a new application",
                "type": "NEW_APPLICATION",
                "job_id": job_id
            })
            await db.commit()
        """
        return await self.create(db, data)
