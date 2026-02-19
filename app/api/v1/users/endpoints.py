from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import verify_password, get_password_hash
from app.core.cache import invalidate_user_cache
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.user import User as UserSchema, UserUpdate, PasswordChange, PasswordChangeResponse
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

    # Re-fetch from DB so the mutation is tracked by the session
    user = await db.get(User, current_user.id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = user_update.model_dump(exclude_unset=True)

    # JSON/array columns that need explicit flagging for SQLAlchemy to detect changes
    json_fields = {'skills', 'experience', 'education', 'preferred_locations'}

    for field, value in update_data.items():
        setattr(user, field, value)
        if field in json_fields:
            flag_modified(user, field)

    # Recalculate embedding if profile fields changed
    if any(field in update_data for field in ['headline', 'skills', 'preferred_locations', 'seniority', 'bio', 'experience', 'education']):
        try:
            profile_embedding = embedding_service.generate_user_embedding(
                headline=user.headline,
                skills=user.skills,
                preferences=user.preferred_locations,
                bio=user.bio,
                experience_text=embedding_service.build_experience_summary(user.experience or []),
                education_text=embedding_service.build_education_summary(user.education or [])
            )
            user.profile_embedding = profile_embedding
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to regenerate profile embedding for user {user.id}: {e}")

    await db.commit()
    await db.refresh(user)
    await invalidate_user_cache(str(current_user.id))

    return user


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

    # Re-fetch from DB so the mutation is tracked by the session
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = user_update.model_dump(exclude_unset=True)

    # JSON/array columns that need explicit flagging for SQLAlchemy to detect changes
    json_fields = {'skills', 'experience', 'education', 'preferred_locations'}

    for field, value in update_data.items():
        setattr(user, field, value)
        # Flag JSON columns as modified so SQLAlchemy includes them in UPDATE
        if field in json_fields:
            flag_modified(user, field)

    # Recalculate embedding if profile fields changed
    if any(field in update_data for field in ['headline', 'skills', 'preferred_locations', 'seniority', 'bio', 'experience', 'education']):
        try:
            profile_embedding = embedding_service.generate_user_embedding(
                headline=user.headline,
                skills=user.skills,
                preferences=user.preferred_locations,
                bio=user.bio,
                experience_text=embedding_service.build_experience_summary(user.experience or []),
                education_text=embedding_service.build_education_summary(user.education or [])
            )
            user.profile_embedding = profile_embedding
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to regenerate profile embedding for user {user.id}: {e}")

    await db.commit()
    await db.refresh(user)
    await invalidate_user_cache(str(user_id))

    return user


@router.post("/{user_id}/change-password", response_model=PasswordChangeResponse)
async def change_password(
    user_id: uuid.UUID,
    password_data: PasswordChange,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Change the user's password.

    Users can only change their own password.
    Requires the current password for verification and a new password
    that meets the following requirements:
    - At least 8 characters long
    - Contains at least one uppercase letter
    - Contains at least one lowercase letter
    - Contains at least one number
    """
    # Ensure users can only change their own password
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only change your own password"
        )

    # Verify current password (password_hash is stored in cache)
    if not verify_password(password_data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    # Ensure new password is different from current
    if password_data.current_password == password_data.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password"
        )

    # Re-fetch from DB so the mutation is tracked by the session
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = get_password_hash(password_data.new_password)
    await db.commit()
    await invalidate_user_cache(str(user_id))

    return PasswordChangeResponse(
        message="Password changed successfully",
        detail="Your password has been updated. Please use your new password for future logins."
    )
