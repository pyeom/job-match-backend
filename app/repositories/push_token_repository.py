"""
Repository for push token database operations.
"""

from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from datetime import datetime
import logging

from app.models.push_token import PushToken, PushTokenPlatform
from .base import BaseRepository

logger = logging.getLogger(__name__)


class PushTokenRepository(BaseRepository[PushToken]):
    """Repository for push token operations."""

    def __init__(self):
        super().__init__(PushToken)

    async def create_or_update(
        self,
        db: AsyncSession,
        token: str,
        platform: str,
        user_id: Optional[UUID] = None,
        company_id: Optional[UUID] = None,
        device_name: Optional[str] = None
    ) -> PushToken:
        """
        Create or update a push token (idempotent operation).

        If token already exists, update it and mark as active.
        Otherwise, create new token.

        Args:
            db: Database session
            token: Expo push token
            platform: Platform (ios, android, web)
            user_id: UUID of user (if jobseeker)
            company_id: UUID of company (if company user)
            device_name: Optional device name

        Returns:
            PushToken instance
        """
        # Check if token exists
        stmt = select(PushToken).where(PushToken.token == token)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing token
            existing.is_active = True
            existing.last_used_at = datetime.utcnow()
            if device_name:
                existing.device_name = device_name
            # Update owner if changed (device re-login scenario)
            if user_id:
                existing.user_id = user_id
                existing.company_id = None
            elif company_id:
                existing.company_id = company_id
                existing.user_id = None

            return existing
        else:
            # Create new token
            push_token = PushToken(
                token=token,
                platform=platform,
                user_id=user_id,
                company_id=company_id,
                device_name=device_name,
                is_active=True
            )
            db.add(push_token)
            await db.flush()
            return push_token

    async def get_active_tokens_for_user(
        self,
        db: AsyncSession,
        user_id: UUID
    ) -> List[PushToken]:
        """
        Get all active push tokens for a user.

        Args:
            db: Database session
            user_id: UUID of the user

        Returns:
            List of active PushToken instances
        """
        stmt = select(PushToken).where(
            PushToken.user_id == user_id,
            PushToken.is_active == True
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_active_tokens_for_company(
        self,
        db: AsyncSession,
        company_id: UUID
    ) -> List[PushToken]:
        """
        Get all active push tokens for a company.

        Args:
            db: Database session
            company_id: UUID of the company

        Returns:
            List of active PushToken instances
        """
        stmt = select(PushToken).where(
            PushToken.company_id == company_id,
            PushToken.is_active == True
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def deactivate_token(
        self,
        db: AsyncSession,
        token: str
    ) -> bool:
        """
        Deactivate a push token.

        Args:
            db: Database session
            token: Expo push token to deactivate

        Returns:
            True if token was found and deactivated, False otherwise
        """
        stmt = update(PushToken).where(
            PushToken.token == token
        ).values(
            is_active=False
        ).returning(PushToken.id)

        result = await db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def delete_token(
        self,
        db: AsyncSession,
        token: str,
        user_id: Optional[UUID] = None,
        company_id: Optional[UUID] = None
    ) -> bool:
        """
        Delete a push token (with ownership check).

        Args:
            db: Database session
            token: Expo push token to delete
            user_id: Optional user_id for ownership check
            company_id: Optional company_id for ownership check

        Returns:
            True if deleted, False if not found or unauthorized
        """
        stmt = delete(PushToken).where(PushToken.token == token)

        # Add ownership filter
        if user_id:
            stmt = stmt.where(PushToken.user_id == user_id)
        elif company_id:
            stmt = stmt.where(PushToken.company_id == company_id)
        else:
            # No ownership specified - delete anyway (admin operation)
            pass

        result = await db.execute(stmt)
        return result.rowcount > 0

    async def mark_token_used(
        self,
        db: AsyncSession,
        token: str
    ):
        """
        Update last_used_at timestamp for a token.

        Args:
            db: Database session
            token: Expo push token
        """
        stmt = update(PushToken).where(
            PushToken.token == token
        ).values(
            last_used_at=datetime.utcnow()
        )
        await db.execute(stmt)
