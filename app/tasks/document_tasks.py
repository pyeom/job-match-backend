import asyncio
import hashlib
import logging
from functools import partial

from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def parse_resume_and_update_profile(
    ctx: dict,
    user_id: str,
    extracted_text: str,
    document_id: str,
) -> None:
    """
    ARQ task: parse resume text with SpaCy NLP and update the user's profile.

    CPU-heavy SpaCy inference is wrapped in asyncio.to_thread() to avoid
    blocking the worker's event loop.
    Raises on failure so ARQ will retry.
    """
    from app.services.resume_parser_service import resume_parser_service
    from app.services.user_service import user_service

    if not extracted_text:
        logger.warning(
            f"No extracted text for document {document_id}, skipping resume parse"
        )
        return

    # ------------------------------------------------------------------
    # Optimization 6: deduplication lock — skip if a concurrent parse of
    # the same text is already in flight (same text hash).
    # ------------------------------------------------------------------
    from app.core.cache import get_redis

    text_hash = hashlib.sha256(extracted_text.encode()).hexdigest()[:16]
    dedup_key = f"resume_parse_inflight:{text_hash}"
    redis = await get_redis()

    lock_acquired = False
    try:
        result = await redis.set(dedup_key, "1", nx=True, ex=300)
        if result is None:
            # Key already existed — another worker is handling this text
            logger.info(
                "Duplicate resume parse skipped for document %s (key %s already held)",
                document_id,
                dedup_key,
            )
            return
        lock_acquired = True
    except Exception as exc:
        # Redis failure must not prevent parsing
        logger.warning("Dedup lock check failed (continuing anyway): %s", exc)

    try:
        async with AsyncSessionLocal() as db:
            try:
                # SpaCy inference is CPU-bound — offload to thread pool
                fn = partial(
                    resume_parser_service.parse_resume,
                    resume_text=extracted_text,
                    document_id=str(document_id),
                )
                parsed_data = await asyncio.to_thread(fn)

                logger.info(
                    f"Parsed resume {document_id} for user {user_id}: "
                    f"confidence={parsed_data.confidence_score:.2f}, "
                    f"skills={len(parsed_data.skills.all_skills)}"
                )

                if parsed_data.confidence_score >= 0.3:
                    from app.models.user import User

                    db_user = await db.get(User, user_id)
                    if not db_user:
                        logger.warning(f"User {user_id} not found, skipping profile update")
                        return

                    updated_user, fields_updated = await user_service.update_profile_from_resume(
                        db=db,
                        user=db_user,
                        parsed_data=parsed_data,
                    )
                    if fields_updated:
                        logger.info(
                            f"Auto-updated profile for user {user_id} from resume {document_id}. "
                            f"Fields: {fields_updated}"
                        )
                else:
                    logger.info(
                        f"Skipping profile update for user {user_id}: "
                        f"confidence too low ({parsed_data.confidence_score:.2f})"
                    )

            except Exception as e:
                logger.error(
                    f"Failed to parse resume {document_id} for user {user_id}: {e}",
                    exc_info=True,
                )
                raise  # Let ARQ retry
    finally:
        # Release the dedup lock regardless of success or failure
        if lock_acquired:
            try:
                await redis.delete(dedup_key)
            except Exception as exc:
                logger.warning("Failed to release dedup lock %s: %s", dedup_key, exc)
