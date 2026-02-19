import logging

from arq.connections import RedisSettings

from app.core.config import settings
from app.tasks.embedding_tasks import update_user_embedding
from app.tasks.notification_tasks import deliver_push_notification
from app.tasks.document_tasks import parse_resume_and_update_profile

logger = logging.getLogger(__name__)


async def on_startup(ctx: dict) -> None:
    logger.info(
        "ARQ worker started. Functions: update_user_embedding, "
        "deliver_push_notification, parse_resume_and_update_profile"
    )


class WorkerSettings:
    functions = [
        update_user_embedding,
        deliver_push_notification,
        parse_resume_and_update_profile,
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10
    job_timeout = 300   # 5 minutes max per task
    max_tries = 3       # Retry up to 3 times on failure
    on_startup = on_startup
