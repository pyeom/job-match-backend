"""B10.2 — Monthly Fairness Audit (arq cron)

Task:
  - run_monthly_fairness_audit : cron day 1 of each month — compute disparate
    impact for all active jobs and persist a dated report to Redis.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)

FAIRNESS_REPORT_PREFIX = "fairness_report:"
FAIRNESS_REPORT_INDEX_KEY = "fairness_report_index"


# ---------------------------------------------------------------------------
# B10.2.1 — run_monthly_fairness_audit
# ---------------------------------------------------------------------------

async def run_monthly_fairness_audit(ctx: dict) -> dict:
    """Monthly cron: compute disparate impact per active job and save report.

    Flags jobs where any protected group has disparate_impact < 0.80 and
    notifies admins via the email service.

    Report is stored in Redis under key ``fairness_report:{YYYY-MM-DD}`` with
    TTL of 2 years; an index key tracks all report dates.
    """
    from app.core.database import get_db
    from app.core.cache import get_redis
    from app.models.job import Job
    from app.services.fairness_service import get_fairness_service
    from sqlalchemy import select

    today = date.today().isoformat()
    logger.info("run_monthly_fairness_audit: starting audit for %s", today)

    report: dict = {}
    flagged_jobs: list[dict] = []

    fairness_service = get_fairness_service()

    async for db in get_db():
        try:
            # Fetch all active jobs (global, not per-company)
            stmt = select(Job).where(Job.is_active == True)  # noqa: E712
            result = await db.execute(stmt)
            jobs = list(result.scalars().all())

            logger.info("run_monthly_fairness_audit: auditing %d active jobs", len(jobs))

            for job in jobs:
                try:
                    di = await fairness_service.compute_disparate_impact(db, job.id)
                    report[str(job.id)] = di

                    any_flagged = any(
                        v.get("flagged") for v in di.values() if isinstance(v, dict)
                    )
                    if any_flagged:
                        flagged_jobs.append({"job_id": str(job.id), "di": di})
                        logger.warning(
                            "Disparate impact flag — job %s: %s", job.id, di
                        )
                except Exception as exc:
                    logger.error(
                        "run_monthly_fairness_audit: error for job %s: %s", job.id, exc
                    )
                    report[str(job.id)] = {"error": str(exc)}

        except Exception as exc:
            logger.error("run_monthly_fairness_audit: DB error: %s", exc)
            return {"error": str(exc), "audited_jobs": 0}

    # Persist report to Redis
    report_payload = {
        "date": today,
        "audited_jobs": len(report),
        "flagged_jobs": len(flagged_jobs),
        "report": report,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        r = await get_redis()
        redis_key = f"{FAIRNESS_REPORT_PREFIX}{today}"
        two_years_seconds = 2 * 365 * 24 * 3600
        await r.set(redis_key, json.dumps(report_payload), ex=two_years_seconds)
        # Track the date in a sorted set (score = YYYYMMDD as int for ordering)
        score = int(today.replace("-", ""))
        await r.zadd(FAIRNESS_REPORT_INDEX_KEY, {today: score})
        logger.info(
            "run_monthly_fairness_audit: saved report for %s (%d jobs, %d flagged)",
            today, len(report), len(flagged_jobs),
        )
    except Exception as exc:
        logger.error("run_monthly_fairness_audit: Redis save error: %s", exc)

    # Notify admins about flagged jobs
    if flagged_jobs:
        await _notify_admins_flagged_jobs(flagged_jobs, today)

    return {
        "date": today,
        "audited_jobs": len(report),
        "flagged_jobs": len(flagged_jobs),
    }


async def _notify_admins_flagged_jobs(flagged_jobs: list[dict], report_date: str) -> None:
    """Send admin alert emails for jobs with disparate impact flags."""
    try:
        from app.services.email_service import send_admin_alert_email

        body = (
            f"Fairness audit {report_date}: {len(flagged_jobs)} job(s) flagged "
            f"for disparate impact below the 4/5 threshold (0.80).\n\n"
        )
        for entry in flagged_jobs:
            body += f"  • Job {entry['job_id']}: {entry['di']}\n"

        await send_admin_alert_email(
            subject=f"[Job Match] Disparate impact detected — {report_date}",
            body=body,
        )
    except Exception as exc:
        logger.error("_notify_admins_flagged_jobs: email error: %s", exc)
