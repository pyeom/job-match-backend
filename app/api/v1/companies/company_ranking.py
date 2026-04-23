"""
B7.5 — Company Ranking API

Three endpoints for the recruiter dashboard:

  GET  /jobs/{job_id}/candidates/ranking
       List all scored candidates sorted by final_effective_score DESC.
       Supports filtering by min_score, archetype, decision_status.

  GET  /jobs/{job_id}/candidates/{user_id}/full-insights
       Full MatchScoreResult for a single candidate. Triggers compute if missing.

  POST /jobs/{job_id}/candidates/{user_id}/decision
       Record recruiter decision (avanza / descarta / en_espera).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, nulls_last
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_company_admin,
    get_company_user_with_verification,
    require_company_access,
)
from app.core.database import get_db
from app.models.job import Job
from app.models.mala import CandidatePUCProfile, MatchScore
from app.models.user import User
from app.schemas.match_score import (
    CandidateRankingItem,
    MatchScoreResult,
    RankingResponse,
    RecruiterDecision,
)
from app.services.match_score_service import ARCHETYPE_EMOJIS
from app.services.match_score_service import compute_final_score

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Candidate Ranking"])


# ---------------------------------------------------------------------------
# Internal helper — verify job ownership
# ---------------------------------------------------------------------------

async def _verify_job_ownership(
    job_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
) -> Job:
    """Ensure the job exists and belongs to the current user's company."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    require_company_access(current_user, job.company_id)
    return job


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/candidates/ranking
# ---------------------------------------------------------------------------

@router.get(
    "/jobs/{job_id}/candidates/ranking",
    response_model=RankingResponse,
    summary="Get ranked candidate list for a job (B7.5)",
)
async def get_candidate_ranking(
    job_id: uuid.UUID,
    min_score: float = Query(default=0.0, ge=0.0, le=100.0, description="Minimum final_effective_score"),
    archetype: Optional[str] = Query(default=None, description="Filter by primary_archetype"),
    decision_status: Optional[str] = Query(default=None, description="Filter by recruiter_decision"),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Candidates per page"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_company_user_with_verification),
) -> RankingResponse:
    """Return a paginated, sorted list of scored candidates for a job.

    Candidates are ordered by final_effective_score DESC. Supports optional
    filters for minimum score, archetype, and recruiter decision status.
    """
    await _verify_job_ownership(job_id, current_user, db)

    # Build base query: join MatchScore with User and CandidatePUCProfile
    stmt = (
        select(MatchScore, User, CandidatePUCProfile)
        .join(User, User.id == MatchScore.user_id)
        .outerjoin(CandidatePUCProfile, CandidatePUCProfile.user_id == MatchScore.user_id)
        .where(MatchScore.job_id == job_id)
    )

    # Apply filters
    if min_score > 0:
        stmt = stmt.where(MatchScore.final_effective_score >= min_score)
    if decision_status:
        stmt = stmt.where(MatchScore.recruiter_decision == decision_status)

    # Archetype filter (requires joining PUCProfile — use sub-filter)
    if archetype:
        stmt = stmt.where(CandidatePUCProfile.primary_archetype == archetype)

    # Order by score DESC, nulls last
    stmt = stmt.order_by(
        nulls_last(MatchScore.final_effective_score.desc())
    )

    # Count total (before pagination)
    count_stmt = (
        select(func.count())
        .select_from(MatchScore)
        .join(User, User.id == MatchScore.user_id)
        .outerjoin(CandidatePUCProfile, CandidatePUCProfile.user_id == MatchScore.user_id)
        .where(MatchScore.job_id == job_id)
    )
    if min_score > 0:
        count_stmt = count_stmt.where(MatchScore.final_effective_score >= min_score)
    if decision_status:
        count_stmt = count_stmt.where(MatchScore.recruiter_decision == decision_status)
    if archetype:
        count_stmt = count_stmt.where(CandidatePUCProfile.primary_archetype == archetype)

    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    # Apply pagination
    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    rows_result = await db.execute(stmt)
    rows = rows_result.all()

    # Build response items
    candidates: list[CandidateRankingItem] = []
    for match_score, user, puc in rows:
        top_strength = None
        top_alert = None
        if match_score.top_strengths and isinstance(match_score.top_strengths, list):
            first = match_score.top_strengths[0] if match_score.top_strengths else None
            if first:
                top_strength = first.get("title") if isinstance(first, dict) else None
        if match_score.top_alerts and isinstance(match_score.top_alerts, list):
            first_alert = match_score.top_alerts[0] if match_score.top_alerts else None
            if first_alert:
                top_alert = first_alert.get("title") if isinstance(first_alert, dict) else None

        primary_archetype = puc.primary_archetype if puc else None
        archetype_emoji = ARCHETYPE_EMOJIS.get(primary_archetype, "") if primary_archetype else None
        puc_completeness = (puc.completeness_score or 0.0) if puc else 0.0

        candidates.append(CandidateRankingItem(
            user_id=user.id,
            candidate_name=user.full_name or user.email,
            avatar_url=user.avatar_thumbnail_url or user.avatar_url,
            primary_archetype=primary_archetype,
            archetype_emoji=archetype_emoji,
            final_effective_score=match_score.final_effective_score or 0.0,
            hard_match_score=match_score.hard_match_score or 0.0,
            soft_match_score=match_score.soft_match_score or 0.0,
            predictive_match_score=match_score.predictive_match_score or 0.0,
            top_strength=top_strength,
            top_alert=top_alert,
            recruiter_decision=match_score.recruiter_decision,
            puc_completeness=puc_completeness,
        ))

    return RankingResponse(
        job_id=job_id,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(offset + len(candidates)) < total,
        candidates=candidates,
    )


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/candidates/{user_id}/full-insights
# ---------------------------------------------------------------------------

@router.get(
    "/jobs/{job_id}/candidates/{user_id}/full-insights",
    response_model=MatchScoreResult,
    summary="Get full match insights for a single candidate (B7.5)",
)
async def get_candidate_full_insights(
    job_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_company_user_with_verification),
) -> MatchScoreResult:
    """Return the full MatchScoreResult for a specific candidate.

    If no score exists yet (candidate has applied but not been scored),
    the computation is triggered synchronously and the result is returned.
    This ensures the recruiter always sees a score even for new applicants.
    """
    job = await _verify_job_ownership(job_id, current_user, db)

    # Check if score already exists
    score_stmt = select(MatchScore).where(
        MatchScore.user_id == user_id,
        MatchScore.job_id == job_id,
    )
    score_result = await db.execute(score_stmt)
    existing_score = score_result.scalar_one_or_none()

    # Trigger compute if no score exists or if score data is incomplete
    if existing_score is None or existing_score.total_score is None:
        try:
            return await compute_final_score(db, user_id, job_id)
        except Exception as exc:
            logger.error(
                "Failed to compute score for user %s job %s: %s",
                user_id, job_id, exc, exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to compute match score. Please try again.",
            )

    # Reconstruct MatchScoreResult from existing DB record
    from app.schemas.match_score import (
        HardMatchDetail, SoftMatchDetail, PredictiveMatchDetail, InsightItem, InterviewQuestion
    )

    hard_detail = HardMatchDetail(
        score=existing_score.hard_match_score or 0.0,
        passed_filter=existing_score.hard_filter_passed if existing_score.hard_filter_passed is not None else True,
        skills_coverage=existing_score.skills_coverage or 0.0,
        experience_score=existing_score.experience_score or 0.0,
        education_score=existing_score.education_score or 0.0,
        language_score=existing_score.language_score or 0.0,
        missing_required_skills=[],
    )
    soft_detail = SoftMatchDetail(
        score=existing_score.soft_match_score or 0.0,
        big_five_fit=existing_score.big_five_fit or 0.0,
        mcclelland_culture_fit=existing_score.mcclelland_culture_fit or 0.0,
        appraisal_values_fit=existing_score.appraisal_values_fit or 0.0,
        career_narrative_fit=existing_score.career_narrative_fit or 0.0,
    )
    pred_detail = PredictiveMatchDetail(
        score=existing_score.predictive_match_score or 0.0,
    )

    # Deserialize JSONB fields
    strengths: list[InsightItem] = []
    if existing_score.top_strengths and isinstance(existing_score.top_strengths, list):
        for s in existing_score.top_strengths:
            if isinstance(s, dict):
                strengths.append(InsightItem(**s))

    alerts: list[InsightItem] = []
    if existing_score.top_alerts and isinstance(existing_score.top_alerts, list):
        for a in existing_score.top_alerts:
            if isinstance(a, dict):
                alerts.append(InsightItem(**a))

    guide: list[InterviewQuestion] = []
    if existing_score.interview_guide and isinstance(existing_score.interview_guide, list):
        for q in existing_score.interview_guide:
            if isinstance(q, dict):
                guide.append(InterviewQuestion(**q))

    return MatchScoreResult(
        user_id=user_id,
        job_id=job_id,
        total_score=existing_score.total_score or 0.0,
        confidence_multiplier=existing_score.confidence_multiplier or 1.0,
        final_effective_score=existing_score.final_effective_score or 0.0,
        hard_match=hard_detail,
        soft_match=soft_detail,
        predictive_match=pred_detail,
        top_strengths=strengths,
        top_alerts=alerts,
        interview_guide=guide,
        explanation_text=existing_score.explanation_text or "",
    )


# ---------------------------------------------------------------------------
# POST /jobs/{job_id}/candidates/{user_id}/decision
# ---------------------------------------------------------------------------

@router.post(
    "/jobs/{job_id}/candidates/{user_id}/decision",
    summary="Record recruiter decision for a candidate (B7.5)",
)
async def record_recruiter_decision(
    job_id: uuid.UUID,
    user_id: uuid.UUID,
    body: RecruiterDecision,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_company_admin),
) -> dict:
    """Set the recruiter decision (avanza / descarta / en_espera) for a candidate.

    Requires COMPANY_ADMIN role. Updates MatchScore.recruiter_decision,
    recruiter_notes, and decision_at.
    """
    # Verify the job belongs to the admin's company
    await _verify_job_ownership(job_id, current_user, db)

    # Load the MatchScore
    stmt = select(MatchScore).where(
        MatchScore.user_id == user_id,
        MatchScore.job_id == job_id,
    )
    result = await db.execute(stmt)
    match_score = result.scalar_one_or_none()

    if match_score is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No match score found for this candidate and job. Ensure the candidate has applied.",
        )

    # Update decision fields
    match_score.recruiter_decision = body.decision
    match_score.recruiter_notes = body.notes
    match_score.decision_at = datetime.now(timezone.utc)

    await db.flush()

    # B9.1.3 side-effects:
    # "descarta" → create a no-hire HiringOutcome entry for the ML dataset.
    # "avanza"   → decision_at is now set; the weekly cron will request an
    #              outcome after 90 days automatically.
    if body.decision == "descarta":
        from app.models.mala import HiringOutcome
        from app.repositories.hiring_outcome_repository import HiringOutcomeRepository
        _outcome_repo = HiringOutcomeRepository()
        existing_outcome = await _outcome_repo.get_by_match_score_id(db, match_score.id)
        if existing_outcome is None:
            await _outcome_repo.create(db, {
                "match_score_id": match_score.id,
                "user_id": user_id,
                "job_id": job_id,
                "company_id": current_user.company_id,
                "was_successful_hire": False,
                "failure_reason": "recruiter_rejected",
            })
            logger.info(
                "No-hire outcome auto-created for descarta: job=%s user=%s",
                job_id, user_id,
            )

    await db.commit()

    logger.info(
        "Recruiter decision recorded: job=%s user=%s decision=%s by=%s",
        job_id, user_id, body.decision, current_user.id,
    )

    return {"status": "ok", "decision": body.decision}


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/candidates/{user_id}/explanation   [B8.2.2]
# ---------------------------------------------------------------------------

@router.get(
    "/jobs/{job_id}/candidates/{user_id}/explanation",
    summary="Get LLM-generated natural-language match explanation (B8.2.2)",
)
async def get_candidate_explanation(
    job_id: uuid.UUID,
    user_id: uuid.UUID,
    regenerate: bool = Query(default=False, description="Force re-generation even if cached"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_company_user_with_verification),
) -> dict:
    """Return a natural-language explanation of the match score for a recruiter.

    If a cached explanation exists in ``match_scores.explanation_text`` it is
    returned immediately.  Pass ``?regenerate=true`` or if the field is empty
    the explanation is generated on-demand via the Anthropic API (with a
    template fallback when no API key is configured) and the result is
    persisted for future requests.
    """
    from app.services.insights_service import generate_explanation_text_llm
    from app.schemas.match_score import (
        HardMatchDetail, SoftMatchDetail, PredictiveMatchDetail,
        InsightItem as _InsightItem, InterviewQuestion as _IQ,
    )

    await _verify_job_ownership(job_id, current_user, db)

    # Load MatchScore
    score_stmt = select(MatchScore).where(
        MatchScore.user_id == user_id,
        MatchScore.job_id == job_id,
    )
    score_result = await db.execute(score_stmt)
    existing_score = score_result.scalar_one_or_none()

    if existing_score is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match score not found.")

    # Return cached if present and not forced regeneration
    if existing_score.explanation_text and not regenerate:
        return {"explanation_text": existing_score.explanation_text, "cached": True}

    # Load candidate and job for context
    user_stmt = select(User).where(User.id == user_id)
    user_result = await db.execute(user_stmt)
    candidate = user_result.scalar_one_or_none()

    job_stmt = select(Job).where(Job.id == job_id)
    job_result = await db.execute(job_stmt)
    job = job_result.scalar_one_or_none()

    if not candidate or not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate or job not found.")

    # Load PUC profile for archetype context
    from app.models.mala import CandidatePUCProfile as _PUC
    puc_stmt = select(_PUC).where(_PUC.user_id == user_id)
    puc_result = await db.execute(puc_stmt)
    puc = puc_result.scalar_one_or_none()

    # Reconstruct MatchScoreResult for LLM context
    hard_detail = HardMatchDetail(
        score=existing_score.hard_match_score or 0.0,
        passed_filter=existing_score.hard_filter_passed if existing_score.hard_filter_passed is not None else True,
        skills_coverage=existing_score.skills_coverage or 0.0,
        experience_score=existing_score.experience_score or 0.0,
        education_score=existing_score.education_score or 0.0,
        language_score=existing_score.language_score or 0.0,
        missing_required_skills=[],
    )
    soft_detail = SoftMatchDetail(
        score=existing_score.soft_match_score or 0.0,
        big_five_fit=existing_score.big_five_fit or 0.0,
        mcclelland_culture_fit=existing_score.mcclelland_culture_fit or 0.0,
        appraisal_values_fit=existing_score.appraisal_values_fit or 0.0,
        career_narrative_fit=existing_score.career_narrative_fit or 0.0,
        personality_distance=0.0,
    )
    pred_detail = PredictiveMatchDetail(score=existing_score.predictive_match_score or 0.0)

    strengths: list[_InsightItem] = []
    if existing_score.top_strengths and isinstance(existing_score.top_strengths, list):
        for s in existing_score.top_strengths:
            if isinstance(s, dict):
                try:
                    strengths.append(_InsightItem(**s))
                except Exception:
                    logger.warning("Failed to deserialize strength insight item: %s", s, exc_info=True)

    alerts: list[_InsightItem] = []
    if existing_score.top_alerts and isinstance(existing_score.top_alerts, list):
        for a in existing_score.top_alerts:
            if isinstance(a, dict):
                try:
                    alerts.append(_InsightItem(**a))
                except Exception:
                    logger.warning("Failed to deserialize alert insight item: %s", a, exc_info=True)

    from app.schemas.match_score import MatchScoreResult
    scores = MatchScoreResult(
        user_id=user_id,
        job_id=job_id,
        total_score=existing_score.total_score or 0.0,
        confidence_multiplier=existing_score.confidence_multiplier or 1.0,
        final_effective_score=existing_score.final_effective_score or 0.0,
        hard_match=hard_detail,
        soft_match=soft_detail,
        predictive_match=pred_detail,
        top_strengths=strengths,
        top_alerts=alerts,
        explanation_text="",
    )

    explanation = await generate_explanation_text_llm(candidate, job, scores, puc)

    # Persist for caching
    existing_score.explanation_text = explanation
    await db.flush()
    await db.commit()

    return {"explanation_text": explanation, "cached": False}


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/candidates/{user_id}/interview-guide   [B8.2.3]
# ---------------------------------------------------------------------------

@router.get(
    "/jobs/{job_id}/candidates/{user_id}/interview-guide",
    summary="Get structured interview guide for a candidate (B8.2.3)",
)
async def get_interview_guide(
    job_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_company_user_with_verification),
) -> dict:
    """Return the interview guide for a candidate in both JSON and plaintext formats.

    The guide is loaded from ``match_scores.interview_guide``.  If it hasn't
    been generated yet the full score computation is triggered first.
    """
    await _verify_job_ownership(job_id, current_user, db)

    # Load MatchScore
    score_stmt = select(MatchScore).where(
        MatchScore.user_id == user_id,
        MatchScore.job_id == job_id,
    )
    score_result = await db.execute(score_stmt)
    existing_score = score_result.scalar_one_or_none()

    # Trigger compute if score not present yet
    if existing_score is None or not existing_score.interview_guide:
        try:
            full = await compute_final_score(db, user_id, job_id)
            guide_items = full.interview_guide
        except Exception as exc:
            logger.error("Failed to compute score for interview guide: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate interview guide.",
            )
    else:
        from app.schemas.match_score import InterviewQuestion as _IQ
        guide_items = []
        for q in existing_score.interview_guide:
            if isinstance(q, dict):
                try:
                    guide_items.append(_IQ(**q))
                except Exception:
                    logger.warning("Failed to deserialize interview guide item: %s", q, exc_info=True)

    # Build plaintext version for copy-paste
    lines: list[str] = ["GUÍA DE ENTREVISTA", "=" * 40]
    for i, q in enumerate(guide_items, start=1):
        lines.append(f"\n{i}. {q.question}")
        lines.append(f"   Propósito: {q.rationale}")
        lines.append(f"   Señales a observar: {q.what_to_look_for}")
        lines.append(f"   Brecha abordada: {q.gap_addressed}")
    plaintext = "\n".join(lines)

    return {
        "questions": [q.model_dump() for q in guide_items],
        "plaintext": plaintext,
        "total": len(guide_items),
    }
