from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.user import User as UserSchema, UserUpdate
from app.services.embedding_service import embedding_service
import uuid

router = APIRouter()


# Legacy endpoints for backward compatibility (deprecated)
# NOTE: These MUST come before /{user_id} routes to avoid UUID parsing conflicts
@router.get("/me", response_model=UserSchema, deprecated=True)
async def get_current_user_profile_legacy(current_user: User = Depends(get_current_user)):
    """
    DEPRECATED: Get current user profile
    Use GET /users/{user_id} instead
    """
    return current_user


@router.patch("/me", response_model=UserSchema, deprecated=True)
async def update_current_user_legacy(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    DEPRECATED: Update current user profile
    Use PATCH /users/{user_id} instead
    """
    from sqlalchemy.orm.attributes import flag_modified

    update_data = user_update.model_dump(exclude_unset=True)

    # JSON/array columns that need explicit flagging for SQLAlchemy to detect changes
    json_fields = {'skills', 'experience', 'education', 'preferred_locations'}

    for field, value in update_data.items():
        setattr(current_user, field, value)
        if field in json_fields:
            flag_modified(current_user, field)

    # Recalculate embedding if profile fields changed
    if any(field in update_data for field in ['headline', 'skills', 'preferred_locations', 'seniority']):
        try:
            profile_embedding = embedding_service.generate_user_embedding(
                headline=current_user.headline,
                skills=current_user.skills,
                preferences=current_user.preferred_locations
            )
            current_user.profile_embedding = profile_embedding
        except Exception as e:
            # Log error but don't fail update
            print(f"Failed to regenerate profile embedding for user {current_user.id}: {e}")

    await db.commit()
    await db.refresh(current_user)

    return current_user


# RESTful user endpoints

@router.get("/{user_id}", response_model=UserSchema)
async def get_user_profile(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user profile by ID (users can only access their own profile)"""
    # Ensure users can only access their own profile
    if current_user.id != user_id:
        raise HTTPException(
            status_code=403,
            detail="You can only access your own profile"
        )
    return current_user


@router.patch("/{user_id}", response_model=UserSchema)
async def update_user_profile(
    user_id: uuid.UUID,
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update user profile by ID (users can only update their own profile)"""
    from sqlalchemy.orm.attributes import flag_modified

    # Ensure users can only update their own profile
    if current_user.id != user_id:
        raise HTTPException(
            status_code=403,
            detail="You can only update your own profile"
        )

    update_data = user_update.model_dump(exclude_unset=True)

    # Debug: log what we're updating
    print(f"User update request - user_id: {user_id}")
    print(f"Update data fields: {list(update_data.keys())}")
    if 'skills' in update_data:
        print(f"Skills being updated: {update_data['skills']}")

    # JSON/array columns that need explicit flagging for SQLAlchemy to detect changes
    json_fields = {'skills', 'experience', 'education', 'preferred_locations'}

    for field, value in update_data.items():
        setattr(current_user, field, value)
        # Flag JSON columns as modified so SQLAlchemy includes them in UPDATE
        if field in json_fields:
            flag_modified(current_user, field)

    # Recalculate embedding if profile fields changed
    if any(field in update_data for field in ['headline', 'skills', 'preferred_locations', 'seniority']):
        try:
            profile_embedding = embedding_service.generate_user_embedding(
                headline=current_user.headline,
                skills=current_user.skills,
                preferences=current_user.preferred_locations
            )
            current_user.profile_embedding = profile_embedding
        except Exception as e:
            # Log error but don't fail update
            print(f"Failed to regenerate profile embedding for user {current_user.id}: {e}")

    await db.commit()
    await db.refresh(current_user)

    return current_user
