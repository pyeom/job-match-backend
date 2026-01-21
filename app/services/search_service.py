"""
Search service for managing job search and filter operations.
"""

from __future__ import annotations
from typing import Optional, List, Tuple
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.models.job import Job
from app.models.user import User
from app.models.filter_preset import FilterPreset
from app.models.recent_search import RecentSearch
from app.repositories.job_repository import JobRepository
from app.repositories.filter_preset_repository import FilterPresetRepository
from app.repositories.recent_search_repository import RecentSearchRepository

logger = logging.getLogger(__name__)


class SearchService:
    """
    Service for managing job search and filter operations.

    Coordinates between job repository and filter/search repositories
    to provide comprehensive search functionality.
    """

    def __init__(
        self,
        job_repo: Optional[JobRepository] = None,
        filter_preset_repo: Optional[FilterPresetRepository] = None,
        recent_search_repo: Optional[RecentSearchRepository] = None
    ):
        """
        Initialize service with repositories.

        Args:
            job_repo: JobRepository instance (creates new if None)
            filter_preset_repo: FilterPresetRepository instance (creates new if None)
            recent_search_repo: RecentSearchRepository instance (creates new if None)
        """
        self.job_repo = job_repo or JobRepository()
        self.filter_preset_repo = filter_preset_repo or FilterPresetRepository()
        self.recent_search_repo = recent_search_repo or RecentSearchRepository()

    async def search_jobs(
        self,
        db: AsyncSession,
        user: User,
        keyword: Optional[str] = None,
        salary_min: Optional[int] = None,
        salary_max: Optional[int] = None,
        currency: Optional[str] = None,
        locations: Optional[List[str]] = None,
        work_arrangement: Optional[List[str]] = None,
        seniority_levels: Optional[List[str]] = None,
        job_types: Optional[List[str]] = None,
        skills: Optional[List[str]] = None,
        sort_by: str = "match_score",
        sort_order: str = "desc",
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[Tuple[Job, int]], int]:
        """
        Search jobs with comprehensive filters.

        Args:
            db: Active database session
            user: Current user
            keyword: Search job title, company name, description
            salary_min: Minimum salary filter
            salary_max: Maximum salary filter
            currency: Currency filter
            locations: Multi-select location filter
            work_arrangement: Remote/Hybrid/On-site filter
            seniority_levels: Seniority levels filter
            job_types: Job types filter
            skills: Skills/tags filter
            sort_by: Sort field
            sort_order: Sort order
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            Tuple of (list of (job, score) tuples, total count)

        Example:
            jobs, total = await service.search_jobs(
                db, user, keyword="Python", skills=["FastAPI"]
            )
        """
        try:
            return await self.job_repo.search_jobs_advanced(
                db=db,
                user=user,
                keyword=keyword,
                salary_min=salary_min,
                salary_max=salary_max,
                currency=currency,
                locations=locations,
                work_arrangement=work_arrangement,
                seniority_levels=seniority_levels,
                job_types=job_types,
                skills=skills,
                sort_by=sort_by,
                sort_order=sort_order,
                skip=skip,
                limit=limit
            )

        except Exception as e:
            logger.error(f"Error in search_jobs service: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to search jobs"
            )

    async def save_filter_preset(
        self,
        db: AsyncSession,
        user_id: UUID,
        name: str,
        filters: dict,
        is_default: bool = False
    ) -> FilterPreset:
        """
        Save a filter preset for a user.

        If is_default is True, unsets all other defaults first.

        Args:
            db: Active database session
            user_id: UUID of the user
            name: Preset name
            filters: Filter parameters as dict
            is_default: Whether this is the default preset

        Returns:
            Created FilterPreset instance

        Example:
            preset = await service.save_filter_preset(
                db, user_id, "My Filters", {"keyword": "Python"}
            )
        """
        try:
            # If setting as default, unset all other defaults
            if is_default:
                await self.filter_preset_repo.unset_all_defaults(db, user_id)

            preset_data = {
                "user_id": user_id,
                "name": name,
                "filters": filters,
                "is_default": is_default
            }

            preset = await self.filter_preset_repo.create(db, preset_data)
            logger.info(f"Filter preset '{name}' saved for user {user_id}")

            return preset

        except Exception as e:
            logger.error(f"Error saving filter preset: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save filter preset"
            )

    async def get_user_filter_presets(
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
            presets = await service.get_user_filter_presets(db, user_id)
        """
        try:
            return await self.filter_preset_repo.get_user_presets(db, user_id)

        except Exception as e:
            logger.error(f"Error fetching filter presets: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to fetch filter presets"
            )

    async def delete_filter_preset(
        self,
        db: AsyncSession,
        user_id: UUID,
        preset_id: UUID
    ) -> None:
        """
        Delete a filter preset.

        Args:
            db: Active database session
            user_id: UUID of the user
            preset_id: UUID of the preset to delete

        Raises:
            HTTPException: 404 if not found, 403 if unauthorized

        Example:
            await service.delete_filter_preset(db, user_id, preset_id)
        """
        try:
            preset = await self.filter_preset_repo.get_user_preset_by_id(
                db, user_id, preset_id
            )

            if not preset:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Filter preset not found"
                )

            await self.filter_preset_repo.delete(db, preset_id)
            logger.info(f"Filter preset {preset_id} deleted by user {user_id}")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting filter preset: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete filter preset"
            )

    async def save_recent_search(
        self,
        db: AsyncSession,
        user_id: UUID,
        query: Optional[str],
        filters_used: Optional[dict]
    ) -> RecentSearch:
        """
        Save a recent search for a user.

        Automatically cleans up old searches to keep only the most recent 10.

        Args:
            db: Active database session
            user_id: UUID of the user
            query: Keyword search query
            filters_used: Filters applied in the search

        Returns:
            Created RecentSearch instance

        Example:
            search = await service.save_recent_search(
                db, user_id, "Python", {"seniority_levels": ["Mid"]}
            )
        """
        try:
            search_data = {
                "user_id": user_id,
                "query": query,
                "filters_used": filters_used
            }

            search = await self.recent_search_repo.create(db, search_data)

            # Clean up old searches (keep only 10 most recent)
            await self.recent_search_repo.cleanup_old_searches(db, user_id, keep_count=10)

            logger.info(f"Recent search saved for user {user_id}")

            return search

        except Exception as e:
            logger.error(f"Error saving recent search: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save recent search"
            )

    async def get_user_recent_searches(
        self,
        db: AsyncSession,
        user_id: UUID,
        limit: int = 10
    ) -> List[RecentSearch]:
        """
        Get user's recent searches.

        Args:
            db: Active database session
            user_id: UUID of the user
            limit: Maximum number of searches to return

        Returns:
            List of RecentSearch instances

        Example:
            searches = await service.get_user_recent_searches(db, user_id)
        """
        try:
            return await self.recent_search_repo.get_user_recent_searches(
                db, user_id, limit
            )

        except Exception as e:
            logger.error(f"Error fetching recent searches: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to fetch recent searches"
            )

    async def delete_recent_search(
        self,
        db: AsyncSession,
        user_id: UUID,
        search_id: UUID
    ) -> None:
        """
        Delete a recent search.

        Args:
            db: Active database session
            user_id: UUID of the user
            search_id: UUID of the search to delete

        Raises:
            HTTPException: 404 if not found

        Example:
            await service.delete_recent_search(db, user_id, search_id)
        """
        try:
            search = await self.recent_search_repo.get_user_search_by_id(
                db, user_id, search_id
            )

            if not search:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Recent search not found"
                )

            await self.recent_search_repo.delete(db, search_id)
            logger.info(f"Recent search {search_id} deleted by user {user_id}")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting recent search: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete recent search"
            )


# Create singleton instance
search_service = SearchService()
