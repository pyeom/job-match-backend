"""
Recent search repository for managing user's search history.
"""

from __future__ import annotations
from typing import List
from uuid import UUID
from sqlalchemy import select, and_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
import logging

from app.models.recent_search import RecentSearch
from .base import BaseRepository

logger = logging.getLogger(__name__)


class RecentSearchRepository(BaseRepository[RecentSearch]):
    """
    Repository for RecentSearch model.

    Provides methods for managing user's recent searches with automatic
    cleanup to limit to most recent 10 entries.
    """

    def __init__(self):
        """Initialize with RecentSearch model."""
        super().__init__(RecentSearch)

    async def get_user_recent_searches(
        self,
        db: AsyncSession,
        user_id: UUID,
        limit: int = 10
    ) -> List[RecentSearch]:
        """
        Get user's recent searches, most recent first.

        Args:
            db: Active database session
            user_id: UUID of the user
            limit: Maximum number of searches to return (default: 10)

        Returns:
            List of RecentSearch instances

        Example:
            searches = await repo.get_user_recent_searches(db, user_id, limit=10)
        """
        try:
            stmt = (
                select(RecentSearch)
                .where(RecentSearch.user_id == user_id)
                .order_by(desc(RecentSearch.searched_at))
                .limit(limit)
            )
            result = await db.execute(stmt)
            return list(result.scalars().all())

        except SQLAlchemyError as e:
            logger.error(f"Error fetching recent searches for user {user_id}: {e}")
            raise

    async def cleanup_old_searches(
        self,
        db: AsyncSession,
        user_id: UUID,
        keep_count: int = 10
    ) -> None:
        """
        Remove old searches, keeping only the most recent N entries.

        Args:
            db: Active database session
            user_id: UUID of the user
            keep_count: Number of recent searches to keep (default: 10)

        Example:
            await repo.cleanup_old_searches(db, user_id, keep_count=10)
        """
        try:
            # Get count of user's searches
            count_stmt = (
                select(func.count())
                .select_from(RecentSearch)
                .where(RecentSearch.user_id == user_id)
            )
            count_result = await db.execute(count_stmt)
            total_count = count_result.scalar_one()

            # If more than keep_count, delete oldest ones
            if total_count > keep_count:
                # Get IDs of searches to keep
                keep_stmt = (
                    select(RecentSearch.id)
                    .where(RecentSearch.user_id == user_id)
                    .order_by(desc(RecentSearch.searched_at))
                    .limit(keep_count)
                )
                keep_result = await db.execute(keep_stmt)
                keep_ids = [row[0] for row in keep_result.all()]

                # Delete searches not in keep list
                delete_stmt = (
                    select(RecentSearch)
                    .where(and_(
                        RecentSearch.user_id == user_id,
                        ~RecentSearch.id.in_(keep_ids)
                    ))
                )
                delete_result = await db.execute(delete_stmt)
                searches_to_delete = delete_result.scalars().all()

                for search in searches_to_delete:
                    await db.delete(search)

                logger.info(f"Cleaned up {len(searches_to_delete)} old searches for user {user_id}")

        except SQLAlchemyError as e:
            logger.error(f"Error cleaning up searches for user {user_id}: {e}")
            raise

    async def get_user_search_by_id(
        self,
        db: AsyncSession,
        user_id: UUID,
        search_id: UUID
    ) -> RecentSearch | None:
        """
        Get a specific recent search by ID, ensuring it belongs to the user.

        Args:
            db: Active database session
            user_id: UUID of the user
            search_id: UUID of the search

        Returns:
            RecentSearch instance or None

        Example:
            search = await repo.get_user_search_by_id(db, user_id, search_id)
        """
        try:
            stmt = (
                select(RecentSearch)
                .where(and_(
                    RecentSearch.id == search_id,
                    RecentSearch.user_id == user_id
                ))
            )
            result = await db.execute(stmt)
            return result.scalar_one_or_none()

        except SQLAlchemyError as e:
            logger.error(f"Error fetching search {search_id} for user {user_id}: {e}")
            raise
