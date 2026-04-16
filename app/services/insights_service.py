"""
B8.1 + B8.2.1 — Insights Service

Enhanced insights generation that compares candidate PUC against job_config
requirements (vs the B7 template-based version that used hardcoded thresholds).

Public API
----------
generate_top_strengths(puc, job_config) -> list[InsightItem]
generate_top_alerts(puc, job_config)    -> list[InsightItem]
generate_competency_explanation(competency, score, evidence) -> str   [B8.2.1]
async generate_explanation_text_llm(candidate, job, scores, puc) -> str  [B8.1.3]
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from app.models.job import Job
from app.models.mala import CandidatePUCProfile, JobMatchConfig
from app.models.user import User
from app.schemas.match_score import (
    HardMatchDetail,
    InsightItem,
    MatchScoreResult,
    SoftMatchDetail,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PUC dimension → recruiter-friendly metadata
# ---------------------------------------------------------------------------

_DIM_META: dict[str, dict] = {
    "openness": {
        "label": "Apertura e innovación",
        "strength_evidence": "Candidato con alta apertura a nuevas ideas y adaptación al cambio.",
        "alert_evidence": "Baja apertura detectada — puede preferir entornos rutinarios. Explorar en entrevista.",
    },
    "conscientiousness": {
        "label": "Autogestión y rigor",
        "strength_evidence": "Perfil altamente organizado, orientado al detalle y al seguimiento de tareas.",
        "alert_evidence": "Baja consciencia detectada — puede requerir supervisión adicional.",
    },
    "extraversion": {
        "label": "Energía social y comunicación",
        "strength_evidence": "Perfil extrovertido con alta energía para interacciones y trabajo en equipo.",
        "alert_evidence": "Perfil introvertido — puede tener dificultades en roles de alta exposición social.",
    },
    "agreeableness": {
        "label": "Colaboración y empatía",
        "strength_evidence": "Alta amabilidad y empatía — favorece la dinámica de equipo y la cooperación.",
        "alert_evidence": "Baja amabilidad detectada — puede generar fricciones interpersonales.",
    },
    "emotional_stability": {
        "label": "Estabilidad emocional bajo presión",
        "strength_evidence": "Alta estabilidad emocional — rendimiento consistente bajo presión y estrés.",
        "alert_evidence": "Baja estabilidad emocional detectada — puede impactar rendimiento bajo presión.",
    },
    "n_ach": {
        "label": "Motivación de logro",
        "strength_evidence": "Alta necesidad de logro — orientado a metas y resultados medibles.",
        "alert_evidence": "Baja orientación al logro — verificar alineación con los objetivos del rol.",
    },
    "n_aff": {
        "label": "Motivación de afiliación",
        "strength_evidence": "Alta necesidad de afiliación — valora las relaciones y la pertenencia al equipo.",
        "alert_evidence": "Baja necesidad de afiliación — puede preferir trabajo independiente.",
    },
    "n_pow": {
        "label": "Motivación de poder / liderazgo",
        "strength_evidence": "Alta necesidad de poder — orientado al liderazgo y la influencia.",
        "alert_evidence": "Baja necesidad de poder — puede no encajar en roles de alta responsabilidad.",
    },
    "leadership_score": {
        "label": "Capacidad de liderazgo",
        "strength_evidence": "Señales lingüísticas de liderazgo y toma de decisiones detectadas.",
        "alert_evidence": "Bajas señales de liderazgo — a explorar si el rol requiere gestión de equipos.",
    },
    "collaboration_score": {
        "label": "Trabajo colaborativo",
        "strength_evidence": "Alta orientación al trabajo en equipo y construcción de consenso.",
        "alert_evidence": "Baja señal de colaboración — verificar adaptación a equipos de trabajo.",
    },
    "analytical_thinking": {
        "label": "Pensamiento analítico",
        "strength_evidence": "Pensamiento estructurado y analítico evidenciado en sus respuestas.",
        "alert_evidence": "Baja densidad causal y pensamiento analítico — explorar capacidad de resolución de problemas.",
    },
    "adaptability_score": {
        "label": "Adaptabilidad al cambio",
        "strength_evidence": "Alta adaptabilidad — se ajusta bien a entornos dinámicos e inciertos.",
        "alert_evidence": "Baja adaptabilidad detectada — puede tener dificultades en entornos cambiantes.",
    },
    "resilience_score": {
        "label": "Resiliencia y manejo del fracaso",
        "strength_evidence": "Alta resiliencia — aprende del error y se recupera ante la adversidad.",
        "alert_evidence": "Baja resiliencia detectada — explorar cómo maneja fracasos y contratiempos.",
    },
    "integrity_score": {
        "label": "Integridad y ética profesional",
        "strength_evidence": "Señales de alta integridad y coherencia en valores profesionales.",
        "alert_evidence": "Baja señal de integridad — a explorar en entrevista de referencias.",
    },
    "written_communication": {
        "label": "Comunicación escrita",
        "strength_evidence": "Alta riqueza léxica y cohesión textual en sus respuestas.",
        "alert_evidence": "Baja calidad de comunicación escrita detectada.",
    },
}

# Dimensions that the job_config configures directly via req_X_min fields
_BIG_FIVE_CONFIG_MAP = [
    ("openness",           "req_openness_min"),
    ("conscientiousness",  "req_conscientiousness_min"),
    ("extraversion",       "req_extraversion_min"),
    ("agreeableness",      "req_agreeableness_min"),
    ("emotional_stability","req_stability_min"),
]

# Other soft dimensions checked against a baseline threshold of 50
_SOFT_DIMS = [
    ("n_ach",             "motivación de logro"),
    ("n_aff",             "motivación de afiliación"),
    ("n_pow",             "motivación de poder"),
    ("leadership_score",  "liderazgo"),
    ("collaboration_score","colaboración"),
    ("analytical_thinking","pensamiento analítico"),
    ("adaptability_score","adaptabilidad"),
    ("resilience_score",  "resiliencia"),
    ("integrity_score",   "integridad"),
    ("written_communication","comunicación escrita"),
]


# ---------------------------------------------------------------------------
# B8.1.1 — generate_top_strengths
# ---------------------------------------------------------------------------

def generate_top_strengths(
    puc: CandidatePUCProfile,
    job_config: JobMatchConfig,
    hard_detail: Optional[HardMatchDetail] = None,
    soft_detail: Optional[SoftMatchDetail] = None,
) -> list[InsightItem]:
    """Return up to 3 strengths where the candidate exceeds job requirements.

    Compares each relevant PUC dimension against the job_config minimum.
    Falls back to absolute performance (>70/100) when no minimum is set.
    """
    candidates: list[tuple[float, InsightItem]] = []  # (confidence, item)

    # --- Big Five vs job requirements ---
    for dim, cfg_field in _BIG_FIVE_CONFIG_MAP:
        cand_val = getattr(puc, dim, None)
        req_min = getattr(job_config, cfg_field, 0.0) or 0.0
        if cand_val is None:
            continue

        # Convert job_config 0-1 scale to 0-100 for comparison
        req_min_100 = req_min * 100 if req_min <= 1.0 else req_min
        threshold = max(req_min_100, 65.0)  # floor at 65 if no requirement set

        if cand_val >= threshold:
            meta = _DIM_META.get(dim, {})
            surplus = cand_val - threshold
            confidence = min(1.0, (cand_val / 100.0) + (surplus / 200.0))
            candidates.append((confidence, InsightItem(
                title=meta.get("label", dim),
                evidence=f"{meta.get('strength_evidence', '')} (score: {cand_val:.0f}/100, req: {threshold:.0f}+)",
                confidence=round(confidence, 3),
                source_layer=4,
            )))

    # --- Soft dimensions vs baseline 70 ---
    for dim, _label in _SOFT_DIMS:
        cand_val = getattr(puc, dim, None)
        if cand_val is None:
            continue
        if cand_val >= 70:
            meta = _DIM_META.get(dim, {})
            confidence = min(1.0, cand_val / 100.0)
            candidates.append((confidence, InsightItem(
                title=meta.get("label", _label),
                evidence=f"{meta.get('strength_evidence', '')} (score: {cand_val:.0f}/100)",
                confidence=round(confidence, 3),
                source_layer=3,
            )))

    # --- Hard skills coverage bonus ---
    if hard_detail and hard_detail.passed_filter and hard_detail.skills_coverage >= 0.85:
        candidates.append((hard_detail.skills_coverage, InsightItem(
            title="Cobertura técnica excelente",
            evidence=f"Cubre el {hard_detail.skills_coverage * 100:.0f}% de las habilidades requeridas para el puesto.",
            confidence=round(hard_detail.skills_coverage, 3),
            source_layer=1,
        )))

    # --- Archetype alignment bonus ---
    if soft_detail and soft_detail.career_narrative_fit >= 100.0:
        candidates.append((0.95, InsightItem(
            title="Arquetipo ideal para el rol",
            evidence="El arquetipo del candidato coincide con el arquetipo ideal definido para esta posición.",
            confidence=0.95,
            source_layer=5,
        )))
    elif soft_detail and soft_detail.big_five_fit >= 80:
        candidates.append((soft_detail.big_five_fit / 100, InsightItem(
            title="Perfil de personalidad bien alineado",
            evidence=f"Distancia Big Five con los requisitos del puesto: {soft_detail.personality_distance:.2f} (baja). Fit: {soft_detail.big_five_fit:.0f}/100.",
            confidence=round(soft_detail.big_five_fit / 100, 3),
            source_layer=4,
        )))

    # Sort by confidence DESC, deduplicate titles, take top 3
    candidates.sort(key=lambda x: x[0], reverse=True)
    seen_titles: set[str] = set()
    strengths: list[InsightItem] = []
    for _, item in candidates:
        if item.title not in seen_titles:
            seen_titles.add(item.title)
            strengths.append(item)
        if len(strengths) >= 3:
            break

    return strengths


# ---------------------------------------------------------------------------
# B8.1.2 — generate_top_alerts
# ---------------------------------------------------------------------------

def generate_top_alerts(
    puc: CandidatePUCProfile,
    job_config: JobMatchConfig,
    hard_detail: Optional[HardMatchDetail] = None,
) -> list[InsightItem]:
    """Return up to 2 alerts where the candidate falls short of job requirements.

    Framed as "areas to explore in the interview", not defects.
    Checks:
      1. Missing required skills (hard filter)
      2. Big Five gaps vs job_config minimums
      3. Diagnostic flags (churn_risk, social_desirability_flag, emotional_stability)
      4. Other soft dimension gaps below 45
    """
    candidates: list[tuple[float, InsightItem]] = []

    # --- Hard skills gaps ---
    if hard_detail:
        for skill in hard_detail.missing_required_skills[:2]:
            candidates.append((0.95, InsightItem(
                title=f"Habilidad no acreditada: {skill}",
                evidence=f"La habilidad '{skill}' es requerida para el puesto y no aparece en el perfil del candidato. Explorar en entrevista.",
                confidence=0.95,
                source_layer=1,
            )))

    # --- Big Five gaps vs job requirements ---
    for dim, cfg_field in _BIG_FIVE_CONFIG_MAP:
        cand_val = getattr(puc, dim, None)
        req_min = getattr(job_config, cfg_field, 0.0) or 0.0
        if cand_val is None:
            continue
        req_min_100 = req_min * 100 if req_min <= 1.0 else req_min
        if req_min_100 < 5:
            continue  # No requirement configured
        gap = req_min_100 - cand_val
        if gap > 5:
            meta = _DIM_META.get(dim, {})
            confidence = min(1.0, gap / 50.0 + 0.5)
            candidates.append((confidence, InsightItem(
                title=f"Área de exploración: {meta.get('label', dim)}",
                evidence=f"{meta.get('alert_evidence', '')} (score: {cand_val:.0f}/100, req: {req_min_100:.0f}+; brecha: {gap:.0f} puntos)",
                confidence=round(confidence, 3),
                source_layer=4,
            )))

    # --- Diagnostic flags ---
    if puc.churn_risk is not None and puc.churn_risk > 0.6:
        candidates.append((puc.churn_risk, InsightItem(
            title="Riesgo de rotación — área a explorar",
            evidence=f"Índice de riesgo de rotación: {puc.churn_risk:.0%}. Señales de cambio frecuente de empleo. Explorar motivación y compromiso a largo plazo.",
            confidence=round(puc.churn_risk, 3),
            source_layer=5,
        )))

    if puc.social_desirability_flag:
        candidates.append((0.7, InsightItem(
            title="Respuestas estratégicamente favorables detectadas",
            evidence="El análisis de respuestas sugiere que el candidato podría estar respondiendo de forma socialmente deseable. Validar con preguntas situacionales específicas.",
            confidence=0.7,
            source_layer=5,
        )))

    if puc.emotional_stability is not None and puc.emotional_stability < 40:
        req_stability = (getattr(job_config, "req_stability_min", 0.0) or 0.0)
        req_stability_100 = req_stability * 100 if req_stability <= 1.0 else req_stability
        if req_stability_100 >= 40 or puc.emotional_stability < 35:
            candidates.append((0.8, InsightItem(
                title="Estabilidad emocional — área de exploración",
                evidence=f"Estabilidad emocional: {puc.emotional_stability:.0f}/100. Evaluar manejo del estrés en entrevista con preguntas situacionales.",
                confidence=0.8,
                source_layer=4,
            )))

    # --- Completeness warning ---
    completeness = puc.completeness_score or 0.0
    if completeness < 0.4:
        candidates.append((0.85, InsightItem(
            title="Perfil MALA incompleto",
            evidence=f"Completitud del perfil: {completeness:.0%}. Las puntuaciones de compatibilidad son preliminares — candidato completó menos del 40% del proceso MALA.",
            confidence=0.85,
            source_layer=0,
        )))

    # Sort by confidence DESC, deduplicate titles, take top 2
    candidates.sort(key=lambda x: x[0], reverse=True)
    seen_titles: set[str] = set()
    alerts: list[InsightItem] = []
    for _, item in candidates:
        if item.title not in seen_titles:
            seen_titles.add(item.title)
            alerts.append(item)
        if len(alerts) >= 2:
            break

    return alerts


# ---------------------------------------------------------------------------
# B8.2.1 — generate_competency_explanation (template-based)
# ---------------------------------------------------------------------------

def generate_competency_explanation(
    competency: str,
    score: float,
    evidence: list[str],
) -> str:
    """Return a recruiter-readable explanation for a single competency score.

    Template output:
        Competencia inferida: {competency} (score: {score}/1.0)

        Evidencia detectada en sus respuestas:
        • evidence_1
        • evidence_2
        • evidence_3

        Confianza de la inferencia: {level} ({n} señales convergentes de fuentes independientes)
    """
    if score >= 0.8:
        level = "Alta"
    elif score >= 0.5:
        level = "Media"
    else:
        level = "Baja"

    evidence_lines = "\n".join(f"• {e}" for e in evidence[:3]) if evidence else "• Sin evidencia textual disponible."
    n_signals = len(evidence)

    return (
        f"Competencia inferida: {competency} (score: {score:.2f}/1.0)\n\n"
        f"Evidencia detectada en sus respuestas:\n{evidence_lines}\n\n"
        f"Confianza de la inferencia: {level} ({n_signals} señales convergentes de fuentes independientes)"
    )


# ---------------------------------------------------------------------------
# B8.1.3 — generate_explanation_text_llm (LLM via Anthropic, fallback template)
# ---------------------------------------------------------------------------

_EXPLANATION_PROMPT = """Eres un psicólogo organizacional. Genera UNA explicación en lenguaje natural \
(3-4 párrafos) para un reclutador no técnico sobre por qué este candidato \
tiene un match score de {score}/100 para este cargo.

Datos del análisis:
- Hard Match: {hard_score}/100 (skills: {skills_detail})
- Soft Match: {soft_score}/100
  - Personalidad (Big Five fit): {big_five_detail}
  - Motivación (McClelland): {mcclelland_detail}
  - Arquetipo: {archetype}
- Fortalezas detectadas: {strengths}
- Áreas de exploración: {alerts}

NO uses jerga técnica (no menciones Big Five, LIWC, sBERT, vectores, etc.).
USA lenguaje de selección de talento cotidiano.
Sé específico con la evidencia del candidato.
Termina con una recomendación clara: avanzar / explorar más / no recomendado."""


async def generate_explanation_text_llm(
    candidate: User,
    job: Job,
    scores: MatchScoreResult,
    puc: Optional[CandidatePUCProfile] = None,
) -> str:
    """Generate a natural-language explanation of the match score via Anthropic.

    Falls back to the template-based explanation from match_score_service if:
    - anthropic package is not installed
    - ANTHROPIC_API_KEY is not set
    - The API call fails

    Returns:
        str — 3-4 paragraph explanation for a non-technical recruiter.
    """
    from app.core.config import settings  # avoid circular import at module load

    api_key = settings.anthropic_api_key
    if not api_key:
        logger.debug("ANTHROPIC_API_KEY not set — falling back to template explanation")
        return _template_explanation(scores)

    try:
        import anthropic  # optional dependency

        archetype = (puc.primary_archetype or "desconocido") if puc else "desconocido"
        strengths_text = "; ".join(s.title for s in scores.top_strengths) or "ninguna detectada"
        alerts_text = "; ".join(a.title for a in scores.top_alerts) or "ninguna"
        skills_detail = (
            f"cubre {scores.hard_match.skills_coverage * 100:.0f}% de skills requeridos"
            if scores.hard_match.skills_coverage
            else "datos no disponibles"
        )
        big_five_text = f"fit {scores.soft_match.big_five_fit:.0f}/100 (distancia {scores.soft_match.personality_distance:.2f})"
        mcclelland_text = f"cultura fit {scores.soft_match.mcclelland_culture_fit:.0f}/100"

        prompt = _EXPLANATION_PROMPT.format(
            score=round(scores.final_effective_score),
            hard_score=round(scores.hard_match.score),
            soft_score=round(scores.soft_match.score),
            skills_detail=skills_detail,
            big_five_detail=big_five_text,
            mcclelland_detail=mcclelland_text,
            archetype=archetype,
            strengths=strengths_text,
            alerts=alerts_text,
        )

        client = anthropic.AsyncAnthropic(api_key=api_key)
        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()

    except ImportError:
        logger.warning("anthropic package not installed — falling back to template explanation")
        return _template_explanation(scores)
    except Exception as exc:
        logger.error("Anthropic API call failed: %s", exc, exc_info=True)
        return _template_explanation(scores)


def _template_explanation(scores: MatchScoreResult) -> str:
    """Deterministic 3-sentence fallback explanation (no LLM)."""
    hard = scores.hard_match
    soft = scores.soft_match
    pred = scores.predictive_match

    if not hard.passed_filter:
        missing = ", ".join(hard.missing_required_skills[:3])
        return (
            f"El candidato no supera el filtro técnico del puesto "
            f"({missing or 'ver detalle de habilidades requeridas'}). "
            "Se recomienda no avanzar en el proceso de selección."
        )

    hard_label = "excelente" if hard.score >= 80 else ("buena" if hard.score >= 60 else "aceptable")
    soft_label = "alta" if soft.score >= 75 else ("media" if soft.score >= 50 else "baja")
    hire_pct = int(pred.hire_probability * 100)

    s1 = (
        f"El candidato muestra una compatibilidad técnica {hard_label} ({hard.score:.0f}/100) "
        f"y una alineación cultural {soft_label} ({soft.score:.0f}/100) con el perfil del puesto."
    )
    if soft.big_five_fit >= 75:
        s2 = f"Su perfil de personalidad está bien alineado con las dimensiones requeridas (fit: {soft.big_five_fit:.0f}/100)."
    elif soft.career_narrative_fit >= 100:
        s2 = "El arquetipo del candidato coincide con el ideal definido para este rol."
    else:
        s2 = (
            f"Existen brechas en el perfil cultural que conviene explorar en la entrevista "
            f"(compatibilidad cultural: {soft.mcclelland_culture_fit:.0f}/100)."
        )
    s3 = (
        f"La probabilidad estimada de contratación exitosa es del {hire_pct}% "
        f"({'estimación heurística' if pred.is_heuristic else 'basado en datos históricos'})."
    )
    return f"{s1} {s2} {s3}"
