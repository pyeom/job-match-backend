"""
B7.2 + B7.3 — Match Score Service

Implements the Match Score Engine:
  - compute_hard_match()       : hard filter + skills/exp/edu/lang scoring
  - compute_soft_match()       : Big Five fit + McClelland + appraisal + narrative
  - compute_predictive_match() : heuristic hire/retention probability
  - generate_insights()        : template-based strengths and alerts (no LLM)
  - generate_interview_guide() : template-based STAR questions (no LLM)
  - generate_explanation_text(): 2-3 sentence plain-text summary (no LLM)
  - compute_final_score()      : orchestrator — loads data, runs all sub-computations,
                                  persists MatchScore, returns MatchScoreResult
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mala import (
    CandidatePUCProfile,
    CompanyOrgProfile,
    JobMatchConfig,
    MatchScore,
)
from app.models.job import Job
from app.models.user import User
from app.repositories.match_score_repository import MatchScoreRepository
from app.repositories.puc_profile_repository import PUCProfileRepository
from app.repositories.job_match_config_repository import JobMatchConfigRepository
from app.repositories.company_org_profile_repository import CompanyOrgProfileRepository
from app.core.config import settings
from app.schemas.match_score import (
    HardMatchDetail,
    InsightItem,
    InterviewQuestion,
    MatchScoreResult,
    PredictiveMatchDetail,
    SoftMatchDetail,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------
_match_score_repo = MatchScoreRepository()
_puc_repo = PUCProfileRepository()
_config_repo = JobMatchConfigRepository()
_org_repo = CompanyOrgProfileRepository()

# ---------------------------------------------------------------------------
# Education level scoring table
# ---------------------------------------------------------------------------
EDU_SCORES: dict[str, float] = {
    "secundaria": 0.3,
    "técnico": 0.6,
    "universitario": 0.8,
    "postgrado": 0.9,
    "doctorado": 1.0,
}

# Ordered list used to determine if a candidate is below required level
EDU_ORDER: list[str] = [
    "secundaria",
    "técnico",
    "universitario",
    "postgrado",
    "doctorado",
]

# ---------------------------------------------------------------------------
# Archetype emoji map — used in ranking responses
# ---------------------------------------------------------------------------
ARCHETYPE_EMOJIS: dict[str, str] = {
    "El Constructor": "🏗️",
    "El Ejecutor": "🎯",
    "El Conector": "🤝",
    "El Explorador": "🔭",
    "El Guardián": "🛡️",
    "El Mentor": "🌱",
    "El Innovador": "💡",
    "El Analista": "📊",
    "El Estratega": "♟️",
}

# ---------------------------------------------------------------------------
# Interview question template bank (~15 templates keyed by gap type)
# ---------------------------------------------------------------------------
_QUESTION_BANK: dict[str, InterviewQuestion] = {
    "big_five_low_conscientiousness": InterviewQuestion(
        question="Cuéntame sobre una ocasión en que tuviste que gestionar múltiples proyectos con plazos ajustados. ¿Cómo organizaste tu trabajo y qué resultado obtuviste?",
        rationale="Evalúa la capacidad de organización y seguimiento ante la baja consciencia detectada.",
        what_to_look_for="Sistemas concretos de priorización, cumplimiento de plazos, aprendizaje ante retrasos.",
        gap_addressed="conscientiousness_below_minimum",
    ),
    "big_five_low_openness": InterviewQuestion(
        question="Describe una situación donde tuviste que adoptar un nuevo proceso o tecnología con la que no estabas familiarizado/a. ¿Qué hiciste?",
        rationale="Evalúa flexibilidad y disposición al aprendizaje dada la apertura por debajo del umbral requerido.",
        what_to_look_for="Actitud proactiva, velocidad de aprendizaje, ausencia de resistencia al cambio.",
        gap_addressed="openness_below_minimum",
    ),
    "big_five_low_extraversion": InterviewQuestion(
        question="Cuéntame sobre una vez que tuviste que liderar una reunión con personas de distintos equipos o jerarquías. ¿Cómo te preparaste y cómo fue?",
        rationale="Evalúa habilidades de comunicación y presencia en espacios sociales dado el bajo nivel de extraversión.",
        what_to_look_for="Preparación previa, capacidad de facilitar conversaciones, manejo de la incomodidad.",
        gap_addressed="extraversion_below_minimum",
    ),
    "big_five_low_agreeableness": InterviewQuestion(
        question="Dame un ejemplo de cuando tuviste un conflicto con un compañero de trabajo. ¿Cómo lo manejaste y cuál fue el resultado?",
        rationale="Evalúa habilidades de resolución de conflictos y empatía ante la baja amabilidad detectada.",
        what_to_look_for="Escucha activa, búsqueda de soluciones ganar-ganar, ausencia de escalación innecesaria.",
        gap_addressed="agreeableness_below_minimum",
    ),
    "big_five_low_stability": InterviewQuestion(
        question="Recuérdame un período de alta presión o incertidumbre en un trabajo anterior. ¿Cómo gestionaste el estrés y mantuviste tu rendimiento?",
        rationale="Evalúa resiliencia emocional dado el bajo nivel de estabilidad emocional detectado.",
        what_to_look_for="Estrategias de regulación emocional, rendimiento sostenido, aprendizaje de la experiencia.",
        gap_addressed="stability_below_minimum",
    ),
    "high_churn_risk": InterviewQuestion(
        question="¿Cuáles son los factores que te han llevado a cambiar de trabajo en el pasado? ¿Qué necesitarías para comprometerte con una empresa a largo plazo?",
        rationale="Explora patrones de rotación y motivadores de retención ante el alto riesgo de churn detectado.",
        what_to_look_for="Razones constructivas de salida, claridad sobre necesidades de permanencia, plan de carrera realista.",
        gap_addressed="high_churn_risk",
    ),
    "skills_gap": InterviewQuestion(
        question="¿Cuál es tu nivel actual con [SKILL_FALTANTE] y qué pasos concretos estás tomando para desarrollarlo?",
        rationale="Evalúa el plan de desarrollo ante las habilidades requeridas no acreditadas.",
        what_to_look_for="Autodidactismo, recursos activos de aprendizaje, plazo realista para alcanzar el nivel requerido.",
        gap_addressed="missing_required_skills",
    ),
    "career_narrative_mismatch": InterviewQuestion(
        question="¿Por qué este rol en particular encaja con la trayectoria que quieres construir? ¿Cómo lo ves dentro de tu plan de carrera a 3-5 años?",
        rationale="Verifica alineación entre el perfil narrativo del candidato y las demandas del puesto.",
        what_to_look_for="Claridad sobre motivación intrínseca, conexión lógica con la trayectoria previa, visión de largo plazo.",
        gap_addressed="career_narrative_mismatch",
    ),
    "low_analytical_thinking": InterviewQuestion(
        question="Cuéntame sobre un problema complejo que tuviste que descomponer para resolverlo. ¿Cómo estructuraste el análisis y qué herramientas usaste?",
        rationale="Evalúa capacidad de análisis estructurado ante el bajo pensamiento analítico detectado.",
        what_to_look_for="Metodología clara, uso de datos, capacidad de síntesis y priorización.",
        gap_addressed="low_analytical_thinking",
    ),
    "low_leadership": InterviewQuestion(
        question="Descríbeme una situación donde influiste en las decisiones de tu equipo sin tener autoridad formal. ¿Cuál fue el resultado?",
        rationale="Evalúa liderazgo informal dado el bajo puntaje de liderazgo en el perfil.",
        what_to_look_for="Influencia por credibilidad, alineación de objetivos, resultados tangibles.",
        gap_addressed="low_leadership_score",
    ),
    "low_collaboration": InterviewQuestion(
        question="¿Puedes darme un ejemplo de un proyecto donde la colaboración entre equipos fue crítica para el éxito? ¿Cuál fue tu rol?",
        rationale="Evalúa habilidades colaborativas dado el bajo puntaje de colaboración detectado.",
        what_to_look_for="Rol activo en la coordinación, comunicación entre equipos, reconocimiento del aporte ajeno.",
        gap_addressed="low_collaboration_score",
    ),
    "low_adaptability": InterviewQuestion(
        question="Cuéntame sobre la situación de mayor cambio que hayas vivido en tu carrera. ¿Cómo te adaptaste y qué aprendiste de esa experiencia?",
        rationale="Evalúa adaptabilidad ante entornos cambiantes dado el bajo puntaje detectado.",
        what_to_look_for="Velocidad de adaptación, aprendizaje iterativo, actitud positiva ante la incertidumbre.",
        gap_addressed="low_adaptability_score",
    ),
    "low_written_communication": InterviewQuestion(
        question="¿Puedes mostrarme o describir un documento técnico o informe que hayas elaborado recientemente? ¿Cómo te aseguras de que tu comunicación escrita sea clara?",
        rationale="Evalúa comunicación escrita ante el bajo nivel detectado en el perfil.",
        what_to_look_for="Claridad, estructura lógica, adaptación al público objetivo.",
        gap_addressed="low_written_communication",
    ),
    "low_integrity": InterviewQuestion(
        question="¿Puedes compartir un momento en que tuviste que elegir entre lo fácil y lo correcto en el contexto de trabajo? ¿Qué decidiste y por qué?",
        rationale="Evalúa integridad y alineación ética ante el bajo puntaje de integridad detectado.",
        what_to_look_for="Transparencia en la decisión, consistencia con valores declarados, ausencia de oportunismo.",
        gap_addressed="low_integrity_score",
    ),
    "low_resilience": InterviewQuestion(
        question="Cuéntame sobre un fracaso profesional importante y cómo lo procesaste. ¿Qué cambió en ti después de esa experiencia?",
        rationale="Evalúa resiliencia y capacidad de recuperación ante el bajo puntaje detectado.",
        what_to_look_for="Reflexión genuina, aprendizaje concreto, ausencia de victimización excesiva.",
        gap_addressed="low_resilience_score",
    ),
}


# ---------------------------------------------------------------------------
# B7.2.1 — compute_hard_match
# ---------------------------------------------------------------------------

def compute_hard_match(
    candidate: dict,
    config: JobMatchConfig,
) -> HardMatchDetail:
    """Compute the hard filter score for a candidate against a job config.

    Args:
        candidate: Dict with keys skills (list[str]), experience_years (int),
                   education_level (str), languages (list[str]).
        config:    JobMatchConfig ORM instance.

    Returns:
        HardMatchDetail with score and sub-scores.
    """
    candidate_skills: list[str] = [s.lower() for s in (candidate.get("skills") or [])]
    experience_years: int = int(candidate.get("experience_years") or 0)
    education_level: str = (candidate.get("education_level") or "").lower()
    candidate_languages: list[str] = [l.lower() for l in (candidate.get("languages") or [])]

    required_skills: list[str] = [s.lower() for s in (config.hard_skills_required or [])]
    desired_skills: list[str] = [s.lower() for s in (config.hard_skills_desired or [])]
    all_required = required_skills  # Only required skills count for coverage

    # Hard filter: missing any required skill OR experience below minimum
    missing_required = [s for s in required_skills if s not in candidate_skills]
    min_exp = config.min_experience_years or 0

    if missing_required or experience_years < min_exp:
        return HardMatchDetail(
            score=0.0,
            passed_filter=False,
            skills_coverage=0.0,
            experience_score=0.0,
            education_score=0.0,
            language_score=0.0,
            missing_required_skills=missing_required,
        )

    # Skills coverage (required + desired)
    all_skills = list(set(required_skills + desired_skills))
    if all_skills:
        skills_coverage = len([s for s in all_skills if s in candidate_skills]) / len(all_skills)
    else:
        skills_coverage = 1.0

    # Experience score
    exp_score = min(experience_years / max(min_exp, 1), 1.0)

    # Education score
    base_edu = EDU_SCORES.get(education_level, 0.5)
    required_edu = (config.required_education_level or "").lower()
    if required_edu and required_edu in EDU_ORDER and education_level in EDU_ORDER:
        cand_idx = EDU_ORDER.index(education_level)
        req_idx = EDU_ORDER.index(required_edu)
        if cand_idx < req_idx:
            base_edu = base_edu / 2.0
    edu_score = base_edu

    # Language score
    req_languages: list[str] = [l.lower() for l in (config.required_languages or [])]
    if req_languages:
        lang_score = len([l for l in req_languages if l in candidate_languages]) / len(req_languages)
    else:
        lang_score = 1.0

    hard_score = (
        skills_coverage * 0.40
        + exp_score * 0.25
        + edu_score * 0.20
        + lang_score * 0.15
    ) * 100.0

    return HardMatchDetail(
        score=round(hard_score, 2),
        passed_filter=True,
        skills_coverage=round(skills_coverage, 4),
        experience_score=round(exp_score, 4),
        education_score=round(edu_score, 4),
        language_score=round(lang_score, 4),
        missing_required_skills=[],
    )


# ---------------------------------------------------------------------------
# B7.2.2 — compute_soft_match
# ---------------------------------------------------------------------------

def compute_soft_match(
    candidate_puc: CandidatePUCProfile,
    job_config: JobMatchConfig,
    org_profile: CompanyOrgProfile | None,
) -> SoftMatchDetail:
    """Compute the soft (personality / culture) match score.

    Args:
        candidate_puc: CandidatePUCProfile ORM instance (fields may be None).
        job_config:    JobMatchConfig ORM instance.
        org_profile:   CompanyOrgProfile ORM instance or None.

    Returns:
        SoftMatchDetail with score and sub-scores.
    """
    # ------------------------------------------------------------------
    # 1. Big Five fit
    # ------------------------------------------------------------------
    bf_fields = [
        (candidate_puc.openness, job_config.req_openness_min or 0.0),
        (candidate_puc.conscientiousness, job_config.req_conscientiousness_min or 0.0),
        (candidate_puc.extraversion, job_config.req_extraversion_min or 0.0),
        (candidate_puc.agreeableness, job_config.req_agreeableness_min or 0.0),
        (candidate_puc.emotional_stability, job_config.req_stability_min or 0.0),
    ]

    # Check if candidate has any Big Five data
    bf_values = [v for v, _ in bf_fields if v is not None]
    if not bf_values:
        big_five_fit = 50.0
        euclidean_dist = 0.0
    else:
        gaps = []
        for cand_val, req_min in bf_fields:
            val = cand_val if cand_val is not None else 50.0  # neutral fallback per dimension
            gap = max(0.0, req_min - val)
            gaps.append(gap)
        euclidean_dist = math.sqrt(sum(g ** 2 for g in gaps)) / 100.0
        big_five_fit = max(0.0, 1.0 - euclidean_dist) * 100.0

    # ------------------------------------------------------------------
    # 2. McClelland / culture fit
    # ------------------------------------------------------------------
    if org_profile is not None and org_profile.affiliation_vs_achievement is not None:
        aff_vs_ach = org_profile.affiliation_vs_achievement
        n_aff = candidate_puc.n_aff if candidate_puc.n_aff is not None else 0.5
        n_ach = candidate_puc.n_ach if candidate_puc.n_ach is not None else 0.5

        if aff_vs_ach > 0.6:
            mcclelland_fit = n_aff * 100.0
        elif aff_vs_ach < 0.4:
            mcclelland_fit = n_ach * 100.0
        else:
            mcclelland_fit = ((n_aff + n_ach) / 2.0) * 100.0
    else:
        mcclelland_fit = 50.0

    # ------------------------------------------------------------------
    # 3. Appraisal / anti-profile fit
    # ------------------------------------------------------------------
    if org_profile is not None and org_profile.anti_profile_signals:
        anti_signals: dict = org_profile.anti_profile_signals or {}
        penalty = 0.0

        # Map threshold keys to PUC profile fields
        _ANTI_FIELD_MAP: dict[str, str] = {
            "conscientiousness_max": "conscientiousness",
            "agreeableness_min": "agreeableness",
            "extraversion_min": "extraversion",
            "openness_min": "openness",
            "stability_min": "emotional_stability",
        }

        for threshold_key, threshold_val in anti_signals.items():
            field_name = _ANTI_FIELD_MAP.get(threshold_key)
            if field_name is None:
                continue
            cand_val = getattr(candidate_puc, field_name, None)
            if cand_val is None:
                continue

            # Normalize candidate value to 0-1 if stored as 0-100
            norm_val = cand_val / 100.0 if cand_val > 1.0 else cand_val

            if threshold_key.endswith("_max") and norm_val > threshold_val:
                penalty += (norm_val - threshold_val) * 50
            elif threshold_key.endswith("_min") and norm_val < threshold_val:
                penalty += (threshold_val - norm_val) * 50

        appraisal_fit = max(0.0, 100.0 - penalty)
    else:
        appraisal_fit = 70.0  # neutral-positive when no org profile

    # ------------------------------------------------------------------
    # 4. Career narrative fit
    # ------------------------------------------------------------------
    if (
        candidate_puc.primary_archetype
        and job_config.ideal_archetype
        and candidate_puc.primary_archetype == job_config.ideal_archetype
    ):
        career_fit = 100.0
    elif candidate_puc.churn_risk is not None and candidate_puc.churn_risk > 0.7:
        career_fit = 40.0
    else:
        career_fit = 65.0  # neutral

    # ------------------------------------------------------------------
    # Weighted soft score
    # ------------------------------------------------------------------
    soft_score = (
        big_five_fit * 0.30
        + mcclelland_fit * 0.25
        + appraisal_fit * 0.25
        + career_fit * 0.20
    )

    return SoftMatchDetail(
        score=round(soft_score, 2),
        big_five_fit=round(big_five_fit, 2),
        mcclelland_culture_fit=round(mcclelland_fit, 2),
        appraisal_values_fit=round(appraisal_fit, 2),
        career_narrative_fit=round(career_fit, 2),
        personality_distance=round(euclidean_dist, 4),
    )


# ---------------------------------------------------------------------------
# B7.2.3 — compute_predictive_match
# ---------------------------------------------------------------------------

def compute_predictive_match(
    features: dict,
    outcomes_count: int,
) -> PredictiveMatchDetail:
    """Compute predictive match score (heuristic when outcomes_count < 50).

    Args:
        features: Dict with hard_match_score (float) and soft_match_score (float).
        outcomes_count: Number of historical HiringOutcome rows for this job.

    Returns:
        PredictiveMatchDetail.
    """
    is_heuristic = outcomes_count < 50

    # Heuristic approach (always used until sufficient outcomes exist)
    hard_score = float(features.get("hard_match_score", 0.0))
    soft_score = float(features.get("soft_match_score", 0.0))
    base = (hard_score * 0.5 + soft_score * 0.5) / 100.0

    hire_probability = min(0.95, base * 0.85 + 0.1)
    retention_12m = min(0.95, base * 0.70 + 0.2)
    score = (hire_probability * 0.6 + retention_12m * 0.4) * 100.0

    return PredictiveMatchDetail(
        score=round(score, 2),
        hire_probability=round(hire_probability, 4),
        retention_12m_probability=round(retention_12m, 4),
        is_heuristic=is_heuristic,
    )


# ---------------------------------------------------------------------------
# B7.3.1 — generate_insights (template-based, no LLM)
# ---------------------------------------------------------------------------

def generate_insights(
    candidate_puc: CandidatePUCProfile,
    hard_detail: HardMatchDetail,
    soft_detail: SoftMatchDetail,
) -> tuple[list[InsightItem], list[InsightItem]]:
    """Generate up to 3 strengths and 2 alerts from PUC values and match details.

    Template-based, deterministic. No LLM calls.

    Returns:
        Tuple of (strengths, alerts) sorted by confidence descending.
    """
    strengths: list[InsightItem] = []
    alerts: list[InsightItem] = []

    # --- Strengths ---

    # High conscientiousness
    if candidate_puc.conscientiousness is not None and candidate_puc.conscientiousness > 70:
        strengths.append(InsightItem(
            title="Alta autogestión y rigor",
            evidence=f"Consciencia: {candidate_puc.conscientiousness:.0f}/100 — perfil de alta organización y seguimiento.",
            confidence=min(1.0, candidate_puc.conscientiousness / 100.0),
            source_layer=4,
        ))

    # Big Five personality alignment
    if soft_detail.big_five_fit > 80:
        strengths.append(InsightItem(
            title="Perfil de personalidad alineado",
            evidence=f"Distancia Big Five con los requisitos del puesto: {soft_detail.personality_distance:.2f} (bajo). Fit: {soft_detail.big_five_fit:.0f}/100.",
            confidence=min(1.0, soft_detail.big_five_fit / 100.0),
            source_layer=4,
        ))

    # Strong analytical thinking
    if candidate_puc.analytical_thinking is not None and candidate_puc.analytical_thinking > 70:
        strengths.append(InsightItem(
            title="Pensamiento analítico sólido",
            evidence=f"Pensamiento analítico: {candidate_puc.analytical_thinking:.0f}/100.",
            confidence=min(1.0, candidate_puc.analytical_thinking / 100.0),
            source_layer=3,
        ))

    # Archetype alignment
    if soft_detail.career_narrative_fit >= 100.0:
        strengths.append(InsightItem(
            title="Arquetipo ideal para el rol",
            evidence="El arquetipo del candidato coincide exactamente con el arquetipo ideal definido para esta posición.",
            confidence=0.95,
            source_layer=5,
        ))

    # High skills coverage
    if hard_detail.passed_filter and hard_detail.skills_coverage > 0.85:
        strengths.append(InsightItem(
            title="Cobertura técnica excelente",
            evidence=f"Cubre el {hard_detail.skills_coverage * 100:.0f}% de las habilidades requeridas y deseadas.",
            confidence=hard_detail.skills_coverage,
            source_layer=1,
        ))

    # High agreeableness / collaboration
    if candidate_puc.agreeableness is not None and candidate_puc.agreeableness > 75:
        strengths.append(InsightItem(
            title="Alta colaboración y amabilidad",
            evidence=f"Amabilidad: {candidate_puc.agreeableness:.0f}/100 — favorece la dinámica de equipo.",
            confidence=min(1.0, candidate_puc.agreeableness / 100.0),
            source_layer=4,
        ))

    # High openness
    if candidate_puc.openness is not None and candidate_puc.openness > 75:
        strengths.append(InsightItem(
            title="Alta apertura e innovación",
            evidence=f"Apertura: {candidate_puc.openness:.0f}/100 — favorece la adaptación y la creatividad.",
            confidence=min(1.0, candidate_puc.openness / 100.0),
            source_layer=4,
        ))

    # --- Alerts ---

    # Missing required skills
    for skill in hard_detail.missing_required_skills[:2]:
        alerts.append(InsightItem(
            title=f"Habilidad requerida no acreditada: {skill}",
            evidence=f"La habilidad '{skill}' es requerida para este puesto y no aparece en el perfil del candidato.",
            confidence=0.95,
            source_layer=1,
        ))

    # High churn risk
    if candidate_puc.churn_risk is not None and candidate_puc.churn_risk > 0.6:
        alerts.append(InsightItem(
            title="Riesgo de rotación detectado",
            evidence=f"Índice de riesgo de rotación: {candidate_puc.churn_risk:.0%}. Historial o señales de cambio frecuente de trabajo.",
            confidence=candidate_puc.churn_risk,
            source_layer=5,
        ))

    # Low stability / emotional instability
    if candidate_puc.emotional_stability is not None and candidate_puc.emotional_stability < 40:
        alerts.append(InsightItem(
            title="Estabilidad emocional por debajo del umbral",
            evidence=f"Estabilidad emocional: {candidate_puc.emotional_stability:.0f}/100. Puede impactar el rendimiento bajo presión.",
            confidence=min(1.0, (50.0 - candidate_puc.emotional_stability) / 50.0),
            source_layer=4,
        ))

    # Social desirability bias detected
    if candidate_puc.social_desirability_flag:
        alerts.append(InsightItem(
            title="Posible sesgo de deseabilidad social",
            evidence="El análisis de respuestas sugiere que el candidato puede estar respondiendo de forma estratégicamente favorable. Interpretar con cautela.",
            confidence=0.7,
            source_layer=5,
        ))

    # Low conscientiousness (if not in strengths)
    if candidate_puc.conscientiousness is not None and candidate_puc.conscientiousness < 40:
        alerts.append(InsightItem(
            title="Baja autogestión detectada",
            evidence=f"Consciencia: {candidate_puc.conscientiousness:.0f}/100. Puede necesitar supervisión adicional.",
            confidence=min(1.0, (50.0 - candidate_puc.conscientiousness) / 50.0),
            source_layer=4,
        ))

    # Low PUC completeness
    if (candidate_puc.completeness_score or 0.0) < 0.4:
        alerts.append(InsightItem(
            title="Perfil MALA incompleto",
            evidence=f"Completitud del perfil: {(candidate_puc.completeness_score or 0.0):.0%}. Las puntuaciones de compatibilidad son preliminares.",
            confidence=0.85,
            source_layer=0,
        ))

    # Sort by confidence descending and cap
    strengths.sort(key=lambda x: x.confidence, reverse=True)
    alerts.sort(key=lambda x: x.confidence, reverse=True)

    return strengths[:3], alerts[:2]


# ---------------------------------------------------------------------------
# B7.3.2 — generate_interview_guide (template-based, no LLM)
# ---------------------------------------------------------------------------

def generate_interview_guide(
    candidate_puc: CandidatePUCProfile,
    job_config: JobMatchConfig,
    soft_detail: SoftMatchDetail,
) -> list[InterviewQuestion]:
    """Generate up to 5 STAR interview questions targeting detected gaps.

    Template-based, deterministic. No LLM calls.

    Returns:
        List of up to 5 InterviewQuestion instances ordered by gap relevance.
    """
    selected: list[tuple[str, float]] = []  # (question_key, priority)

    # Big Five gaps
    bf_gaps = [
        ("conscientiousness", candidate_puc.conscientiousness, job_config.req_conscientiousness_min or 0.0, "big_five_low_conscientiousness"),
        ("openness", candidate_puc.openness, job_config.req_openness_min or 0.0, "big_five_low_openness"),
        ("extraversion", candidate_puc.extraversion, job_config.req_extraversion_min or 0.0, "big_five_low_extraversion"),
        ("agreeableness", candidate_puc.agreeableness, job_config.req_agreeableness_min or 0.0, "big_five_low_agreeableness"),
        ("emotional_stability", candidate_puc.emotional_stability, job_config.req_stability_min or 0.0, "big_five_low_stability"),
    ]
    for _dim, cand_val, req_min, key in bf_gaps:
        val = cand_val if cand_val is not None else 50.0
        gap = max(0.0, req_min - val)
        if gap > 5:
            selected.append((key, gap))

    # Churn risk
    if candidate_puc.churn_risk is not None and candidate_puc.churn_risk > 0.6:
        selected.append(("high_churn_risk", candidate_puc.churn_risk * 100))

    # Skills gap (first missing required skill)
    if job_config.hard_skills_required:
        selected.append(("skills_gap", 80.0))

    # Career narrative mismatch
    if soft_detail.career_narrative_fit < 65:
        selected.append(("career_narrative_mismatch", 100.0 - soft_detail.career_narrative_fit))

    # Low analytical thinking
    if candidate_puc.analytical_thinking is not None and candidate_puc.analytical_thinking < 50:
        selected.append(("low_analytical_thinking", 50.0 - candidate_puc.analytical_thinking))

    # Low leadership
    if candidate_puc.leadership_score is not None and candidate_puc.leadership_score < 50:
        selected.append(("low_leadership", 50.0 - candidate_puc.leadership_score))

    # Low collaboration
    if candidate_puc.collaboration_score is not None and candidate_puc.collaboration_score < 50:
        selected.append(("low_collaboration", 50.0 - candidate_puc.collaboration_score))

    # Low adaptability
    if candidate_puc.adaptability_score is not None and candidate_puc.adaptability_score < 50:
        selected.append(("low_adaptability", 50.0 - candidate_puc.adaptability_score))

    # Low written communication
    if candidate_puc.written_communication is not None and candidate_puc.written_communication < 50:
        selected.append(("low_written_communication", 50.0 - candidate_puc.written_communication))

    # Low resilience
    if candidate_puc.resilience_score is not None and candidate_puc.resilience_score < 50:
        selected.append(("low_resilience", 50.0 - candidate_puc.resilience_score))

    # Low integrity
    if candidate_puc.integrity_score is not None and candidate_puc.integrity_score < 50:
        selected.append(("low_integrity", 50.0 - candidate_puc.integrity_score))

    # Sort by priority descending, deduplicate keys, take top 5
    seen: set[str] = set()
    guide: list[InterviewQuestion] = []
    for key, _priority in sorted(selected, key=lambda x: x[1], reverse=True):
        if key in seen or key not in _QUESTION_BANK:
            continue
        seen.add(key)
        guide.append(_QUESTION_BANK[key])
        if len(guide) >= 5:
            break

    # If fewer than 5 selected, pad with default questions that were not yet added
    _DEFAULT_ORDER = [
        "career_narrative_mismatch",
        "big_five_low_conscientiousness",
        "big_five_low_openness",
        "high_churn_risk",
        "skills_gap",
    ]
    for fallback_key in _DEFAULT_ORDER:
        if len(guide) >= 5:
            break
        if fallback_key not in seen and fallback_key in _QUESTION_BANK:
            seen.add(fallback_key)
            guide.append(_QUESTION_BANK[fallback_key])

    return guide


# ---------------------------------------------------------------------------
# B7.3.3 — generate_explanation_text (no LLM)
# ---------------------------------------------------------------------------

def generate_explanation_text(
    hard: HardMatchDetail,
    soft: SoftMatchDetail,
    pred: PredictiveMatchDetail,
) -> str:
    """Generate a 2-3 sentence human-readable explanation of the match score.

    Deterministic, template-based. No LLM.
    """
    if not hard.passed_filter:
        missing = ", ".join(hard.missing_required_skills[:3])
        return (
            f"El candidato no supera el filtro duro del puesto: "
            f"le faltan las habilidades requeridas ({missing or 'ver detalle'}) "
            f"o no cumple la experiencia mínima. "
            f"Se recomienda no avanzar en el proceso de selección."
        )

    hard_label = "excelente" if hard.score >= 80 else ("buena" if hard.score >= 60 else "aceptable")
    soft_label = "alta" if soft.score >= 75 else ("media" if soft.score >= 50 else "baja")
    hire_pct = int(pred.hire_probability * 100)

    sentence1 = (
        f"El candidato muestra una compatibilidad técnica {hard_label} "
        f"({hard.score:.0f}/100) y una alineación cultural {soft_label} "
        f"({soft.score:.0f}/100) con el perfil del puesto."
    )

    if soft.big_five_fit >= 75:
        sentence2 = (
            f"Su perfil de personalidad está bien alineado con las dimensiones Big Five requeridas "
            f"(fit: {soft.big_five_fit:.0f}/100)."
        )
    elif soft.career_narrative_fit >= 100:
        sentence2 = "El arquetipo del candidato coincide con el ideal definido para este rol."
    else:
        sentence2 = (
            f"Existen brechas en el perfil de personalidad o cultural que conviene explorar "
            f"en la entrevista (compatibilidad cultural: {soft.mcclelland_culture_fit:.0f}/100)."
        )

    sentence3 = (
        f"La probabilidad estimada de contratación exitosa es del {hire_pct}% "
        f"({'estimación heurística' if pred.is_heuristic else 'basado en datos históricos'})."
    )

    return f"{sentence1} {sentence2} {sentence3}"


# ---------------------------------------------------------------------------
# B7.2.4 — compute_final_score (orchestrator)
# ---------------------------------------------------------------------------

async def compute_final_score(
    db: AsyncSession,
    user_id: UUID,
    job_id: UUID,
) -> MatchScoreResult:
    """Orchestrate the full match score computation.

    Steps:
    1. Load CandidatePUCProfile by user_id
    2. Load JobMatchConfig by job_id
    3. Load CompanyOrgProfile by job's company_id
    4. Build candidate dict from User model
    5. Compute hard, soft, predictive
    6. Compute confidence_multiplier from completeness_score
    7. Compute weighted total and effective score
    8. Generate insights and interview guide
    9. Upsert MatchScore in DB
    10. Return MatchScoreResult

    Args:
        db:      Async database session.
        user_id: UUID of the job-seeker.
        job_id:  UUID of the job.

    Returns:
        MatchScoreResult with all sub-scores and insights.
    """
    # --- 1. Load CandidatePUCProfile ---
    candidate_puc = await _puc_repo.get_by_user_id(db, user_id)
    if candidate_puc is None:
        # Build a minimal empty PUC profile for scoring (all fields None/0)
        candidate_puc = CandidatePUCProfile(
            user_id=user_id,
            completeness_score=0.0,
        )

    # --- 2. Load JobMatchConfig ---
    job_config = await _config_repo.get_by_job_id(db, job_id)
    if job_config is None:
        # Use a minimal default config — all weights equal, no requirements
        job_config = JobMatchConfig(
            job_id=job_id,
            weight_hard=0.50,
            weight_soft=0.30,
            weight_predictive=0.20,
            min_experience_years=0,
            hard_skills_required=[],
            hard_skills_desired=[],
            required_languages=[],
        )

    # --- 3. Load CompanyOrgProfile ---
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    org_profile: CompanyOrgProfile | None = None
    if job is not None:
        org_profile = await _org_repo.get_by_company_id(db, job.company_id)

    # --- 4. Build candidate dict from User ---
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()

    candidate_dict = _build_candidate_dict(user)

    # --- 5. Compute sub-scores ---
    hard_detail = compute_hard_match(candidate_dict, job_config)
    soft_detail = compute_soft_match(candidate_puc, job_config, org_profile)
    predictive_detail = compute_predictive_match(
        features={
            "hard_match_score": hard_detail.score,
            "soft_match_score": soft_detail.score,
        },
        outcomes_count=0,  # No historical outcomes yet — always heuristic
    )

    # --- 6. Confidence multiplier ---
    completeness = candidate_puc.completeness_score if candidate_puc.completeness_score is not None else 0.5
    # Clamp to [0.3, 1.0] so score is never entirely zeroed for low completeness
    confidence_multiplier = max(0.3, min(1.0, completeness))

    # --- 7. Weighted total and effective score ---
    # Fall back to system-level defaults from settings when the job has no config.
    # WHY: weights derived from recruiter validation study (Q1 2026) — see config.py.
    w_hard = job_config.weight_hard or settings.match_score_w_hard
    w_soft = job_config.weight_soft or settings.match_score_w_soft
    w_pred = job_config.weight_predictive or settings.match_score_w_predictive

    total_score = (
        hard_detail.score * w_hard
        + soft_detail.score * w_soft
        + predictive_detail.score * w_pred
    )
    final_effective_score = total_score * confidence_multiplier

    # --- 8. Insights + interview guide ---
    strengths, alerts = generate_insights(candidate_puc, hard_detail, soft_detail)
    interview_guide = generate_interview_guide(candidate_puc, job_config, soft_detail)
    explanation = generate_explanation_text(hard_detail, soft_detail, predictive_detail)

    # --- 9. Upsert MatchScore ---
    score_data = {
        "total_score": round(total_score, 2),
        "confidence_multiplier": round(confidence_multiplier, 4),
        "final_effective_score": round(final_effective_score, 2),
        "hard_match_score": round(hard_detail.score, 2),
        "soft_match_score": round(soft_detail.score, 2),
        "predictive_match_score": round(predictive_detail.score, 2),
        "skills_coverage": hard_detail.skills_coverage,
        "experience_score": hard_detail.experience_score,
        "education_score": hard_detail.education_score,
        "language_score": hard_detail.language_score,
        "hard_filter_passed": hard_detail.passed_filter,
        "big_five_fit": soft_detail.big_five_fit,
        "mcclelland_culture_fit": soft_detail.mcclelland_culture_fit,
        "appraisal_values_fit": soft_detail.appraisal_values_fit,
        "career_narrative_fit": soft_detail.career_narrative_fit,
        "top_strengths": [s.model_dump() for s in strengths],
        "top_alerts": [a.model_dump() for a in alerts],
        "interview_guide": [q.model_dump() for q in interview_guide],
        "explanation_text": explanation,
        "recalculated_at": datetime.now(timezone.utc),
    }
    await _match_score_repo.upsert(db, user_id, job_id, score_data)
    await db.commit()

    # --- 10. Return result ---
    return MatchScoreResult(
        user_id=user_id,
        job_id=job_id,
        total_score=round(total_score, 2),
        confidence_multiplier=round(confidence_multiplier, 4),
        final_effective_score=round(final_effective_score, 2),
        hard_match=hard_detail,
        soft_match=soft_detail,
        predictive_match=predictive_detail,
        top_strengths=strengths,
        top_alerts=alerts,
        interview_guide=interview_guide,
        explanation_text=explanation,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_candidate_dict(user: User | None) -> dict:
    """Extract candidate attributes from User ORM instance with safe defaults."""
    if user is None:
        return {
            "skills": [],
            "experience_years": 0,
            "education_level": "",
            "languages": [],
        }

    # Skills: stored as list[str] in User.skills
    skills: list[str] = user.skills or []

    # Experience years: derive from User.experience JSON list if present
    experience_years = _estimate_experience_years(user.experience)

    # Education level: derive from User.education JSON list if present
    education_level = _extract_highest_education(user.education)

    # Languages: not a first-class field on User — check skills list for language entries
    # or fall back to empty (recruiter filter will still work, just with 0 lang score)
    languages = _extract_languages_from_skills(skills)

    return {
        "skills": skills,
        "experience_years": experience_years,
        "education_level": education_level,
        "languages": languages,
    }


def _estimate_experience_years(experience: list | None) -> int:
    """Estimate total years of experience from User.experience JSON list.

    Each entry may have start_date / end_date fields (ISO strings) or
    a numeric years field.  Returns 0 if the list is empty or malformed.
    """
    if not experience:
        return 0

    total_months = 0
    now = datetime.now(timezone.utc)

    for entry in experience:
        if not isinstance(entry, dict):
            continue
        # Direct years field
        if "years" in entry:
            try:
                total_months += int(float(entry["years"])) * 12
                continue
            except (ValueError, TypeError):
                pass
        # Try date parsing
        start_str = entry.get("start_date") or entry.get("startDate") or ""
        end_str = entry.get("end_date") or entry.get("endDate") or ""
        try:
            from dateutil.parser import parse as parse_date
            start = parse_date(start_str)
            end = parse_date(end_str) if end_str else now
            delta_months = (end.year - start.year) * 12 + (end.month - start.month)
            total_months += max(0, delta_months)
        except Exception:
            pass

    return total_months // 12


def _extract_highest_education(education: list | None) -> str:
    """Return the highest education level label from User.education JSON list."""
    if not education:
        return ""

    level_priority = {k: i for i, k in enumerate(EDU_ORDER)}
    best_level = ""
    best_idx = -1

    for entry in education:
        if not isinstance(entry, dict):
            continue
        level_raw = (entry.get("level") or entry.get("degree") or "").lower()
        # Normalize common labels
        for key in EDU_ORDER:
            if key in level_raw:
                idx = level_priority[key]
                if idx > best_idx:
                    best_idx = idx
                    best_level = key
                break

    return best_level


_LANGUAGE_KEYWORDS = {"english", "inglés", "spanish", "español", "french", "francés",
                       "portuguese", "portugués", "german", "alemán", "italian", "italiano"}


def _extract_languages_from_skills(skills: list[str]) -> list[str]:
    """Extract language entries from skills list (heuristic)."""
    return [s for s in skills if s.lower() in _LANGUAGE_KEYWORDS]
