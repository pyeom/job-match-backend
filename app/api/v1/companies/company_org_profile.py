"""
B6.3.1 — POST /api/v1/companies/org-profile
B6.3.2 — GET  /api/v1/companies/{company_id}/org-profile
"""
from __future__ import annotations

import logging
import uuid

from arq import create_pool
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_company_admin, get_company_user_with_verification
from app.core.arq import get_arq_pool
from app.core.database import get_db
from app.models.user import User
from app.schemas.company_profile import OrgProfileCreate, OrgProfileRead
from app.services.company_profile_service import build_org_profile, get_org_profile

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Company Org Profile"])


@router.post(
    "/org-profile",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit company org profile for MALA analysis (E1–E4)",
)
async def create_org_profile(
    payload: OrgProfileCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_company_admin),
):
    """B6.3.1 — Save E1–E4 texts and enqueue background MALA analysis.

    Returns immediately with ``{org_profile_id, status: "analyzing"}``.
    Requires ``company_admin`` role.
    """
    company_id: uuid.UUID = current_user.company_id
    if not company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not associated with a company",
        )

    profile = await build_org_profile(db, company_id, payload)

    # Enqueue background MALA analysis
    try:
        pool = await get_arq_pool()
        await pool.enqueue_job("analyze_org_profile", str(company_id))
    except Exception as exc:
        logger.warning("Could not enqueue org profile analysis for company %s: %s", company_id, exc)

    return {
        "org_profile_id": str(profile.id),
        "company_id": str(company_id),
        "status": "analyzing",
    }


@router.get(
    "/{company_id}/org-profile",
    response_model=OrgProfileRead,
    summary="Get company org profile with inferred culture fields",
)
async def read_org_profile(
    company_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_company_user_with_verification),
):
    """B6.3.2 — Returns the full inferred org profile.

    If analysis is still in progress, inferred fields will be ``null``
    and ``status`` will be ``"analyzing"``.
    """
    # Company users can only read their own company profile
    if current_user.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    profile = await get_org_profile(db, company_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Org profile not found. Submit E1–E4 answers first.",
        )

    # Determine status: if management_archetype is set, analysis completed
    is_completed = profile.management_archetype is not None

    return OrgProfileRead(
        id=profile.id,
        company_id=profile.company_id,
        e1_culture_text=profile.e1_culture_text,
        e2_no_fit_text=profile.e2_no_fit_text,
        e3_decision_style_text=profile.e3_decision_style_text,
        e4_best_hire_text=profile.e4_best_hire_text,
        status="completed" if is_completed else "analyzing",
        culture_valence=profile.culture_valence,
        affiliation_vs_achievement=profile.affiliation_vs_achievement,
        hierarchy_score=profile.hierarchy_score,
        management_archetype=profile.management_archetype,
        org_openness=profile.org_openness,
        org_conscientiousness=profile.org_conscientiousness,
        org_extraversion=profile.org_extraversion,
        org_agreeableness=profile.org_agreeableness,
        org_stability=profile.org_stability,
        cultural_deal_breakers=profile.cultural_deal_breakers,
        anti_profile_signals=profile.anti_profile_signals,
    )
