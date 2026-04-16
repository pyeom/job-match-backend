"""
B7.4 — Match Score arq tasks

Three background tasks:
  - recalculate_match_scores_for_user : re-score all active applications for a user
  - recalculate_match_scores_for_job  : re-score all applicants for a job
  - generate_initial_ranking          : compute scores for all applicants of a new job
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select

from app.core.database import get_db
from app.models.application import Application
from app.models.mala import MatchScore

logger = logging.getLogger(__name__)


async def recalculate_match_scores_for_user(ctx: dict, user_id: str) -> dict:
    """Re-compute match scores for all active applications belonging to a user.

    If a recomputed score improves by more than 5 points, enqueue a company
    notification so the recruiter is alerted.

    Args:
        ctx:     arq worker context dict.
        user_id: String UUID of the job-seeker.

    Returns:
        Summary dict with status and count of jobs processed.
    """
    user_uuid = UUID(user_id)

    async for db in get_db():
        try:
            from app.services.match_score_service import compute_final_score

            # Find all active applications for this user
            stmt = select(Application).where(
                Application.user_id == user_uuid,
                Application.status != "REJECTED",
            )
            result = await db.execute(stmt)
            applications = list(result.scalars().all())

            processed = 0
            for app in applications:
                try:
                    # Read existing score before recomputation
                    existing_stmt = select(MatchScore).where(
                        MatchScore.user_id == user_uuid,
                        MatchScore.job_id == app.job_id,
                    )
                    existing_result = await db.execute(existing_stmt)
                    existing_score = existing_result.scalar_one_or_none()
                    old_effective = existing_score.final_effective_score if existing_score else 0.0

                    new_result = await compute_final_score(db, user_uuid, app.job_id)
                    processed += 1

                    # Enqueue notification if score improved significantly
                    if new_result.final_effective_score > old_effective + 5:
                        try:
                            from app.core.arq import get_arq_pool
                            pool = await get_arq_pool()
                            await pool.enqueue_job(
                                "deliver_push_notification",
                                user_id=str(user_id),
                                job_id=str(app.job_id),
                                event="score_improved",
                            )
                        except Exception as notify_err:
                            logger.warning(
                                "Could not enqueue score-improved notification for user %s job %s: %s",
                                user_id, app.job_id, notify_err,
                            )

                except Exception as score_err:
                    logger.error(
                        "Failed to compute score for user %s job %s: %s",
                        user_id, app.job_id, score_err, exc_info=True,
                    )

            logger.info(
                "recalculate_match_scores_for_user: user=%s, processed=%d applications",
                user_id, processed,
            )
            return {"status": "completed", "user_id": user_id, "processed": processed}

        except Exception as exc:
            logger.error(
                "recalculate_match_scores_for_user failed for user %s: %s",
                user_id, exc, exc_info=True,
            )
            raise


async def recalculate_match_scores_for_job(ctx: dict, job_id: str) -> dict:
    """Re-compute match scores for all applicants of a specific job.

    Args:
        ctx:    arq worker context dict.
        job_id: String UUID of the job.

    Returns:
        Summary dict with status and count of candidates processed.
    """
    job_uuid = UUID(job_id)

    async for db in get_db():
        try:
            from app.services.match_score_service import compute_final_score

            # Find all applications for this job
            stmt = select(Application).where(Application.job_id == job_uuid)
            result = await db.execute(stmt)
            applications = list(result.scalars().all())

            processed = 0
            for app in applications:
                try:
                    await compute_final_score(db, app.user_id, job_uuid)
                    processed += 1
                except Exception as score_err:
                    logger.error(
                        "Failed to compute score for job %s user %s: %s",
                        job_id, app.user_id, score_err, exc_info=True,
                    )

            logger.info(
                "recalculate_match_scores_for_job: job=%s, processed=%d candidates",
                job_id, processed,
            )
            return {"status": "completed", "job_id": job_id, "processed": processed}

        except Exception as exc:
            logger.error(
                "recalculate_match_scores_for_job failed for job %s: %s",
                job_id, exc, exc_info=True,
            )
            raise


async def generate_initial_ranking(ctx: dict, job_id: str) -> dict:
    """Generate the initial candidate ranking for a newly published job.

    Finds all active applications, computes scores, and effectively builds
    the first ranking for the company's recruiter dashboard.

    Args:
        ctx:    arq worker context dict.
        job_id: String UUID of the job.

    Returns:
        Summary dict with status, count processed, and count passing hard filter.
    """
    job_uuid = UUID(job_id)

    async for db in get_db():
        try:
            from app.services.match_score_service import compute_final_score

            # Find all active (non-rejected) applications for this job
            stmt = select(Application).where(
                Application.job_id == job_uuid,
                Application.status != "REJECTED",
            )
            result = await db.execute(stmt)
            applications = list(result.scalars().all())

            processed = 0
            passed_hard_filter = 0

            for app in applications:
                try:
                    score_result = await compute_final_score(db, app.user_id, job_uuid)
                    processed += 1
                    if score_result.hard_match.passed_filter:
                        passed_hard_filter += 1
                except Exception as score_err:
                    logger.error(
                        "generate_initial_ranking: failed for job %s user %s: %s",
                        job_id, app.user_id, score_err, exc_info=True,
                    )

            logger.info(
                "generate_initial_ranking: job=%s, processed=%d, passed_hard_filter=%d",
                job_id, processed, passed_hard_filter,
            )
            return {
                "status": "completed",
                "job_id": job_id,
                "processed": processed,
                "passed_hard_filter": passed_hard_filter,
            }

        except Exception as exc:
            logger.error(
                "generate_initial_ranking failed for job %s: %s",
                job_id, exc, exc_info=True,
            )
            raise
