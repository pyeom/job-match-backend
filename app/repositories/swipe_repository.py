"""
Swipe repository for managing swipe data and undo operations.

This module provides specialized queries for swipes, including
undo window checks, last swipe queries, and filtering out undone swipes.
"""

from __future__ import annotations
from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, and_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
import logging

from app.models.swipe import Swipe
from app.models.job import Job
from .base import BaseRepository

logger = logging.getLogger(__name__)


class SwipeRepository(BaseRepository[Swipe]):
    """
    Repository for Swipe model with specialized undo queries.

    Provides methods for:
    - Getting last swipe within undo window
    - Checking if a swipe can be undone
    - Soft-deleting swipes (marking as undone)
    - Filtering out undone swipes
    """

    def __init__(self):
        """Initialize with Swipe model."""
        super().__init__(Swipe)

    async def get_last_swipe(
        self,
        db: AsyncSession,
        user_id: UUID,
        undo_window_seconds: int = 5
    ) -> Optional[Swipe]:
        """
        Get the user's last swipe within the undo window.

        Args:
            db: Active database session
            user_id: UUID of the user
            undo_window_seconds: Undo window in seconds (default: 5)

        Returns:
            Last swipe if within undo window and not undone, None otherwise

        Example:
            last_swipe = await repo.get_last_swipe(db, user_id, undo_window_seconds=5)
            if last_swipe:
                print(f"Last swipe was {time_ago} seconds ago")
        """
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=undo_window_seconds)

            stmt = (
                select(Swipe)
                .where(
                    and_(
                        Swipe.user_id == user_id,
                        Swipe.is_undone == False,
                        Swipe.created_at >= cutoff_time
                    )
                )
                .order_by(desc(Swipe.created_at))
                .limit(1)
            )

            result = await db.execute(stmt)
            return result.scalar_one_or_none()

        except SQLAlchemyError as e:
            logger.error(f"Error fetching last swipe for user {user_id}: {e}")
            raise

    async def get_with_job(
        self,
        db: AsyncSession,
        swipe_id: UUID
    ) -> Optional[Swipe]:
        """
        Get a swipe by ID with job relationship loaded.

        Args:
            db: Active database session
            swipe_id: UUID of the swipe

        Returns:
            Swipe instance with job loaded, or None if not found

        Example:
            swipe = await repo.get_with_job(db, swipe_id)
            if swipe and swipe.job:
                print(f"Swipe on job: {swipe.job.title}")
        """
        try:
            stmt = (
                select(Swipe)
                .where(Swipe.id == swipe_id)
                .options(selectinload(Swipe.job))
            )

            result = await db.execute(stmt)
            return result.scalar_one_or_none()

        except SQLAlchemyError as e:
            logger.error(f"Error fetching swipe {swipe_id} with job: {e}")
            raise

    async def mark_as_undone(
        self,
        db: AsyncSession,
        swipe: Swipe
    ) -> Swipe:
        """
        Mark a swipe as undone (soft delete).

        Args:
            db: Active database session
            swipe: Swipe instance to mark as undone

        Returns:
            Updated swipe instance

        Example:
            swipe = await repo.get(db, swipe_id)
            undone_swipe = await repo.mark_as_undone(db, swipe)
            await db.commit()
        """
        try:
            swipe.is_undone = True
            swipe.undone_at = datetime.now(timezone.utc)

            await db.flush()
            await db.refresh(swipe)

            return swipe

        except SQLAlchemyError as e:
            logger.error(f"Error marking swipe {swipe.id} as undone: {e}")
            await db.rollback()
            raise

    async def can_undo_swipe(
        self,
        db: AsyncSession,
        swipe: Swipe,
        undo_window_seconds: int = 5
    ) -> tuple[bool, Optional[str]]:
        """
        Check if a swipe can be undone.

        Args:
            db: Active database session
            swipe: Swipe instance to check
            undo_window_seconds: Undo window in seconds (default: 5)

        Returns:
            Tuple of (can_undo: bool, reason: Optional[str])
            If can_undo is False, reason contains the error message

        Example:
            can_undo, reason = await repo.can_undo_swipe(db, swipe)
            if not can_undo:
                raise HTTPException(400, detail=reason)
        """
        try:
            # Check if already undone
            if swipe.is_undone:
                return False, "Swipe has already been undone"

            # Check if within undo window
            time_elapsed = (datetime.now(timezone.utc) - swipe.created_at).total_seconds()
            if time_elapsed > undo_window_seconds:
                return False, f"Undo window ({undo_window_seconds} seconds) has expired"

            return True, None

        except Exception as e:
            logger.error(f"Error checking if swipe {swipe.id} can be undone: {e}")
            return False, "Error checking undo eligibility"

    async def count_active_swipes(
        self,
        db: AsyncSession,
        user_id: UUID,
        job_id: Optional[UUID] = None
    ) -> int:
        """
        Count active (non-undone) swipes for a user.

        Args:
            db: Active database session
            user_id: UUID of the user
            job_id: Optional UUID to filter by specific job

        Returns:
            Count of active swipes

        Example:
            count = await repo.count_active_swipes(db, user_id)
            print(f"User has {count} active swipes")
        """
        try:
            query = select(func.count(Swipe.id)).where(
                and_(
                    Swipe.user_id == user_id,
                    Swipe.is_undone == False
                )
            )

            if job_id:
                query = query.where(Swipe.job_id == job_id)

            result = await db.execute(query)
            return result.scalar() or 0

        except SQLAlchemyError as e:
            logger.error(f"Error counting active swipes for user {user_id}: {e}")
            raise

    async def get_user_active_swipe_on_job(
        self,
        db: AsyncSession,
        user_id: UUID,
        job_id: UUID
    ) -> Optional[Swipe]:
        """
        Get user's active (non-undone) swipe on a specific job.

        Args:
            db: Active database session
            user_id: UUID of the user
            job_id: UUID of the job

        Returns:
            Active swipe if exists, None otherwise

        Example:
            swipe = await repo.get_user_active_swipe_on_job(db, user_id, job_id)
            if swipe:
                print(f"User already swiped {swipe.direction} on this job")
        """
        try:
            stmt = (
                select(Swipe)
                .where(
                    and_(
                        Swipe.user_id == user_id,
                        Swipe.job_id == job_id,
                        Swipe.is_undone == False
                    )
                )
            )

            result = await db.execute(stmt)
            return result.scalar_one_or_none()

        except SQLAlchemyError as e:
            logger.error(f"Error fetching active swipe for user {user_id} on job {job_id}: {e}")
            raise

    async def get_right_swipes_count(
        self,
        db: AsyncSession,
        user_id: UUID
    ) -> int:
        """
        Count active RIGHT swipes for a user (for embedding updates).

        Args:
            db: Active database session
            user_id: UUID of the user

        Returns:
            Count of active RIGHT swipes

        Example:
            count = await repo.get_right_swipes_count(db, user_id)
            if count >= 5:
                # Update user embedding
        """
        try:
            stmt = (
                select(func.count(Swipe.id))
                .where(
                    and_(
                        Swipe.user_id == user_id,
                        Swipe.direction == "RIGHT",
                        Swipe.is_undone == False
                    )
                )
            )

            result = await db.execute(stmt)
            return result.scalar() or 0

        except SQLAlchemyError as e:
            logger.error(f"Error counting right swipes for user {user_id}: {e}")
            raise
