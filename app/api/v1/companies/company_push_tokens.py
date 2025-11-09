"""
Company push token endpoints for registering and managing push notification tokens.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List
import logging

from app.core.database import get_db
from app.api.deps import get_company_user_with_verification
from app.models.user import User
from app.repositories.push_token_repository import PushTokenRepository
from app.schemas.push_token import (
    PushTokenCreate,
    PushTokenResponse,
    PushTokenDeleteResponse
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{company_id}/push-tokens", response_model=PushTokenResponse, status_code=status.HTTP_201_CREATED)
async def register_company_push_token(
    company_id: UUID,
    token_data: PushTokenCreate,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """
    Register a push notification token for a company.

    This endpoint is idempotent - if the token already exists, it will be
    reactivated and updated instead of creating a duplicate.

    **Authorization**: Company users can only register tokens for their own company.

    Args:
        company_id: UUID of the company
        token_data: Push token data (token, platform, device_name)
        current_user: Current authenticated company user
        db: Database session

    Returns:
        The created or updated push token
    """
    # Verify company user can only register tokens for their own company
    if current_user.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only register push tokens for your own company"
        )

    push_token_repo = PushTokenRepository()

    try:
        push_token = await push_token_repo.create_or_update(
            db=db,
            token=token_data.token,
            platform=token_data.platform,
            company_id=company_id,
            device_name=token_data.device_name
        )

        await db.commit()
        await db.refresh(push_token)

        logger.info(f"Registered push token for company {company_id}: {token_data.token[:20]}...")

        return push_token

    except Exception as e:
        await db.rollback()
        logger.error(f"Error registering company push token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register push token"
        )


@router.get("/{company_id}/push-tokens", response_model=List[PushTokenResponse])
async def get_company_push_tokens(
    company_id: UUID,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all active push tokens for a company.

    **Authorization**: Company users can only view tokens for their own company.

    Args:
        company_id: UUID of the company
        current_user: Current authenticated company user
        db: Database session

    Returns:
        List of active push tokens
    """
    # Verify company user can only view tokens for their own company
    if current_user.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view push tokens for your own company"
        )

    push_token_repo = PushTokenRepository()
    tokens = await push_token_repo.get_active_tokens_for_company(db, company_id)

    return tokens


@router.delete("/{company_id}/push-tokens/{token}", response_model=PushTokenDeleteResponse)
async def delete_company_push_token(
    company_id: UUID,
    token: str,
    current_user: User = Depends(get_company_user_with_verification),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a push notification token for a company.

    This is useful when the user logs out or uninstalls the app.

    **Authorization**: Company users can only delete tokens for their own company.

    Args:
        company_id: UUID of the company
        token: The Expo push token to delete
        current_user: Current authenticated company user
        db: Database session

    Returns:
        Success response
    """
    # Verify company user can only delete tokens for their own company
    if current_user.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete push tokens for your own company"
        )

    push_token_repo = PushTokenRepository()

    try:
        deleted = await push_token_repo.delete_token(
            db=db,
            token=token,
            company_id=company_id
        )

        await db.commit()

        if deleted:
            logger.info(f"Deleted push token for company {company_id}: {token[:20]}...")
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
        logger.error(f"Error deleting company push token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete push token"
        )
