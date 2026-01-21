from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
import uuid

from app.core.database import get_db
from app.api.deps import get_current_user, get_job_seeker
from app.models.user import User
from app.schemas.search import RecentSearch, RecentSearchCreate
from app.services.search_service import search_service

router = APIRouter()


@router.post("/recent-searches", response_model=RecentSearch, status_code=201)
async def create_recent_search(
    search: RecentSearchCreate,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Save a search query to recent searches.

    This endpoint is typically called automatically after performing a search,
    but can also be called manually. Automatically maintains only the 10 most
    recent searches per user.
    """
    created_search = await search_service.save_recent_search(
        db=db,
        user_id=current_user.id,
        query=search.query,
        filters_used=search.filters_used
    )

    await db.commit()
    await db.refresh(created_search)

    return created_search


@router.get("/recent-searches", response_model=List[RecentSearch])
async def get_recent_searches(
    limit: int = Query(10, ge=1, le=20, description="Maximum number of recent searches to return"),
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Get recent searches for the current user.

    Returns up to the specified limit of recent searches, ordered by
    most recent first. Default limit is 10.
    """
    searches = await search_service.get_user_recent_searches(
        db=db,
        user_id=current_user.id,
        limit=limit
    )

    return searches


@router.delete("/recent-searches/{search_id}", status_code=204)
async def delete_recent_search(
    search_id: uuid.UUID,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a recent search entry.

    Removes a specific search from the user's recent search history.
    """
    await search_service.delete_recent_search(
        db=db,
        user_id=current_user.id,
        search_id=search_id
    )

    await db.commit()
