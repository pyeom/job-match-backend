"""ARQ task: bulk reindex all jobs into Elasticsearch.

Triggered once at startup when the index is freshly created, or can be
run manually to rebuild the index after schema changes.
"""
import logging

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.job import Job
from app.services.elasticsearch_service import elasticsearch_service

logger = logging.getLogger(__name__)

BATCH_SIZE = 100


async def reindex_all_jobs(ctx: dict) -> dict:
    """Bulk index all jobs with embeddings into Elasticsearch."""
    logger.info("Starting bulk Elasticsearch reindex...")

    indexed = 0
    skipped = 0
    errors = 0
    offset = 0

    async with AsyncSessionLocal() as db:
        while True:
            result = await db.execute(
                select(Job)
                .where(Job.job_embedding.isnot(None))
                .order_by(Job.created_at)
                .offset(offset)
                .limit(BATCH_SIZE)
            )
            jobs = result.scalars().all()

            if not jobs:
                break

            for job in jobs:
                try:
                    await elasticsearch_service.index_job(job)
                    indexed += 1
                except Exception as exc:
                    logger.error("Failed to index job %s: %s", job.id, exc)
                    errors += 1

            offset += BATCH_SIZE
            logger.info("Reindex progress: %d indexed so far...", indexed)

    logger.info(
        "Bulk reindex complete: indexed=%d skipped=%d errors=%d",
        indexed,
        skipped,
        errors,
    )
    return {"indexed": indexed, "skipped": skipped, "errors": errors}
