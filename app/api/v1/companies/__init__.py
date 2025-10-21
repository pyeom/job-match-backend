"""
Companies API module

This module organizes company-related endpoints into logical sub-modules:
- company_crud: Company CRUD operations
- company_jobs: Job management endpoints
- company_applications: Application management endpoints
"""

from fastapi import APIRouter
from .company_crud import router as crud_router
from .company_jobs import router as jobs_router
from .company_applications import router as applications_router

# Create a single router that combines all company endpoints
router = APIRouter()

# Include all sub-routers
router.include_router(crud_router)
router.include_router(jobs_router)
router.include_router(applications_router)
