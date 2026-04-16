"""B10.1 — Fairness Service

Implements the 5 bias mitigations defined in the PRD:
  Bias 1 — Articulation (TTR normalization by education level)
  Bias 2 — LIWC gender ratios (audit-only flag, no individual adjustment)
  Bias 3 — Cultural background (implicit via L3 LIWC calibration — no action here)
  Bias 4 — Social Desirability (already in Layer5Result.social_desirability_flag)
  Bias 5 — ML Bias (compute_disparate_impact, 4/5 rule, per-job per-group)
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bias 1 — TTR normalisation by education level
# ---------------------------------------------------------------------------

EDU_TTR_BASELINES: dict[str, float] = {
    "secundaria": 0.35,
    "técnico": 0.42,
    "universitario": 0.48,
    "postgrado": 0.54,
    "doctorado": 0.58,
}


def normalize_ttr_for_education(ttr: float, edu: str) -> float:
    """Return TTR normalised relative to the education-level baseline.

    Candidates with lower formal education are penalised less when their raw
    TTR is proportionally high relative to their peer group.

    Returns a value in [0, 1].
    """
    baseline = EDU_TTR_BASELINES.get(edu.lower().strip(), 0.45)
    return min(ttr / baseline, 1.0) if baseline > 0 else ttr


# ---------------------------------------------------------------------------
# Bias 2 — LIWC gender audit flag
# ---------------------------------------------------------------------------

def should_flag_liwc_gender_audit(
    we_ratio: float,
    i_ratio: float,
    *,
    we_threshold: float = 0.03,
    i_threshold: float = 0.06,
) -> bool:
    """Return True when the LIWC pronoun ratios warrant inclusion in the monthly
    gender audit.

    We *do not* adjust scores per individual based on gender; instead we flag
    transcripts where pronoun ratios diverge significantly so the monthly audit
    can check for disparate-impact patterns across the full cohort.
    """
    return we_ratio > we_threshold or i_ratio > i_threshold


# ---------------------------------------------------------------------------
# Bias 5 — Disparate Impact (ML / Recruiter decision)
# ---------------------------------------------------------------------------

class FairnessService:
    """Compute per-job disparate impact metrics across protected groups.

    Supported groups:
      - "region" — derived from User.preferred_locations[0] (best-effort)
      - "gender" — not yet available in the data model; returns {} with a note

    The 4/5 rule: disparate_impact = min_group_rate / max_group_rate.
    A value below 0.80 triggers a flag.
    """

    async def _compute_selection_rates_by(
        self,
        db: AsyncSession,
        job_id: UUID,
        group: str,
    ) -> dict[str, float]:
        """Return {group_value: selection_rate} for a given job and protected group.

        selection_rate = candidates advanced / total candidates in that group.
        Returns {} when there is insufficient demographic data.
        """
        from app.models.mala import MatchScore
        from app.models.user import User

        stmt = (
            select(MatchScore, User)
            .join(User, User.id == MatchScore.user_id)
            .where(MatchScore.job_id == job_id)
        )
        result = await db.execute(stmt)
        rows = result.all()

        if not rows:
            return {}

        group_totals: dict[str, int] = {}
        group_advanced: dict[str, int] = {}

        for match_score, user in rows:
            if group == "gender":
                gender_value = (user.gender_identity or "").strip() or "unknown"
                group_key = gender_value

            elif group == "region":
                locations: list = user.preferred_locations or []
                group_key = str(locations[0]).strip() if locations else "unknown"
                if not group_key:
                    group_key = "unknown"
            else:
                logger.warning("FairnessService: unknown group '%s', skipping", group)
                return {}

            group_totals[group_key] = group_totals.get(group_key, 0) + 1
            if match_score.recruiter_decision == "avanza":
                group_advanced[group_key] = group_advanced.get(group_key, 0) + 1

        rates: dict[str, float] = {}
        for grp, total in group_totals.items():
            advanced = group_advanced.get(grp, 0)
            rates[grp] = advanced / total if total > 0 else 0.0

        return rates

    async def compute_disparate_impact(
        self,
        db: AsyncSession,
        job_id: UUID,
    ) -> dict:
        """Compute disparate impact for all supported protected groups for a job.

        Returns a dict keyed by group name, each containing:
          - disparate_impact (float)
          - flagged (bool) — True when DI < 0.80 (4/5 rule)
          - rates (dict[str, float]) — selection rate per group value
          - note (str | None) — populated when data is insufficient
        """
        results: dict = {}
        for group in ("gender", "region"):
            try:
                rates = await self._compute_selection_rates_by(db, job_id, group)
            except Exception as exc:
                logger.error(
                    "FairnessService: error computing rates for group '%s', job %s: %s",
                    group, job_id, exc,
                )
                results[group] = {
                    "disparate_impact": None,
                    "flagged": False,
                    "rates": {},
                    "note": f"computation error: {exc}",
                }
                continue

            if not rates:
                results[group] = {
                    "disparate_impact": None,
                    "flagged": False,
                    "rates": {},
                    "note": "insufficient demographic data",
                }
                continue

            values = list(rates.values())
            if len(values) < 2:
                # Only one group present — can't compute ratio
                results[group] = {
                    "disparate_impact": None,
                    "flagged": False,
                    "rates": rates,
                    "note": "only one group represented",
                }
                continue

            min_rate = min(values)
            max_rate = max(values)
            di = min_rate / max_rate if max_rate > 0 else 1.0

            results[group] = {
                "disparate_impact": round(di, 4),
                "flagged": di < 0.8,
                "rates": {k: round(v, 4) for k, v in rates.items()},
                "note": None,
            }

        return results


# Singleton
_fairness_service: Optional[FairnessService] = None


def get_fairness_service() -> FairnessService:
    global _fairness_service
    if _fairness_service is None:
        _fairness_service = FairnessService()
    return _fairness_service
