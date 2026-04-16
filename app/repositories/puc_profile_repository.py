from __future__ import annotations
from typing import Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
import logging

from app.models.mala import CandidatePUCProfile
from .base import BaseRepository

logger = logging.getLogger(__name__)


class PUCProfileRepository(BaseRepository[CandidatePUCProfile]):

    def __init__(self):
        super().__init__(CandidatePUCProfile)

    async def get_by_user_id(
        self,
        db: AsyncSession,
        user_id: UUID,
    ) -> Optional[CandidatePUCProfile]:
        try:
            stmt = select(CandidatePUCProfile).where(CandidatePUCProfile.user_id == user_id)
            result = await db.execute(stmt)
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching CandidatePUCProfile for user {user_id}: {e}")
            raise

    async def upsert(
        self,
        db: AsyncSession,
        user_id: UUID,
        data: dict,
    ) -> CandidatePUCProfile:
        try:
            existing = await self.get_by_user_id(db, user_id)
            if existing:
                return await self.update(db, existing, data)
            data["user_id"] = user_id
            return await self.create(db, data)
        except SQLAlchemyError as e:
            logger.error(f"Error upserting CandidatePUCProfile for user {user_id}: {e}")
            raise
