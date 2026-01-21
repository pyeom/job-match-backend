from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
import uuid

from app.core.database import get_db
from app.api.deps import get_current_user, get_job_seeker
from app.models.user import User
from app.schemas.search import FilterPreset, FilterPresetCreate, FilterPresetUpdate
from app.services.search_service import search_service

router = APIRouter()


@router.post("/filter-presets", response_model=FilterPreset, status_code=201)
async def create_filter_preset(
    preset: FilterPresetCreate,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Save a custom filter preset.

    Allows job seekers to save their frequently used search filters
    for quick access. If is_default is True, this preset will be
    automatically applied when opening the search page.
    """
    created_preset = await search_service.save_filter_preset(
        db=db,
        user_id=current_user.id,
        name=preset.name,
        filters=preset.filters,
        is_default=preset.is_default
    )

    await db.commit()
    await db.refresh(created_preset)

    return created_preset


@router.get("/filter-presets", response_model=List[FilterPreset])
async def get_filter_presets(
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all saved filter presets for the current user.

    Returns all filter presets ordered by creation date (newest first).
    """
    presets = await search_service.get_user_filter_presets(
        db=db,
        user_id=current_user.id
    )

    return presets


@router.patch("/filter-presets/{preset_id}", response_model=FilterPreset)
async def update_filter_preset(
    preset_id: uuid.UUID,
    preset_update: FilterPresetUpdate,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a filter preset.

    Allows updating the name, filters, or default status of a preset.
    """
    from app.repositories.filter_preset_repository import FilterPresetRepository

    repo = FilterPresetRepository()

    # Get the preset and verify ownership
    preset = await repo.get_user_preset_by_id(db, current_user.id, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Filter preset not found")

    # If setting as default, unset all other defaults
    if preset_update.is_default:
        await repo.unset_all_defaults(db, current_user.id)

    # Update the preset
    update_data = preset_update.model_dump(exclude_unset=True)
    updated_preset = await repo.update(db, preset, update_data)

    await db.commit()
    await db.refresh(updated_preset)

    return updated_preset


@router.delete("/filter-presets/{preset_id}", status_code=204)
async def delete_filter_preset(
    preset_id: uuid.UUID,
    current_user: User = Depends(get_job_seeker),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a filter preset.

    Permanently removes a saved filter preset.
    """
    await search_service.delete_filter_preset(
        db=db,
        user_id=current_user.id,
        preset_id=preset_id
    )

    await db.commit()
