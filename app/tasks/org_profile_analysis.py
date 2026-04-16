from __future__ import annotations

import logging

from app.core.database import get_db

logger = logging.getLogger(__name__)


async def analyze_org_profile(ctx: dict, company_id: str) -> dict:
    """arq task — run MALA analysis on company org profile (E1–E4).

    Calls the MALA microservice and persists inferred fields into
    ``company_org_profiles``.
    """
    async for db in get_db():
        try:
            from app.services.company_profile_service import analyze_org_profile_background

            await analyze_org_profile_background(db, company_id)
            logger.info("Org profile analysis task completed for company %s", company_id)
            return {"status": "completed", "company_id": company_id}

        except Exception as exc:
            logger.error(
                "Org profile analysis task failed for company %s: %s",
                company_id,
                exc,
                exc_info=True,
            )
            raise
