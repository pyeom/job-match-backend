import logging

import httpx
from arq.connections import RedisSettings
from arq import cron

from app.core.config import settings
from app.tasks.embedding_tasks import update_user_embedding
from app.tasks.notification_tasks import deliver_push_notification
from app.tasks.document_tasks import parse_resume_and_update_profile
from app.tasks.elasticsearch_tasks import reindex_all_jobs
from app.tasks.application_tasks import finalize_pending_application
from app.tasks.auth_tasks import cleanup_expired_sessions
from app.tasks.mala_analysis import analyze_mala_response
from app.tasks.org_profile_analysis import analyze_org_profile
from app.tasks.match_score_tasks import (
    recalculate_match_scores_for_user,
    recalculate_match_scores_for_job,
    generate_initial_ranking,
)
from app.tasks.feedback_loop_tasks import (
    schedule_outcome_requests,
    retrain_predictive_model,
)
from app.tasks.fairness_tasks import run_monthly_fairness_audit

logger = logging.getLogger(__name__)


async def on_startup(ctx: dict) -> None:
    ctx["http_client"] = httpx.AsyncClient(timeout=10.0)
    logger.info(
        "ARQ worker started. Functions: update_user_embedding, "
        "deliver_push_notification, parse_resume_and_update_profile, "
        "reindex_all_jobs, finalize_pending_application, cleanup_expired_sessions"
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
        finalize_pending_application,
        cleanup_expired_sessions,
        analyze_mala_response,
        analyze_org_profile,
        recalculate_match_scores_for_user,
        recalculate_match_scores_for_job,
        generate_initial_ranking,
        schedule_outcome_requests,
        retrain_predictive_model,
        run_monthly_fairness_audit,
    ]
    cron_jobs = [
        cron(cleanup_expired_sessions, hour={0, 6, 12, 18}, minute=0),
        # B9.1.2 — weekly outcome-request emails (Monday 09:00 UTC)
        cron(schedule_outcome_requests, weekday=0, hour=9, minute=0),
        # B9.2.2 — weekly model retraining (Sunday 02:00 UTC, low-traffic window)
        cron(retrain_predictive_model, weekday=6, hour=2, minute=0),
        # B10.2.2 — monthly fairness audit (1st of each month, 03:00 UTC)
        cron(run_monthly_fairness_audit, day=1, hour=3, minute=0),
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10
    job_timeout = 300   # 5 minutes max per task
    max_tries = 3       # Retry up to 3 times on failure
    on_startup = on_startup
    on_shutdown = on_shutdown
