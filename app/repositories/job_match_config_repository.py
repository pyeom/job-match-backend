from __future__ import annotations
from typing import Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
import logging

from app.models.mala import JobMatchConfig
from .base import BaseRepository

logger = logging.getLogger(__name__)


class JobMatchConfigRepository(BaseRepository[JobMatchConfig]):

    def __init__(self):
        super().__init__(JobMatchConfig)

    async def get_by_job_id(
        self,
        db: AsyncSession,
        job_id: UUID,
    ) -> Optional[JobMatchConfig]:
        try:
            stmt = select(JobMatchConfig).where(JobMatchConfig.job_id == job_id)
            result = await db.execute(stmt)
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching JobMatchConfig for job {job_id}: {e}")
            raise

    async def upsert(
        self,
        db: AsyncSession,
        job_id: UUID,
        data: dict,
    ) -> JobMatchConfig:
        try:
            existing = await self.get_by_job_id(db, job_id)
            if existing:
                return await self.update(db, existing, data)
            data["job_id"] = job_id
            return await self.create(db, data)
        except SQLAlchemyError as e:
            logger.error(f"Error upserting JobMatchConfig for job {job_id}: {e}")
            raise
