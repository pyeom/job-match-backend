"""
User push token endpoints for registering and managing push notification tokens.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List
import logging

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User, UserRole
from app.repositories.push_token_repository import PushTokenRepository
from app.schemas.push_token import (
    PushTokenCreate,
    PushTokenResponse,
    PushTokenDeleteResponse
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{user_id}/push-tokens", response_model=PushTokenResponse, status_code=status.HTTP_201_CREATED)
async def register_push_token(
    user_id: UUID,
    token_data: PushTokenCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Register a push notification token for a user.

    This endpoint is idempotent - if the token already exists, it will be
    reactivated and updated instead of creating a duplicate.

    **Authorization**: Users can only register tokens for themselves.

    Args:
        user_id: UUID of the user
        token_data: Push token data (token, platform, device_name)
        current_user: Current authenticated user
        db: Database session

    Returns:
        The created or updated push token
    """
    # Verify user can only register tokens for themselves
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only register push tokens for yourself"
        )

    # Verify user is a jobseeker (not a company user)
    if current_user.role == UserRole.COMPANY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company users should use the company push token endpoints"
        )

    push_token_repo = PushTokenRepository()

    try:
        push_token = await push_token_repo.create_or_update(
            db=db,
            token=token_data.token,
            platform=token_data.platform,
            user_id=user_id,
            device_name=token_data.device_name
        )

        await db.commit()
        await db.refresh(push_token)

        logger.info(f"Registered push token for user {user_id}: {token_data.token[:20]}...")

        return push_token

    except Exception as e:
        await db.rollback()
        logger.error(f"Error registering push token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register push token"
        )


@router.get("/{user_id}/push-tokens", response_model=List[PushTokenResponse])
async def get_user_push_tokens(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all active push tokens for a user.

    **Authorization**: Users can only view their own tokens.

    Args:
        user_id: UUID of the user
        current_user: Current authenticated user
        db: Database session

    Returns:
        List of active push tokens
    """
    # Verify user can only view their own tokens
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own push tokens"
        )

    push_token_repo = PushTokenRepository()
    tokens = await push_token_repo.get_active_tokens_for_user(db, user_id)

    return tokens


@router.delete("/{user_id}/push-tokens/{token}", response_model=PushTokenDeleteResponse)
async def delete_push_token(
    user_id: UUID,
    token: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a push notification token for a user.

    This is useful when the user logs out or uninstalls the app.

    **Authorization**: Users can only delete their own tokens.

    Args:
        user_id: UUID of the user
        token: The Expo push token to delete
        current_user: Current authenticated user
        db: Database session

    Returns:
        Success response
    """
    # Verify user can only delete their own tokens
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own push tokens"
        )

    push_token_repo = PushTokenRepository()

    try:
        deleted = await push_token_repo.delete_token(
            db=db,
            token=token,
            user_id=user_id
        )

        await db.commit()

        if deleted:
            logger.info(f"Deleted push token for user {user_id}: {token[:20]}...")
            return PushTokenDeleteResponse(
                success=True,
                message="Push token deleted successfully"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Push token not found"
            )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting push token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete push token"
        )
