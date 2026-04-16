from __future__ import annotations

import logging
import uuid

from app.core.database import get_db
from app.repositories.mala_response_repository import MalaResponseRepository
from app.repositories.puc_profile_repository import PUCProfileRepository

logger = logging.getLogger(__name__)

_mala_repo = MalaResponseRepository()
_puc_repo = PUCProfileRepository()


async def analyze_mala_response(
    ctx: dict,
    user_id: str,
    question_code: str,
    response_text: str,
) -> dict:
    user_uuid = uuid.UUID(user_id)

    async for db in get_db():
        try:
            await _mala_repo.update_status(db, user_uuid, question_code, "processing")
            await db.commit()

            try:
                from app.services.nlp import mala_client

                result = await mala_client.analyze_candidate(
                    candidate_id=user_id,
                    cv_text="",
                    answers=[{"code": question_code, "text": response_text}],
                )
            except Exception as client_err:
                logger.warning(
                    "MALA client unavailable for user %s / %s: %s — storing placeholder",
                    user_id,
                    question_code,
                    client_err,
                )
                result = {
                    "layer1_sentiment": None,
                    "layer2_nlp": None,
                    "layer3_liwc": None,
                    "layer4_neuro": None,
                    "layer5_synthesis": None,
                }

            layer_data = {
                "layer1_sentiment": result.get("layer1_sentiment"),
                "layer2_nlp": result.get("layer2_nlp"),
                "layer3_liwc": result.get("layer3_liwc"),
                "layer4_neuro": result.get("layer4_neuro"),
                "layer5_synthesis": result.get("layer5_synthesis"),
                "processing_status": "completed",
                "processing_error": None,
            }

            await _mala_repo.save_layer_results(db, user_uuid, question_code, layer_data)
            await db.commit()

            logger.info("MALA analysis completed for user %s / %s", user_id, question_code)
            return {"status": "completed", "question_code": question_code}

        except Exception as exc:
            logger.error(
                "MALA analysis failed for user %s / %s: %s",
                user_id,
                question_code,
                exc,
                exc_info=True,
            )
            try:
                await _mala_repo.update_status(
                    db, user_uuid, question_code, "failed", error=str(exc)
                )
                await db.commit()
            except Exception:
                pass
            raise
