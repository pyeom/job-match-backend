"""B9.1 / B9.2 — Feedback Loop + Predictive Model Retraining

Tasks:
  - schedule_outcome_requests  : weekly cron — email recruiters for 90-day hire reviews
  - retrain_predictive_model   : weekly cron — retrain XGBoost on accumulated outcomes
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Path where serialised models are stored (overridable via MODEL_PATH env var)
MODEL_PATH = os.environ.get("MODEL_PATH", "/tmp/job_match_models")


# ---------------------------------------------------------------------------
# B9.1.2 — schedule_outcome_requests
# ---------------------------------------------------------------------------

async def schedule_outcome_requests(ctx: dict) -> dict:
    """Weekly cron: find 'avanza' match_scores older than 90 days with no outcome,
    and email each recruiter asking for a 2-minute evaluation.
    """
    from app.core.database import get_db
    from app.repositories.hiring_outcome_repository import HiringOutcomeRepository
    from app.services.email_service import send_outcome_request_email
    from app.core.config import settings
    from sqlalchemy import select
    from app.models.job import Job
    from app.models.user import User

    sent_count = 0
    skipped_count = 0
    outcome_repo = HiringOutcomeRepository()

    async for db in get_db():
        try:
            pending = await outcome_repo.get_pending_outcome_requests(db, days_since_decision=90)
            logger.info("schedule_outcome_requests: %d pending outcome requests found", len(pending))

            for record in pending:
                try:
                    job_result = await db.execute(
                        select(Job).where(Job.id == record["job_id"])
                    )
                    job = job_result.scalar_one_or_none()
                    if not job:
                        skipped_count += 1
                        continue

                    # Find the recruiter who owns the company
                    recruiter_result = await db.execute(
                        select(User).where(User.company_id == job.company_id)
                    )
                    recruiter = recruiter_result.scalar_one_or_none()
                    if not recruiter:
                        skipped_count += 1
                        continue

                    outcome_url = (
                        f"{settings.frontend_url}/company/outcomes"
                        f"?match_score_id={record['match_score_id']}"
                    )

                    await send_outcome_request_email(
                        to_email=recruiter.email,
                        recruiter_name=recruiter.full_name or recruiter.email,
                        candidate_name=record["candidate_name"],
                        job_title=job.title,
                        outcome_url=outcome_url,
                    )
                    sent_count += 1
                except Exception as e:
                    logger.error(
                        "schedule_outcome_requests: failed for match_score %s: %s",
                        record.get("match_score_id"), e, exc_info=True,
                    )
                    skipped_count += 1

        except Exception as exc:
            logger.error("schedule_outcome_requests failed: %s", exc, exc_info=True)
            raise

    logger.info("schedule_outcome_requests: sent=%d skipped=%d", sent_count, skipped_count)
    return {"status": "completed", "sent": sent_count, "skipped": skipped_count}


# ---------------------------------------------------------------------------
# B9.2.1 — retrain_predictive_model
# ---------------------------------------------------------------------------

async def retrain_predictive_model(ctx: dict) -> dict:
    """Weekly cron: retrain the XGBoost hire-prediction model on accumulated outcomes.

    Minimum 100 labelled outcomes required.  New model replaces the active one
    only if AUC-ROC > 0.65.  Model is serialised to MODEL_PATH/ with a timestamp
    in the filename, and the active-model pointer is updated in Redis.
    """
    import os
    import joblib
    import numpy as np
    from app.core.database import get_db
    from app.repositories.hiring_outcome_repository import HiringOutcomeRepository

    outcome_repo = HiringOutcomeRepository()

    async for db in get_db():
        try:
            outcomes = await outcome_repo.get_all_with_features(db)
        except Exception as exc:
            logger.error("retrain_predictive_model: failed to load outcomes: %s", exc, exc_info=True)
            raise

    if len(outcomes) < 100:
        logger.info(
            "retrain_predictive_model: insufficient data (%d outcomes). Skipping.", len(outcomes)
        )
        return {"status": "skipped", "reason": "insufficient_data", "n_outcomes": len(outcomes)}

    try:
        from xgboost import XGBClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import roc_auc_score
    except ImportError as e:
        logger.error("retrain_predictive_model: missing dependency: %s", e)
        return {"status": "error", "reason": str(e)}

    X = [o["puc_vector"] + o["match_features"] for o in outcomes]
    y = [1 if o["was_successful_hire"] else 0 for o in outcomes]

    X_arr = np.array(X, dtype=np.float32)
    y_arr = np.array(y, dtype=np.int32)

    X_train, X_test, y_train, y_test = train_test_split(
        X_arr, y_arr, test_size=0.2, random_state=42, stratify=y_arr if sum(y_arr) >= 2 else None
    )

    model = XGBClassifier(
        n_estimators=100,
        max_depth=4,
        learning_rate=0.1,
        eval_metric="logloss",
        use_label_encoder=False,
    )
    model.fit(X_train, y_train)

    try:
        proba = model.predict_proba(X_test)[:, 1]
        auc = float(roc_auc_score(y_test, proba))
    except ValueError:
        # Can happen with too few positive samples in the test split
        auc = 0.0

    logger.info("retrain_predictive_model: n=%d AUC-ROC=%.3f", len(outcomes), auc)

    if auc <= 0.65:
        logger.warning(
            "retrain_predictive_model: AUC %.3f below threshold (0.65). Model NOT promoted.", auc
        )
        return {"status": "below_threshold", "auc": auc, "n_outcomes": len(outcomes)}

    # Persist model
    os.makedirs(MODEL_PATH, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    model_filename = f"predictive_v{timestamp}.pkl"
    model_filepath = os.path.join(MODEL_PATH, model_filename)
    joblib.dump(model, model_filepath)
    logger.info("retrain_predictive_model: model saved to %s", model_filepath)

    # Update active-model pointer in Redis
    try:
        from app.core.cache import get_redis
        r = await get_redis()
        await r.set(
            "predictive_model:active",
            model_filepath,
        )
        await r.hset("predictive_model:metrics", mapping={
            "auc": str(auc),
            "n_training_samples": str(len(X_train)),
            "n_test_samples": str(len(X_test)),
            "retrained_at": datetime.now(timezone.utc).isoformat(),
            "model_path": model_filepath,
        })
        logger.info("retrain_predictive_model: active model pointer updated in Redis")
    except Exception as e:
        logger.warning("retrain_predictive_model: failed to update Redis pointer: %s", e)

    return {
        "status": "promoted",
        "auc": auc,
        "n_outcomes": len(outcomes),
        "model_path": model_filepath,
    }
