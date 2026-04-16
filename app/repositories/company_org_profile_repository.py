from __future__ import annotations
from typing import Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
import logging

from app.models.mala import CompanyOrgProfile
from .base import BaseRepository

logger = logging.getLogger(__name__)


class CompanyOrgProfileRepository(BaseRepository[CompanyOrgProfile]):

    def __init__(self):
        super().__init__(CompanyOrgProfile)

    async def get_by_company_id(
        self,
        db: AsyncSession,
        company_id: UUID,
    ) -> Optional[CompanyOrgProfile]:
        try:
            stmt = select(CompanyOrgProfile).where(CompanyOrgProfile.company_id == company_id)
            result = await db.execute(stmt)
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching CompanyOrgProfile for company {company_id}: {e}")
            raise

    async def upsert(
        self,
        db: AsyncSession,
        company_id: UUID,
        data: dict,
    ) -> CompanyOrgProfile:
        try:
            existing = await self.get_by_company_id(db, company_id)
            if existing:
                return await self.update(db, existing, data)
            data["company_id"] = company_id
            return await self.create(db, data)
        except SQLAlchemyError as e:
            logger.error(f"Error upserting CompanyOrgProfile for company {company_id}: {e}")
            raise
