"""B9.1 — Hiring Outcome Repository"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
import logging

from app.models.mala import HiringOutcome, MatchScore
from app.models.user import User
from app.models.company import Company
from .base import BaseRepository

logger = logging.getLogger(__name__)


class HiringOutcomeRepository(BaseRepository[HiringOutcome]):

    def __init__(self):
        super().__init__(HiringOutcome)

    async def get_by_match_score_id(
        self,
        db: AsyncSession,
        match_score_id: UUID,
    ) -> Optional[HiringOutcome]:
        try:
            stmt = select(HiringOutcome).where(
                HiringOutcome.match_score_id == match_score_id
            )
            result = await db.execute(stmt)
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error("Error fetching HiringOutcome for match_score %s: %s", match_score_id, e)
            raise

    async def get_pending_outcome_requests(
        self,
        db: AsyncSession,
        days_since_decision: int = 90,
    ) -> list[dict]:
        """Return match_scores with decision='avanza', no outcome yet, and decision_at > N days ago.

        Returns list of dicts with match_score, recruiter email, candidate name, job title.
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days_since_decision)

            # Subquery: match_score_ids that already have an outcome
            existing_outcome_ids_stmt = select(HiringOutcome.match_score_id)
            existing_result = await db.execute(existing_outcome_ids_stmt)
            existing_ids = {row[0] for row in existing_result.fetchall()}

            stmt = (
                select(MatchScore, User)
                .join(User, User.id == MatchScore.user_id)
                .where(
                    MatchScore.recruiter_decision == "avanza",
                    MatchScore.decision_at <= cutoff,
                )
            )
            if existing_ids:
                stmt = stmt.where(MatchScore.id.notin_(existing_ids))

            result = await db.execute(stmt)
            rows = result.all()

            records = []
            for match_score, candidate in rows:
                records.append({
                    "match_score_id": match_score.id,
                    "job_id": match_score.job_id,
                    "candidate_name": candidate.full_name or candidate.email,
                    "decision_at": match_score.decision_at,
                })
            return records
        except SQLAlchemyError as e:
            logger.error("Error fetching pending outcome requests: %s", e)
            raise

    async def get_all_with_features(self, db: AsyncSession) -> list[dict]:
        """Return all completed hiring outcomes joined with their PUC vectors and match features.

        Used by the predictive model retraining task (B9.2).
        """
        try:
            from app.models.mala import CandidatePUCProfile

            stmt = (
                select(HiringOutcome, MatchScore, CandidatePUCProfile)
                .join(MatchScore, MatchScore.id == HiringOutcome.match_score_id)
                .outerjoin(
                    CandidatePUCProfile,
                    CandidatePUCProfile.user_id == HiringOutcome.user_id,
                )
                .where(HiringOutcome.was_successful_hire.isnot(None))
            )
            result = await db.execute(stmt)
            rows = result.all()

            records = []
            for outcome, match_score, puc in rows:
                puc_vector = list(puc.puc_vector) if puc and puc.puc_vector is not None else [0.0] * 47
                match_features = [
                    match_score.hard_match_score or 0.0,
                    match_score.soft_match_score or 0.0,
                    match_score.predictive_match_score or 0.0,
                    match_score.skills_coverage or 0.0,
                    match_score.experience_score or 0.0,
                    match_score.education_score or 0.0,
                    match_score.language_score or 0.0,
                    match_score.big_five_fit or 0.0,
                    match_score.mcclelland_culture_fit or 0.0,
                    match_score.appraisal_values_fit or 0.0,
                    match_score.career_narrative_fit or 0.0,
                ]
                records.append({
                    "outcome_id": outcome.id,
                    "puc_vector": puc_vector,
                    "match_features": match_features,
                    "was_successful_hire": outcome.was_successful_hire,
                    "performance_6m": outcome.performance_6m,
                    "retention_6m": outcome.retention_6m,
                })
            return records
        except SQLAlchemyError as e:
            logger.error("Error fetching outcomes with features: %s", e)
            raise
