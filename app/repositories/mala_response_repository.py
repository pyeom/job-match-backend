from __future__ import annotations
from typing import Optional
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
import logging

from app.models.mala import CandidateMalaResponse
from .base import BaseRepository

logger = logging.getLogger(__name__)


class MalaResponseRepository(BaseRepository[CandidateMalaResponse]):

    def __init__(self):
        super().__init__(CandidateMalaResponse)

    async def get_by_user_id(
        self,
        db: AsyncSession,
        user_id: UUID,
    ) -> list[CandidateMalaResponse]:
        try:
            stmt = select(CandidateMalaResponse).where(CandidateMalaResponse.user_id == user_id)
            result = await db.execute(stmt)
            return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Error fetching CandidateMalaResponse for user {user_id}: {e}")
            raise

    async def get_by_user_and_question(
        self,
        db: AsyncSession,
        user_id: UUID,
        question_code: str,
    ) -> Optional[CandidateMalaResponse]:
        try:
            stmt = select(CandidateMalaResponse).where(
                CandidateMalaResponse.user_id == user_id,
                CandidateMalaResponse.question_code == question_code,
            )
            result = await db.execute(stmt)
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(
                f"Error fetching CandidateMalaResponse for user {user_id} question {question_code}: {e}"
            )
            raise

    async def upsert(
        self,
        db: AsyncSession,
        user_id: UUID,
        question_code: str,
        data: dict,
    ) -> CandidateMalaResponse:
        try:
            existing = await self.get_by_user_and_question(db, user_id, question_code)
            if existing:
                return await self.update(db, existing, data)
            data["user_id"] = user_id
            data["question_code"] = question_code
            return await self.create(db, data)
        except SQLAlchemyError as e:
            logger.error(
                f"Error upserting CandidateMalaResponse for user {user_id} question {question_code}: {e}"
            )
            raise

    async def get_answered_count(
        self,
        db: AsyncSession,
        user_id: UUID,
    ) -> int:
        try:
            stmt = (
                select(func.count())
                .select_from(CandidateMalaResponse)
                .where(CandidateMalaResponse.user_id == user_id)
            )
            result = await db.execute(stmt)
            return result.scalar_one()
        except SQLAlchemyError as e:
            logger.error(f"Error counting CandidateMalaResponse for user {user_id}: {e}")
            raise

    async def count_completed(self, db: AsyncSession, user_id: UUID) -> int:
        return await self.get_answered_count(db, user_id)

    async def update_status(
        self,
        db: AsyncSession,
        user_id: UUID,
        question_code: str,
        status: str,
        error: Optional[str] = None,
    ) -> Optional[CandidateMalaResponse]:
        try:
            existing = await self.get_by_user_and_question(db, user_id, question_code)
            if existing is None:
                return None
            data: dict = {"processing_status": status}
            if error is not None:
                data["processing_error"] = error
            return await self.update(db, existing, data)
        except SQLAlchemyError as e:
            logger.error(
                f"Error updating status for user {user_id} question {question_code}: {e}"
            )
            raise

    async def save_layer_results(
        self,
        db: AsyncSession,
        user_id: UUID,
        question_code: str,
        layer_data: dict,
    ) -> Optional[CandidateMalaResponse]:
        try:
            existing = await self.get_by_user_and_question(db, user_id, question_code)
            if existing is None:
                return None
            return await self.update(db, existing, layer_data)
        except SQLAlchemyError as e:
            logger.error(
                f"Error saving layer results for user {user_id} question {question_code}: {e}"
            )
            raise
