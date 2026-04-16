"""
Companies API module

This module organizes company-related endpoints into logical sub-modules:
- company_crud: Company CRUD operations
- company_jobs: Job management endpoints
- company_applications: Application management endpoints
- company_notifications: Notification management endpoints
- company_push_tokens: Push token management endpoints
- company_org_profile: Org profile (E1–E4) endpoints
- company_match_config: Job match config (E5–E9) endpoints
"""

from fastapi import APIRouter
from .company_crud import router as crud_router
from .company_jobs import router as jobs_router
from .company_applications import router as applications_router
from .company_notifications import router as notifications_router
from .company_push_tokens import router as push_tokens_router
from .company_org_profile import router as org_profile_router
from .company_match_config import router as match_config_router
from .company_ranking import router as ranking_router

# Create a single router that combines all company endpoints
router = APIRouter()

# Include all sub-routers.
# IMPORTANT: applications_router must come before crud_router so that
# static paths like GET /applications are matched before the wildcard
# GET /{company_id} route in crud_router.
# org_profile_router and match_config_router must come before crud_router
# so that static paths (/org-profile, /jobs/{id}/match-config) are matched
# before the /{company_id} wildcard.
router.include_router(org_profile_router)
router.include_router(match_config_router)
router.include_router(ranking_router)
router.include_router(applications_router)
router.include_router(crud_router)
router.include_router(jobs_router)
router.include_router(notifications_router)
router.include_router(push_tokens_router)
