import logging

import httpx
from arq.connections import RedisSettings

from app.core.config import settings
from app.tasks.embedding_tasks import update_user_embedding
from app.tasks.notification_tasks import deliver_push_notification
from app.tasks.document_tasks import parse_resume_and_update_profile
from app.tasks.elasticsearch_tasks import reindex_all_jobs

logger = logging.getLogger(__name__)


async def on_startup(ctx: dict) -> None:
    ctx["http_client"] = httpx.AsyncClient(timeout=10.0)
    logger.info(
        "ARQ worker started. Functions: update_user_embedding, "
        "deliver_push_notification, parse_resume_and_update_profile, "
        "reindex_all_jobs"
    )


async def on_shutdown(ctx: dict) -> None:
    http_client: httpx.AsyncClient | None = ctx.get("http_client")
    if http_client is not None:
        await http_client.aclose()
    logger.info("ARQ worker shut down. HTTP client closed.")


class WorkerSettings:
    functions = [
        update_user_embedding,
        deliver_push_notification,
        parse_resume_and_update_profile,
        reindex_all_jobs,
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10
    job_timeout = 300   # 5 minutes max per task
    max_tries = 3       # Retry up to 3 times on failure
    on_startup = on_startup
    on_shutdown = on_shutdown
