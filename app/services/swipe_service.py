"""
Swipe service for business logic related to swipes and undo operations.

This module handles swipe management including undo time-window checks
and application cleanup when a swipe is undone.
"""

from __future__ import annotations
from typing import Optional, Tuple
from uuid import UUID
from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.models.swipe import Swipe
from app.models.user import User
from app.repositories.swipe_repository import SwipeRepository

logger = logging.getLogger(__name__)


class SwipeService:
    """
    Service for managing swipes and undo operations.

    This service coordinates between repositories and implements
    business logic for undo operations, including:
    - Undo window validation (5-second time limit)
    - Application cleanup when swipes are undone
    """

    # Constants — session-level rolling window of 2 minutes
    UNDO_WINDOW_SECONDS = 120

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
        3. Swipe is within the undo window

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

            # Check undo window (2-minute session-level rolling window)
            time_elapsed = (datetime.now(timezone.utc) - swipe.created_at).total_seconds()
            if time_elapsed > self.UNDO_WINDOW_SECONDS:
                return False, "Undo window has expired (2 minutes)"

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
        1. Validates undo eligibility (ownership, not already undone, within window)
        2. Marks swipe as undone
        3. Deletes associated application if RIGHT swipe

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

            logger.info(
                f"User {user.id} undid swipe {swipe_id} (direction: {swipe.direction})"
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

    async def get_undoable_swipes(
        self,
        db: AsyncSession,
        user: User
    ) -> list[Swipe]:
        """
        Get all swipes the user can still undo (within the 2-minute session window),
        sorted newest first.
        """
        try:
            return await self.swipe_repo.get_undoable_swipes(
                db,
                user.id,
                undo_window_seconds=self.UNDO_WINDOW_SECONDS
            )
        except Exception as e:
            logger.error(f"Error getting undoable swipes for user {user.id}: {e}")
            return []

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
