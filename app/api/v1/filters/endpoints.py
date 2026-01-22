"""
Filter endpoints for managing search filters and presets.

This module provides endpoints for:
- Managing filter presets (create, list, delete)
- Getting filter suggestions (locations, skills)
- Managing recent searches
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct
from typing import List, Optional
from uuid import UUID

from app.core.database import get_db
from app.api.deps import get_current_user, get_job_seeker
from app.models.user import User
from app.models.job import Job
from app.schemas.search import (
    FilterPreset,
    FilterPresetCreate,
    FilterPresetUpdate,
    RecentSearch
)
from app.services.search_service import search_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/presets", response_model=List[FilterPreset])
async def get_filter_presets(
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all saved filter presets for the current user.

    Returns presets ordered by creation date (newest first).
    Each preset contains saved filter parameters that can be
    quickly applied to job searches.
    """
    try:
        presets = await search_service.get_user_filter_presets(db, current_user.id)
        return presets

    except Exception as e:
        logger.error(f"Error fetching filter presets: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch filter presets"
        )


@router.post("/presets", response_model=FilterPreset, status_code=status.HTTP_201_CREATED)
async def create_filter_preset(
    preset_data: FilterPresetCreate,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new filter preset.

    Saves the current filter configuration for quick access later.
    If marked as default, it will be the first preset shown to the user.
    """
    try:
        preset = await search_service.save_filter_preset(
            db=db,
            user_id=current_user.id,
            name=preset_data.name,
            filters=preset_data.filters,
            is_default=preset_data.is_default
        )
        await db.commit()
        await db.refresh(preset)
        return preset

    except Exception as e:
        logger.error(f"Error creating filter preset: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create filter preset"
        )


@router.patch("/presets/{preset_id}", response_model=FilterPreset)
async def update_filter_preset(
    preset_id: UUID,
    preset_update: FilterPresetUpdate,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Update an existing filter preset.

    Can update the name, filters, or default status.
    Only the preset owner can update it.
    """
    from app.repositories.filter_preset_repository import FilterPresetRepository

    try:
        preset_repo = FilterPresetRepository()

        # Get preset and verify ownership
        preset = await preset_repo.get_user_preset_by_id(db, current_user.id, preset_id)
        if not preset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Filter preset not found"
            )

        # If setting as default, unset other defaults
        if preset_update.is_default:
            await preset_repo.unset_all_defaults(db, current_user.id)

        # Update preset
        update_data = preset_update.model_dump(exclude_unset=True)
        updated_preset = await preset_repo.update(db, preset, update_data)

        await db.commit()
        await db.refresh(updated_preset)
        return updated_preset

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating filter preset: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update filter preset"
        )


@router.delete("/presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_filter_preset(
    preset_id: UUID,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a filter preset.

    Only the preset owner can delete it.
    """
    try:
        await search_service.delete_filter_preset(db, current_user.id, preset_id)
        await db.commit()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting filter preset: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete filter preset"
        )


@router.get("/suggestions/locations", response_model=List[str])
async def get_location_suggestions(
    query: Optional[str] = Query(None, min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Get location autocomplete suggestions.

    Returns a list of distinct locations from active job postings
    that match the query string (case-insensitive).

    Args:
        query: Optional search query to filter locations
        limit: Maximum number of suggestions to return (default: 10)

    Returns:
        List of location strings, ordered by frequency
    """
    try:
        # Build query for distinct locations from active jobs
        stmt = (
            select(Job.location, func.count(Job.id).label('count'))
            .where(Job.is_active == True, Job.location.isnot(None))
            .group_by(Job.location)
        )

        # Add search filter if query provided
        if query:
            stmt = stmt.where(Job.location.ilike(f"%{query}%"))

        # Order by frequency and limit
        stmt = stmt.order_by(func.count(Job.id).desc()).limit(limit)

        result = await db.execute(stmt)
        locations = [row[0] for row in result.all() if row[0]]

        return locations

    except Exception as e:
        logger.error(f"Error fetching location suggestions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch location suggestions"
        )


@router.get("/suggestions/skills", response_model=List[str])
async def get_skill_suggestions(
    query: Optional[str] = Query(None, min_length=1, max_length=100),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Get skill/tag autocomplete suggestions.

    Returns a list of popular skills from active job postings.
    Skills are extracted from job tags and ordered by frequency.

    Args:
        query: Optional search query to filter skills (case-insensitive)
        limit: Maximum number of suggestions to return (default: 20)

    Returns:
        List of skill strings, ordered by frequency
    """
    try:
        from sqlalchemy.dialects.postgresql import JSONB

        # Get all jobs with tags
        stmt = (
            select(Job.tags)
            .where(Job.is_active == True, Job.tags.isnot(None))
        )

        result = await db.execute(stmt)
        all_jobs = result.scalars().all()

        # Extract and count all tags
        skill_counts: dict[str, int] = {}
        for tags in all_jobs:
            if isinstance(tags, list):
                for tag in tags:
                    if isinstance(tag, str):
                        # Apply query filter if provided
                        if query and query.lower() not in tag.lower():
                            continue

                        skill_counts[tag] = skill_counts.get(tag, 0) + 1

        # Sort by frequency and return top N
        sorted_skills = sorted(
            skill_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:limit]

        skills = [skill for skill, _ in sorted_skills]
        return skills

    except Exception as e:
        logger.error(f"Error fetching skill suggestions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch skill suggestions"
        )


@router.get("/recent-searches", response_model=List[RecentSearch])
async def get_recent_searches(
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Get user's recent search history.

    Returns the most recent searches, ordered by date (newest first).

    Args:
        limit: Maximum number of searches to return (default: 10)

    Returns:
        List of recent searches with query and filters used
    """
    try:
        searches = await search_service.get_user_recent_searches(
            db, current_user.id, limit
        )
        return searches

    except Exception as e:
        logger.error(f"Error fetching recent searches: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch recent searches"
        )


@router.delete("/recent-searches/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recent_search(
    search_id: UUID,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a specific recent search.

    Only the search owner can delete it.
    """
    try:
        await search_service.delete_recent_search(db, current_user.id, search_id)
        await db.commit()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting recent search: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete recent search"
        )


@router.delete("/recent-searches", status_code=status.HTTP_204_NO_CONTENT)
async def clear_recent_searches(
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Clear all recent searches for the current user.

    Deletes all search history entries.
    """
    from app.repositories.recent_search_repository import RecentSearchRepository

    try:
        recent_search_repo = RecentSearchRepository()

        # Get all user's searches
        searches = await recent_search_repo.get_user_recent_searches(
            db, current_user.id, limit=1000
        )

        # Delete all
        for search in searches:
            await db.delete(search)

        await db.commit()
        logger.info(f"Cleared {len(searches)} recent searches for user {current_user.id}")

    except Exception as e:
        logger.error(f"Error clearing recent searches: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear recent searches"
        )
