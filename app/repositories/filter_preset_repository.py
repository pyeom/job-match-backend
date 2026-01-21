"""
Filter preset repository for managing user's saved search filters.
"""

from __future__ import annotations
from typing import Optional, List
from uuid import UUID
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
import logging

from app.models.filter_preset import FilterPreset
from .base import BaseRepository

logger = logging.getLogger(__name__)


class FilterPresetRepository(BaseRepository[FilterPreset]):
    """
    Repository for FilterPreset model.

    Provides methods for managing user's saved filter presets.
    """

    def __init__(self):
        """Initialize with FilterPreset model."""
        super().__init__(FilterPreset)

    async def get_user_presets(
        self,
        db: AsyncSession,
        user_id: UUID
    ) -> List[FilterPreset]:
        """
        Get all filter presets for a user.

        Args:
            db: Active database session
            user_id: UUID of the user

        Returns:
            List of FilterPreset instances

        Example:
            presets = await repo.get_user_presets(db, user_id)
        """
        try:
            stmt = (
                select(FilterPreset)
                .where(FilterPreset.user_id == user_id)
                .order_by(desc(FilterPreset.created_at))
            )
            result = await db.execute(stmt)
            return list(result.scalars().all())

        except SQLAlchemyError as e:
            logger.error(f"Error fetching filter presets for user {user_id}: {e}")
            raise

    async def get_user_default_preset(
        self,
        db: AsyncSession,
        user_id: UUID
    ) -> Optional[FilterPreset]:
        """
        Get user's default filter preset.

        Args:
            db: Active database session
            user_id: UUID of the user

        Returns:
            FilterPreset instance or None

        Example:
            default_preset = await repo.get_user_default_preset(db, user_id)
        """
        try:
            stmt = (
                select(FilterPreset)
                .where(and_(
                    FilterPreset.user_id == user_id,
                    FilterPreset.is_default == True
                ))
            )
            result = await db.execute(stmt)
            return result.scalar_one_or_none()

        except SQLAlchemyError as e:
            logger.error(f"Error fetching default preset for user {user_id}: {e}")
            raise

    async def unset_all_defaults(
        self,
        db: AsyncSession,
        user_id: UUID
    ) -> None:
        """
        Unset all default presets for a user.

        This is used before setting a new default preset.

        Args:
            db: Active database session
            user_id: UUID of the user

        Example:
            await repo.unset_all_defaults(db, user_id)
        """
        try:
            stmt = (
                select(FilterPreset)
                .where(and_(
                    FilterPreset.user_id == user_id,
                    FilterPreset.is_default == True
                ))
            )
            result = await db.execute(stmt)
            presets = result.scalars().all()

            for preset in presets:
                preset.is_default = False

        except SQLAlchemyError as e:
            logger.error(f"Error unsetting default presets for user {user_id}: {e}")
            raise

    async def get_user_preset_by_id(
        self,
        db: AsyncSession,
        user_id: UUID,
        preset_id: UUID
    ) -> Optional[FilterPreset]:
        """
        Get a specific filter preset by ID, ensuring it belongs to the user.

        Args:
            db: Active database session
            user_id: UUID of the user
            preset_id: UUID of the preset

        Returns:
            FilterPreset instance or None

        Example:
            preset = await repo.get_user_preset_by_id(db, user_id, preset_id)
        """
        try:
            stmt = (
                select(FilterPreset)
                .where(and_(
                    FilterPreset.id == preset_id,
                    FilterPreset.user_id == user_id
                ))
            )
            result = await db.execute(stmt)
            return result.scalar_one_or_none()

        except SQLAlchemyError as e:
            logger.error(f"Error fetching preset {preset_id} for user {user_id}: {e}")
            raise
