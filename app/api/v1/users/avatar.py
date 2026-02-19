"""
Avatar upload and management endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.avatar import AvatarUploadResponse, AvatarDeleteResponse
from app.core.cache import invalidate_user_cache
from app.services.image_service import image_service
from app.services.storage_service import storage_service
from app.services.rate_limit_service import rate_limit_service


router = APIRouter()


@router.post("/avatar", response_model=AvatarUploadResponse, status_code=status.HTTP_200_OK)
async def upload_avatar(
    file: UploadFile = File(..., description="Avatar image file (JPEG, PNG, or WebP, max 5MB)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload or update user avatar.

    Accepts JPEG, PNG, or WebP images up to 5MB.
    Images are automatically:
    - Resized to 512x512 (standard) and 256x256 (thumbnail)
    - Converted to WebP format for optimization
    - Stored with unique filenames

    Rate limit: 10 uploads per hour per user.
    """
    # Check rate limit
    is_allowed, retry_after = rate_limit_service.check_rate_limit(
        user_id=current_user.id,
        max_requests=10,
        window_seconds=3600  # 1 hour
    )

    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Maximum 10 uploads per hour. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)}
        )

    # Validate file size from Content-Length header
    # This is optional but provides early rejection for large files
    # Note: The actual validation happens in image_service.validate_image()

    # Validate image file
    await image_service.validate_image(file)

    # Process image (resize and convert to WebP)
    try:
        standard_bytes, thumbnail_bytes = await image_service.process_avatar(file)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process image: {str(e)}"
        )

    # Delete old avatars if they exist
    if current_user.avatar_url:
        old_filename = storage_service.extract_filename_from_url(current_user.avatar_url)
        if old_filename:
            await storage_service.delete_avatar(current_user.id, old_filename)

    if current_user.avatar_thumbnail_url:
        old_thumbnail = storage_service.extract_filename_from_url(current_user.avatar_thumbnail_url)
        if old_thumbnail:
            await storage_service.delete_avatar(current_user.id, old_thumbnail)

    # Save new avatars
    try:
        avatar_url, _ = await storage_service.save_avatar(
            user_id=current_user.id,
            file_content=standard_bytes,
            size_suffix="standard"
        )

        thumbnail_url, _ = await storage_service.save_avatar(
            user_id=current_user.id,
            file_content=thumbnail_bytes,
            size_suffix="thumbnail"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save avatar: {str(e)}"
        )

    # Re-fetch from DB so the mutation is tracked by the session
    user = await db.get(User, current_user.id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.avatar_url = avatar_url
    user.avatar_thumbnail_url = thumbnail_url

    try:
        await db.commit()
        await db.refresh(user)
    except Exception as e:
        # Rollback database changes
        await db.rollback()

        # Try to clean up uploaded files
        avatar_filename = storage_service.extract_filename_from_url(avatar_url)
        thumbnail_filename = storage_service.extract_filename_from_url(thumbnail_url)

        if avatar_filename:
            await storage_service.delete_avatar(current_user.id, avatar_filename)
        if thumbnail_filename:
            await storage_service.delete_avatar(current_user.id, thumbnail_filename)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user record: {str(e)}"
        )

    await invalidate_user_cache(str(current_user.id))

    # Record successful request for rate limiting
    rate_limit_service.record_request(current_user.id)

    return AvatarUploadResponse(
        avatar_url=avatar_url,
        avatar_thumbnail_url=thumbnail_url,
        message="Avatar uploaded successfully"
    )


@router.delete("/avatar", response_model=AvatarDeleteResponse, status_code=status.HTTP_200_OK)
async def delete_avatar(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete current user's avatar.

    Removes both standard and thumbnail versions of the avatar
    and sets the database fields to NULL.
    """
    if not current_user.avatar_url and not current_user.avatar_thumbnail_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No avatar found for this user"
        )

    # Delete files from storage
    deleted_files = []

    if current_user.avatar_url:
        filename = storage_service.extract_filename_from_url(current_user.avatar_url)
        if filename:
            success = await storage_service.delete_avatar(current_user.id, filename)
            if success:
                deleted_files.append("standard")

    if current_user.avatar_thumbnail_url:
        filename = storage_service.extract_filename_from_url(current_user.avatar_thumbnail_url)
        if filename:
            success = await storage_service.delete_avatar(current_user.id, filename)
            if success:
                deleted_files.append("thumbnail")

    # Re-fetch from DB so the mutation is tracked by the session
    user = await db.get(User, current_user.id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.avatar_url = None
    user.avatar_thumbnail_url = None

    try:
        await db.commit()
        await db.refresh(user)
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user record: {str(e)}"
        )

    await invalidate_user_cache(str(current_user.id))

    return AvatarDeleteResponse(
        message=f"Avatar deleted successfully ({', '.join(deleted_files)} removed)"
        if deleted_files
        else "Avatar deleted successfully"
    )
