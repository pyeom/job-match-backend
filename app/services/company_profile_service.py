"""
Company profile service — B6.2

Handles:
  - build_org_profile()               : persist E1-E4 texts, enqueue MALA analysis
  - analyze_org_profile_background()  : arq task — calls MALA, updates DB
  - create_or_update_match_config()   : persist E5-E9 + filters, auto-adjust weights
  - infer_big_five_from_job_description(): calls MALA /analyze/job, returns Big Five mins
  - get_job_vector_preview()          : compute preview of Job Vector without activating
"""
from __future__ import annotations

import logging
import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mala import CompanyOrgProfile, JobMatchConfig
from app.repositories.company_org_profile_repository import CompanyOrgProfileRepository
from app.repositories.job_match_config_repository import JobMatchConfigRepository
from app.schemas.company_profile import (
    OrgProfileCreate,
    OrgProfileRead,
    JobMatchConfigCreate,
    JobMatchConfigRead,
    BigFiveMinimums,
    JobVectorPreview,
    ArchetypeAdvantage,
)

logger = logging.getLogger(__name__)

_org_repo = CompanyOrgProfileRepository()
_config_repo = JobMatchConfigRepository()


# ---------------------------------------------------------------------------
# B6.2.1  build_org_profile
# ---------------------------------------------------------------------------

async def build_org_profile(
    db: AsyncSession,
    company_id: UUID,
    payload: OrgProfileCreate,
) -> CompanyOrgProfile:
    """Persist E1–E4 texts and mark profile as pending analysis.

    The actual MALA analysis is done asynchronously by the arq task
    ``analyze_org_profile_background``.
    """
    data = {
        "e1_culture_text": payload.e1_culture_text,
        "e2_no_fit_text": payload.e2_no_fit_text,
        "e3_decision_style_text": payload.e3_decision_style_text,
        "e4_best_hire_text": payload.e4_best_hire_text,
        # Clear any previous inferred fields so GET shows "analyzing"
        "culture_valence": None,
        "affiliation_vs_achievement": None,
        "hierarchy_score": None,
        "management_archetype": None,
        "org_openness": None,
        "org_conscientiousness": None,
        "org_extraversion": None,
        "org_agreeableness": None,
        "org_stability": None,
        "cultural_deal_breakers": None,
        "anti_profile_signals": None,
    }
    profile = await _org_repo.upsert(db, company_id, data)
    await db.commit()
    await db.refresh(profile)
    return profile


async def get_org_profile(
    db: AsyncSession,
    company_id: UUID,
) -> CompanyOrgProfile | None:
    return await _org_repo.get_by_company_id(db, company_id)


# ---------------------------------------------------------------------------
# B6.2.1 (continued)  background MALA analysis — called by arq task
# ---------------------------------------------------------------------------

async def analyze_org_profile_background(
    db: AsyncSession,
    company_id: str,
) -> None:
    """Runs in an arq worker. Calls MALA microservice and persists results."""
    company_uuid = UUID(company_id)
    profile = await _org_repo.get_by_company_id(db, company_uuid)
    if not profile:
        logger.warning("analyze_org_profile_background: no profile found for company %s", company_id)
        return

    try:
        from app.services.nlp import mala_client

        # Build a combined text for E1–E4
        combined = "\n\n".join(filter(None, [
            profile.e1_culture_text,
            profile.e2_no_fit_text,
            profile.e3_decision_style_text,
            profile.e4_best_hire_text,
        ]))

        e_answers = []
        if profile.e1_culture_text:
            e_answers.append({"code": "E1", "text": profile.e1_culture_text})
        if profile.e2_no_fit_text:
            e_answers.append({"code": "E2", "text": profile.e2_no_fit_text})
        if profile.e3_decision_style_text:
            e_answers.append({"code": "E3", "text": profile.e3_decision_style_text})
        if profile.e4_best_hire_text:
            e_answers.append({"code": "E4", "text": profile.e4_best_hire_text})

        result = await mala_client.analyze_job(
            job_offer_id=f"org:{company_id}",
            description=combined,
            e_answers=e_answers,
        )

        inferred = _extract_org_profile_fields(result, profile)

    except Exception as exc:
        logger.error("MALA org-profile analysis failed for company %s: %s", company_id, exc)
        # Leave existing profile intact; caller can retry
        return

    await _org_repo.update(db, profile, inferred)
    await db.commit()
    logger.info("Org profile analysis completed for company %s", company_id)


def _extract_org_profile_fields(mala_result: dict, profile: CompanyOrgProfile) -> dict:
    """Map MALA JobVector response fields into CompanyOrgProfile columns."""
    # MALA returns a JobVector; extract what we need
    req_bf = mala_result.get("required_big_five", {})
    anti_profile = _parse_anti_fit_text(profile.e2_no_fit_text or "")
    management = _detect_management_archetype(profile.e3_decision_style_text or "")

    return {
        "culture_valence": mala_result.get("culture_valence", 0.5),
        "affiliation_vs_achievement": mala_result.get("affiliation_vs_achievement", 0.5),
        "hierarchy_score": mala_result.get("hierarchy_score", 0.5),
        "management_archetype": management,
        "org_openness": _bf_to_100(req_bf.get("openness", 0.5)),
        "org_conscientiousness": _bf_to_100(req_bf.get("conscientiousness", 0.5)),
        "org_extraversion": _bf_to_100(req_bf.get("extraversion", 0.5)),
        "org_agreeableness": _bf_to_100(req_bf.get("agreeableness", 0.5)),
        "org_stability": _bf_to_100(1 - req_bf.get("neuroticism", 0.5)),
        "cultural_deal_breakers": anti_profile["deal_breakers"],
        "anti_profile_signals": anti_profile["thresholds"],
    }


def _bf_to_100(value: float) -> float:
    """Convert 0-1 Big Five score to 0-100 scale."""
    return round(max(0.0, min(100.0, value * 100)), 1)


# B6.2.1 — E2: detect anti-fit traits → max thresholds
_ANTI_FIT_PATTERNS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"impaciente|apresurad", re.I), "conscientiousness_max", 0.4),
    (re.compile(r"agresiv|conflict", re.I), "agreeableness_min", 0.6),
    (re.compile(r"desorgani|caótic", re.I), "conscientiousness_max", 0.35),
    (re.compile(r"introvert|retraíd|solitari", re.I), "extraversion_min", 0.45),
    (re.compile(r"rígid|inflexible|cerrad", re.I), "openness_min", 0.5),
    (re.compile(r"inestable|ansios|nervios", re.I), "stability_min", 0.55),
]


def _parse_anti_fit_text(text: str) -> dict:
    """Detect negative trait mentions → convert to max/min thresholds."""
    deal_breakers: list[str] = []
    thresholds: dict[str, float] = {}

    for pattern, threshold_key, threshold_val in _ANTI_FIT_PATTERNS:
        if pattern.search(text):
            deal_breakers.append(threshold_key.split("_")[0])
            thresholds[threshold_key] = threshold_val

    return {"deal_breakers": deal_breakers, "thresholds": thresholds}


# B6.2.1 — E3: management archetype classification
_MANAGEMENT_ARCHETYPES: dict[str, list[str]] = {
    "autocrático": ["yo decido", "la dirección define", "decisión ejecutiva", "dueño decide"],
    "consultivo": ["consultamos", "pedimos opinión", "input del equipo", "escuchamos", "consideramos"],
    "democrático": ["votamos", "consenso", "todos tienen voz", "decisión colectiva", "juntos decidimos"],
    "laissez": ["cada uno decide", "autonomía total", "sin microgestión", "libertad", "auto-gestionamos"],
}


def _detect_management_archetype(text: str) -> str:
    text_lower = text.lower()
    scores: dict[str, int] = {archetype: 0 for archetype in _MANAGEMENT_ARCHETYPES}

    for archetype, keywords in _MANAGEMENT_ARCHETYPES.items():
        for kw in keywords:
            if kw in text_lower:
                scores[archetype] += 1

    best = max(scores, key=lambda k: scores[k])
    # If no match at all, default to consultivo (most common in practice)
    return best if scores[best] > 0 else "consultivo"


# ---------------------------------------------------------------------------
# B6.2.2  infer_big_five_from_job_description
# ---------------------------------------------------------------------------

# Signal table: pattern → (dimension, min_value)
_JD_SIGNALS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"orientad[oa] a resultados|driven|alto desempeño", re.I), "conscientiousness_min", 65.0),
    (re.compile(r"trabajar? con autonomía|self.starter|independiente", re.I), "openness_min", 55.0),
    (re.compile(r"alta exigencia|high.demand|ritmo acelerado", re.I), "stability_min", 60.0),
    (re.compile(r"comunicación a distintos niveles|stakeholders|presentaciones", re.I), "extraversion_min", 50.0),
    (re.compile(r"trabaj[ao] en equipo|colaborativ|team player", re.I), "agreeableness_min", 55.0),
    (re.compile(r"innovació|creativ|disruptiv", re.I), "openness_min", 60.0),
    (re.compile(r"liderazgo|gestión de equipos|manage a team", re.I), "extraversion_min", 60.0),
    (re.compile(r"metódic|estructurad|ordenad", re.I), "conscientiousness_min", 60.0),
    (re.compile(r"resiliencia|presión|adversidad", re.I), "stability_min", 65.0),
    (re.compile(r"empatía|relaciones interpersonales", re.I), "agreeableness_min", 60.0),
]

_DIM_MAP = {
    "openness_min": "openness",
    "conscientiousness_min": "conscientiousness",
    "extraversion_min": "extraversion",
    "agreeableness_min": "agreeableness",
    "stability_min": "stability",
}


async def infer_big_five_from_job_description(description: str) -> BigFiveMinimums:
    """B6.2.2 — Infer Big Five minimums from free-text job description.

    Uses heuristic signal table first; falls back to MALA if available.
    """
    minimums = {dim: 0.0 for dim in _DIM_MAP.values()}

    for pattern, threshold_key, threshold_val in _JD_SIGNALS:
        if pattern.search(description):
            dim = _DIM_MAP[threshold_key]
            minimums[dim] = max(minimums[dim], threshold_val)

    # Attempt MALA enrichment (best-effort)
    try:
        from app.services.nlp import mala_client

        result = await mala_client.analyze_job(
            job_offer_id="infer_bf",
            description=description,
            e_answers=[],
        )
        req_bf = result.get("required_big_five", {})
        thresholds = result.get("min_thresholds", {})

        for dim in ("openness", "conscientiousness", "extraversion", "agreeableness"):
            mala_val = _bf_to_100(thresholds.get(dim, req_bf.get(dim, 0.0)))
            minimums[dim] = max(minimums[dim], mala_val)
        # neuroticism → stability
        neuroticism = thresholds.get("neuroticism", req_bf.get("neuroticism", 0.5))
        minimums["stability"] = max(minimums["stability"], _bf_to_100(1 - neuroticism))

    except Exception as exc:
        logger.debug("MALA enrichment unavailable for infer_big_five: %s", exc)

    return BigFiveMinimums(**minimums)


# ---------------------------------------------------------------------------
# B6.2 (support)  create_or_update_match_config
# ---------------------------------------------------------------------------

async def create_or_update_match_config(
    db: AsyncSession,
    job_id: UUID,
    payload: JobMatchConfigCreate,
) -> JobMatchConfig:
    """Persist E5-E9 + filters + auto-adjusted weights."""
    weight_hard, weight_soft, weight_predictive = _auto_adjust_weights(
        payload.e5_skills_vs_attitude,
        payload.weight_hard,
        payload.weight_soft,
        payload.weight_predictive,
    )

    anti_profile = _parse_anti_profile_vector(payload.e9_failure_profile)
    ideal_archetype = _infer_ideal_archetype(payload)

    data = {
        "e5_skills_vs_attitude": payload.e5_skills_vs_attitude,
        "e6_team_description": payload.e6_team_description,
        "e7_first_90_days": payload.e7_first_90_days,
        "e8_success_signal": payload.e8_success_signal,
        "e9_failure_profile": payload.e9_failure_profile,
        "req_openness_min": payload.req_openness_min,
        "req_conscientiousness_min": payload.req_conscientiousness_min,
        "req_extraversion_min": payload.req_extraversion_min,
        "req_agreeableness_min": payload.req_agreeableness_min,
        "req_stability_min": payload.req_stability_min,
        "weight_hard": weight_hard,
        "weight_soft": weight_soft,
        "weight_predictive": weight_predictive,
        "min_experience_years": payload.min_experience_years,
        "required_education_level": payload.required_education_level,
        "required_languages": payload.required_languages,
        "hard_skills_required": payload.hard_skills_required,
        "hard_skills_desired": payload.hard_skills_desired,
        "interview_type": payload.interview_type,
        "portfolio_required": payload.portfolio_required,
        "ideal_archetype": ideal_archetype,
        "anti_profile_vector": anti_profile,
    }

    config = await _config_repo.upsert(db, job_id, data)
    await db.commit()
    await db.refresh(config)
    return config


async def get_match_config(
    db: AsyncSession,
    job_id: UUID,
) -> JobMatchConfig | None:
    return await _config_repo.get_by_job_id(db, job_id)


# ---------------------------------------------------------------------------
# B6.2  Weight auto-adjustment from E5 (B6.3.3 spec)
# ---------------------------------------------------------------------------

def _auto_adjust_weights(
    e5_text: str,
    w_hard: float,
    w_soft: float,
    w_pred: float,
) -> tuple[float, float, float]:
    text = e5_text.lower()
    if "skills exactas" in text or "técnic" in text or "certificad" in text:
        return 0.65, 0.20, 0.15
    if "actitud" in text or "aprend" in text or "potencial" in text or "motivación" in text:
        return 0.35, 0.45, 0.20
    # Keep caller-provided weights
    return w_hard, w_soft, w_pred


# ---------------------------------------------------------------------------
# E9 → anti-profile vector
# ---------------------------------------------------------------------------

_E9_SIGNALS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"impaciente|no escucha|arrogan", re.I), "agreeableness", -1.0),
    (re.compile(r"desorgani|incumpl|no entrega", re.I), "conscientiousness", -1.0),
    (re.compile(r"no aprende|rígid|cerrad", re.I), "openness", -1.0),
    (re.compile(r"conflictiv|tóxic|agresiv", re.I), "agreeableness", -2.0),
    (re.compile(r"ansios|estresad|no maneja presión", re.I), "stability", -1.0),
]


def _parse_anti_profile_vector(e9_text: str) -> dict[str, float]:
    """Convert E9 failure-profile text into negative Big Five adjustment signals."""
    vector: dict[str, float] = {}
    for pattern, dim, weight in _E9_SIGNALS:
        if pattern.search(e9_text):
            vector[dim] = vector.get(dim, 0.0) + weight
    return vector


# ---------------------------------------------------------------------------
# Ideal archetype inference from E5–E8
# ---------------------------------------------------------------------------

_ARCHETYPE_SIGNALS: dict[str, list[str]] = {
    "El Constructor": ["escalar", "crecer", "construir desde cero", "startup", "etapa temprana"],
    "El Ejecutor": ["resultados", "kpi", "metas", "entrega", "ejecutar", "deadline"],
    "El Conector": ["red", "relaciones", "colaborar", "alianzas", "comunicación"],
    "El Explorador": ["investigar", "innovar", "experimentar", "aprender", "curiosidad"],
    "El Guardián": ["procesos", "calidad", "cumplimiento", "estabilidad", "normas"],
    "El Mentor": ["enseñar", "desarrollar", "coaching", "equipo", "liderazgo"],
}


def _infer_ideal_archetype(payload: JobMatchConfigCreate) -> str | None:
    combined = " ".join([
        payload.e5_skills_vs_attitude,
        payload.e6_team_description,
        payload.e7_first_90_days,
        payload.e8_success_signal,
    ]).lower()

    scores: dict[str, int] = {k: 0 for k in _ARCHETYPE_SIGNALS}
    for archetype, signals in _ARCHETYPE_SIGNALS.items():
        for signal in signals:
            if signal in combined:
                scores[archetype] += 1

    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else None


# ---------------------------------------------------------------------------
# B6.3.4  Job Vector preview
# ---------------------------------------------------------------------------

_ARCHETYPE_BIG_FIVE_AFFINITY: dict[str, list[str]] = {
    "El Constructor": ["openness", "conscientiousness"],
    "El Ejecutor": ["conscientiousness", "stability"],
    "El Conector": ["extraversion", "agreeableness"],
    "El Explorador": ["openness", "extraversion"],
    "El Guardián": ["conscientiousness", "stability"],
    "El Mentor": ["agreeableness", "extraversion"],
}


async def get_job_vector_preview(
    db: AsyncSession,
    job_id: UUID,
) -> JobVectorPreview | None:
    config = await _config_repo.get_by_job_id(db, job_id)
    if not config:
        return None

    minimums = BigFiveMinimums(
        openness=config.req_openness_min or 0.0,
        conscientiousness=config.req_conscientiousness_min or 0.0,
        extraversion=config.req_extraversion_min or 0.0,
        agreeableness=config.req_agreeableness_min or 0.0,
        stability=config.req_stability_min or 0.0,
    )

    advantages = _compute_archetype_advantages(minimums, config.ideal_archetype)
    anti_summary = _summarize_anti_profile(config.anti_profile_vector or {})

    config_read = JobMatchConfigRead.model_validate(config)

    return JobVectorPreview(
        job_id=job_id,
        big_five_minimums=minimums,
        weight_hard=config.weight_hard,
        weight_soft=config.weight_soft,
        weight_predictive=config.weight_predictive,
        ideal_archetype=config.ideal_archetype,
        archetype_advantages=advantages,
        anti_profile_summary=anti_summary,
        config=config_read,
    )


def _compute_archetype_advantages(
    mins: BigFiveMinimums,
    ideal_archetype: str | None,
) -> list[ArchetypeAdvantage]:
    advantages: list[ArchetypeAdvantage] = []
    mins_dict = mins.model_dump()

    for archetype, affinities in _ARCHETYPE_BIG_FIVE_AFFINITY.items():
        boost = sum(1 for dim in affinities if mins_dict.get(dim, 0) >= 50)
        if boost > 0:
            is_ideal = archetype == ideal_archetype
            label = "+20 pts" if is_ideal else f"+{boost * 5} pts"
            advantages.append(ArchetypeAdvantage(
                archetype=archetype,
                score_boost=label,
                reason=f"High {' & '.join(affinities)} fit",
            ))

    if ideal_archetype and not any(a.archetype == ideal_archetype for a in advantages):
        advantages.insert(0, ArchetypeAdvantage(
            archetype=ideal_archetype,
            score_boost="+20 pts",
            reason="Explicitly preferred archetype",
        ))

    return advantages[:5]


def _summarize_anti_profile(anti_vector: dict[str, float]) -> str | None:
    if not anti_vector:
        return None
    negatives = [dim for dim, weight in anti_vector.items() if weight < 0]
    if not negatives:
        return None
    dim_labels = {
        "openness": "low openness",
        "conscientiousness": "low conscientiousness",
        "agreeableness": "low agreeableness",
        "extraversion": "low extraversion",
        "stability": "emotional instability",
    }
    labels = [dim_labels.get(d, d) for d in negatives]
    return f"Candidates flagged for: {', '.join(labels)}"
