import asyncio
import logging
from functools import partial

from sqlalchemy import select, func

from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.job import Job
from app.models.swipe import Swipe

logger = logging.getLogger(__name__)


async def update_user_embedding(ctx: dict, user_id: str) -> None:
    """
    ARQ task: re-compute and persist the user's profile embedding.

    Triggered after every right-swipe threshold (5th, then every 3rd).
    Uses asyncio.to_thread() so that synchronous model.encode() calls do
    not block the worker's event loop.
    """
    from app.services.embedding_service import embedding_service

    async with AsyncSessionLocal() as db:
        try:
            # Count active right swipes
            result = await db.execute(
                select(func.count(Swipe.id)).where(
                    Swipe.user_id == user_id,
                    Swipe.direction == "RIGHT",
                    Swipe.is_undone == False,
                )
            )
            right_swipe_count = result.scalar() or 0

            # Get recent right-swiped job embeddings (last 10)
            result = await db.execute(
                select(Job.job_embedding)
                .join(Swipe, Job.id == Swipe.job_id)
                .where(
                    Swipe.user_id == user_id,
                    Swipe.direction == "RIGHT",
                    Swipe.is_undone == False,
                    Job.job_embedding.isnot(None),
                )
                .order_by(Swipe.created_at.desc())
                .limit(10)
            )
            job_embeddings = [row[0] for row in result.all()]

            if not job_embeddings:
                logger.info(f"No job embeddings found for user {user_id}, skipping embedding update")
                return

            db_user = await db.get(User, user_id)
            if not db_user:
                logger.warning(f"User {user_id} not found, skipping embedding update")
                return

            # Generate base embedding if missing
            if db_user.profile_embedding is None:
                experience_text = embedding_service.build_experience_summary(
                    getattr(db_user, "experience", None) or []
                )
                education_text = embedding_service.build_education_summary(
                    getattr(db_user, "education", None) or []
                )
                fn = partial(
                    embedding_service.generate_user_embedding,
                    headline=db_user.headline,
                    skills=db_user.skills,
                    preferences=db_user.preferred_locations,
                    bio=getattr(db_user, "bio", None),
                    experience_text=experience_text,
                    education_text=education_text,
                )
                db_user.profile_embedding = await asyncio.to_thread(fn)

            # Blend profile with swipe history
            fn = partial(
                embedding_service.update_user_embedding_with_history,
                base_embedding=db_user.profile_embedding,
                liked_job_embeddings=job_embeddings,
                alpha=0.3,
            )
            updated_embedding = await asyncio.to_thread(fn)

            db_user.profile_embedding = updated_embedding
            await db.commit()

            logger.info(
                f"Updated embedding for user {user_id} after {right_swipe_count} right swipes"
            )

        except Exception as e:
            logger.error(
                f"Failed to update embedding for user {user_id}: {e}", exc_info=True
            )
            raise  # Let ARQ retry
