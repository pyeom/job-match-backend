from __future__ import annotations
from typing import Optional
from uuid import UUID
from sqlalchemy import select, func, nulls_last
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
import logging

from app.models.mala import MatchScore
from .base import BaseRepository

logger = logging.getLogger(__name__)


class MatchScoreRepository(BaseRepository[MatchScore]):

    def __init__(self):
        super().__init__(MatchScore)

    async def get_by_user_and_job(
        self,
        db: AsyncSession,
        user_id: UUID,
        job_id: UUID,
    ) -> Optional[MatchScore]:
        try:
            stmt = select(MatchScore).where(
                MatchScore.user_id == user_id,
                MatchScore.job_id == job_id,
            )
            result = await db.execute(stmt)
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching MatchScore for user {user_id} job {job_id}: {e}")
            raise

    async def get_ranked_for_job(
        self,
        db: AsyncSession,
        job_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[MatchScore], int]:
        try:
            stmt = (
                select(MatchScore)
                .where(MatchScore.job_id == job_id)
                .order_by(nulls_last(MatchScore.final_effective_score.desc()))
                .offset(skip)
                .limit(limit)
            )
            result = await db.execute(stmt)
            items = list(result.scalars().all())

            count_stmt = (
                select(func.count())
                .select_from(MatchScore)
                .where(MatchScore.job_id == job_id)
            )
            count_result = await db.execute(count_stmt)
            total = count_result.scalar_one()

            return items, total
        except SQLAlchemyError as e:
            logger.error(f"Error fetching ranked MatchScores for job {job_id}: {e}")
            raise

    async def upsert(
        self,
        db: AsyncSession,
        user_id: UUID,
        job_id: UUID,
        data: dict,
    ) -> MatchScore:
        try:
            existing = await self.get_by_user_and_job(db, user_id, job_id)
            if existing:
                return await self.update(db, existing, data)
            data["user_id"] = user_id
            data["job_id"] = job_id
            return await self.create(db, data)
        except SQLAlchemyError as e:
            logger.error(f"Error upserting MatchScore for user {user_id} job {job_id}: {e}")
            raise
