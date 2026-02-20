"""
Swipe service for business logic related to swipes and undo operations.

This module handles swipe management including undo limits, time window checks,
and daily counter resets with proper timezone handling.
"""

from __future__ import annotations
from typing import Optional, Tuple
from uuid import UUID
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.models.swipe import Swipe
from app.models.user import User
from app.models.application import Application
from app.repositories.swipe_repository import SwipeRepository

logger = logging.getLogger(__name__)


class SwipeService:
    """
    Service for managing swipes and undo operations.

    This service coordinates between repositories and implements
    business logic for undo operations, including:
    - Daily limit enforcement
    - Undo window validation
    - Counter resets
    - Application cleanup when swipes are undone
    """

    # Constants
    UNDO_WINDOW_SECONDS = 5
    FREE_USER_DAILY_LIMIT = 3
    PREMIUM_USER_DAILY_LIMIT = 10

    def __init__(
        self,
        swipe_repo: Optional[SwipeRepository] = None
    ):
        """
        Initialize service with repositories.

        Args:
            swipe_repo: SwipeRepository instance (creates new if None)
        """
        self.swipe_repo = swipe_repo or SwipeRepository()

    def _get_user_today(self, user: User) -> date:
        """
        Return today's date in the user's configured timezone.

        Falls back to UTC if the stored timezone string is missing or invalid.

        Args:
            user: User instance

        Returns:
            Current date in the user's local timezone
        """
        tz_name = getattr(user, "timezone", None) or "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            logger.warning(
                "Unknown timezone '%s' for user %s — falling back to UTC",
                tz_name,
                user.id,
            )
            tz = ZoneInfo("UTC")
        return datetime.now(tz).date()

    async def check_and_reset_daily_counter(
        self,
        db: AsyncSession,
        user: User
    ) -> User:
        """
        Check if daily undo counter needs to be reset and reset if necessary.

        The counter resets at midnight in the user's configured timezone
        (stored in ``user.timezone``, defaulting to ``"UTC"``).

        Args:
            db: Active database session
            user: User instance

        Returns:
            User instance (possibly updated)

        Example:
            user = await service.check_and_reset_daily_counter(db, user)
            await db.commit()
        """
        try:
            today = self._get_user_today(user)

            # Reset counter if it's a new day or never set
            if user.undo_count_reset_date is None or user.undo_count_reset_date < today:
                user.daily_undo_count = 0
                user.undo_count_reset_date = today
                await db.flush()

            return user

        except Exception as e:
            logger.error(f"Error resetting daily counter for user {user.id}: {e}")
            raise

    def get_daily_limit(self, user: User) -> int:
        """
        Get the daily undo limit for a user based on their subscription.

        Args:
            user: User instance

        Returns:
            Daily undo limit (3 for free, 10 for premium)

        Example:
            limit = service.get_daily_limit(user)
            print(f"User can undo {limit} times per day")
        """
        return self.PREMIUM_USER_DAILY_LIMIT if user.is_premium else self.FREE_USER_DAILY_LIMIT

    def get_remaining_daily_undos(self, user: User) -> int:
        """
        Get the number of remaining undos for the user today.

        Args:
            user: User instance

        Returns:
            Number of remaining undos

        Example:
            remaining = service.get_remaining_daily_undos(user)
            print(f"User has {remaining} undos left today")
        """
        limit = self.get_daily_limit(user)
        return max(0, limit - user.daily_undo_count)

    async def check_undo_eligibility(
        self,
        db: AsyncSession,
        user: User,
        swipe: Swipe
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a user can undo a swipe.

        Verifies:
        1. Swipe belongs to user
        2. Swipe is not already undone
        3. Swipe is within undo window
        4. User has not exceeded daily limit

        Args:
            db: Active database session
            user: User instance
            swipe: Swipe instance

        Returns:
            Tuple of (can_undo: bool, error_message: Optional[str])

        Example:
            can_undo, error = await service.check_undo_eligibility(db, user, swipe)
            if not can_undo:
                raise HTTPException(400, detail=error)
        """
        try:
            # Check ownership
            if swipe.user_id != user.id:
                return False, "This swipe does not belong to you"

            # Check if already undone
            if swipe.is_undone:
                return False, "This swipe has already been undone"

            # Check undo window
            time_elapsed = (datetime.now(timezone.utc) - swipe.created_at).total_seconds()
            if time_elapsed > self.UNDO_WINDOW_SECONDS:
                return False, f"Undo window ({self.UNDO_WINDOW_SECONDS} seconds) has expired"

            # Check daily limit
            await self.check_and_reset_daily_counter(db, user)
            remaining = self.get_remaining_daily_undos(user)
            if remaining <= 0:
                limit = self.get_daily_limit(user)
                return False, f"Daily undo limit reached ({limit} undos per day). {'Upgrade to premium for more undos!' if not user.is_premium else 'Try again tomorrow.'}"

            return True, None

        except Exception as e:
            logger.error(f"Error checking undo eligibility: {e}")
            return False, "Error checking undo eligibility"

    async def undo_swipe(
        self,
        db: AsyncSession,
        user: User,
        swipe_id: UUID
    ) -> Swipe:
        """
        Undo a swipe.

        This operation:
        1. Validates undo eligibility
        2. Marks swipe as undone
        3. Increments daily undo counter
        4. Deletes associated application if RIGHT swipe

        Args:
            db: Active database session
            user: User instance
            swipe_id: UUID of the swipe to undo

        Returns:
            Updated swipe instance

        Raises:
            HTTPException: If swipe not found or undo not allowed

        Example:
            swipe = await service.undo_swipe(db, user, swipe_id)
            await db.commit()
        """
        try:
            # Get swipe
            swipe = await self.swipe_repo.get(db, swipe_id)
            if not swipe:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Swipe not found"
                )

            # Check eligibility
            can_undo, error_message = await self.check_undo_eligibility(db, user, swipe)
            if not can_undo:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_message
                )

            # Mark as undone
            swipe = await self.swipe_repo.mark_as_undone(db, swipe)

            # Increment daily counter
            user.daily_undo_count += 1
            await db.flush()

            # If RIGHT swipe, delete associated application
            if swipe.direction == "RIGHT":
                from sqlalchemy import select, delete as sql_delete

                # Delete application
                delete_stmt = sql_delete(Application).where(
                    Application.user_id == user.id,
                    Application.job_id == swipe.job_id
                )
                await db.execute(delete_stmt)

                logger.info(f"Deleted application for user {user.id} on job {swipe.job_id} due to undo")

            logger.info(
                f"User {user.id} undid swipe {swipe_id} "
                f"(direction: {swipe.direction}, daily count: {user.daily_undo_count})"
            )

            return swipe

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error undoing swipe {swipe_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to undo swipe"
            )

    async def get_last_swipe_with_window(
        self,
        db: AsyncSession,
        user: User
    ) -> Optional[Tuple[Swipe, int]]:
        """
        Get the user's last swipe within undo window with remaining time.

        Args:
            db: Active database session
            user: User instance

        Returns:
            Tuple of (swipe, remaining_seconds) if within window, None otherwise

        Example:
            result = await service.get_last_swipe_with_window(db, user)
            if result:
                swipe, remaining = result
                print(f"Can undo for {remaining} more seconds")
        """
        try:
            swipe = await self.swipe_repo.get_last_swipe(
                db,
                user.id,
                undo_window_seconds=self.UNDO_WINDOW_SECONDS
            )

            if not swipe:
                return None

            # Calculate remaining time
            elapsed = (datetime.now(timezone.utc) - swipe.created_at).total_seconds()
            remaining = max(0, int(self.UNDO_WINDOW_SECONDS - elapsed))

            return swipe, remaining

        except Exception as e:
            logger.error(f"Error getting last swipe for user {user.id}: {e}")
            return None

    def get_undo_limit_info(self, user: User) -> dict:
        """
        Get information about user's undo limits and usage.

        Args:
            user: User instance

        Returns:
            Dictionary with limit information

        Example:
            info = service.get_undo_limit_info(user)
            print(f"Used {info['used_today']} of {info['daily_limit']}")
        """
        daily_limit = self.get_daily_limit(user)
        remaining = self.get_remaining_daily_undos(user)

        return {
            "daily_limit": daily_limit,
            "used_today": user.daily_undo_count,
            "remaining_today": remaining,
            "is_premium": user.is_premium
        }
