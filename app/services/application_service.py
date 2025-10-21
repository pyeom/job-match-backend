"""
Application service for business logic related to job applications.

This module handles application management including status updates,
filtering, and company-specific application queries with proper
authorization checks.
"""

from __future__ import annotations
from typing import Optional
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.models.application import Application
from app.models.user import User
from app.repositories.application_repository import ApplicationRepository
from app.repositories.job_repository import JobRepository
from app.utils.status_mapper import map_status_to_frontend, map_status_to_backend

logger = logging.getLogger(__name__)


class ApplicationService:
    """
    Service for managing job applications.

    This service coordinates between repositories and implements
    business logic for application operations, including authorization
    checks and status mapping.
    """

    def __init__(
        self,
        application_repo: Optional[ApplicationRepository] = None,
        job_repo: Optional[JobRepository] = None
    ):
        """
        Initialize service with repositories.

        Args:
            application_repo: ApplicationRepository instance (creates new if None)
            job_repo: JobRepository instance (creates new if None)
        """
        self.application_repo = application_repo or ApplicationRepository()
        self.job_repo = job_repo or JobRepository()

    async def get_job_applications_paginated(
        self,
        db: AsyncSession,
        company_id: UUID,
        job_id: UUID,
        page: int = 1,
        limit: int = 20,
        status_filter: Optional[str] = None
    ) -> tuple[list[Application], int]:
        """
        Get paginated applications for a specific job.

        Verifies that the job belongs to the specified company before
        retrieving applications. Maps backend statuses to frontend format.

        Args:
            db: Active database session
            company_id: UUID of the company (for authorization)
            job_id: UUID of the job
            page: Page number (1-indexed)
            limit: Items per page
            status_filter: Optional frontend status filter (SUBMITTED, ACCEPTED, REJECTED)

        Returns:
            Tuple of (list of applications, total count)

        Raises:
            HTTPException: 404 if job not found, 403 if company doesn't own job

        Example:
            apps, total = await service.get_job_applications_paginated(
                db, company_id, job_id, page=1, limit=20
            )
        """
        try:
            # Verify job exists and belongs to company
            job = await self.job_repo.get(db, job_id)
            if not job:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Job {job_id} not found"
                )

            if job.company_id != company_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied. Job does not belong to your company"
                )

            # Map frontend status filter to backend statuses if provided
            backend_status_filter = None
            if status_filter:
                try:
                    backend_status_filter = map_status_to_backend(status_filter)
                except ValueError as e:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=str(e)
                    )

            # Calculate offset
            skip = (page - 1) * limit

            # Get applications
            applications, total = await self.application_repo.get_applications_for_job(
                db, job_id, skip=skip, limit=limit, status_filter=backend_status_filter
            )

            return applications, total

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting applications for job {job_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve applications"
            )

    async def update_application_status(
        self,
        db: AsyncSession,
        application_id: UUID,
        frontend_status: str,
        current_user: User
    ) -> Application:
        """
        Update the status of an application.

        Verifies that the current user's company owns the job before
        allowing status updates. Maps frontend status to backend format.

        Args:
            db: Active database session
            application_id: UUID of the application
            frontend_status: New status in frontend format (SUBMITTED, ACCEPTED, REJECTED)
            current_user: Current authenticated user

        Returns:
            Updated Application instance

        Raises:
            HTTPException: 404 if application not found, 403 if unauthorized

        Example:
            app = await service.update_application_status(
                db, app_id, "ACCEPTED", current_user
            )
            await db.commit()
        """
        try:
            # Get application with job loaded
            application = await self.application_repo.get(db, application_id)
            if not application:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Application {application_id} not found"
                )

            # Get job to verify ownership
            job = await self.job_repo.get(db, application.job_id)
            if not job:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Associated job not found"
                )

            # Verify current user's company owns the job
            if not current_user.company_id or job.company_id != current_user.company_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied. You can only update applications for your company's jobs"
                )

            # Map frontend status to backend
            try:
                backend_status = map_status_to_backend(frontend_status)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e)
                )

            # Update application
            updated_application = await self.application_repo.update(
                db,
                application,
                {"status": backend_status}
            )

            logger.info(
                f"Application {application_id} status updated to {backend_status} "
                f"by user {current_user.id}"
            )

            return updated_application

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating application {application_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update application status"
            )

    async def get_company_applications(
        self,
        db: AsyncSession,
        company_id: UUID,
        page: int = 1,
        limit: int = 50,
        status_filter: Optional[str] = None
    ) -> tuple[list[Application], int]:
        """
        Get paginated applications for all jobs of a company.

        Args:
            db: Active database session
            company_id: UUID of the company
            page: Page number (1-indexed)
            limit: Items per page
            status_filter: Optional frontend status filter

        Returns:
            Tuple of (list of applications, total count)

        Example:
            apps, total = await service.get_company_applications(
                db, company_id, page=1, limit=50, status_filter="SUBMITTED"
            )
        """
        try:
            # Map frontend status filter to backend if provided
            backend_status_filter = None
            if status_filter:
                try:
                    backend_status_filter = map_status_to_backend(status_filter)
                except ValueError as e:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=str(e)
                    )

            # Calculate offset
            skip = (page - 1) * limit

            # Get applications
            applications, total = await self.application_repo.get_applications_for_company(
                db, company_id, skip=skip, limit=limit, status_filter=backend_status_filter
            )

            return applications, total

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting applications for company {company_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve applications"
            )

    async def get_application_by_id(
        self,
        db: AsyncSession,
        application_id: UUID,
        current_user: User
    ) -> Application:
        """
        Get a single application by ID with authorization check.

        Args:
            db: Active database session
            application_id: UUID of the application
            current_user: Current authenticated user

        Returns:
            Application instance

        Raises:
            HTTPException: 404 if not found, 403 if unauthorized
        """
        try:
            application = await self.application_repo.get(db, application_id)
            if not application:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Application {application_id} not found"
                )

            # Verify authorization
            # User can view if they're the applicant OR if they're from the company
            job = await self.job_repo.get(db, application.job_id)
            if not job:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Associated job not found"
                )

            is_applicant = application.user_id == current_user.id
            is_company_user = (
                current_user.company_id and
                job.company_id == current_user.company_id
            )

            if not (is_applicant or is_company_user):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied"
                )

            return application

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting application {application_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve application"
            )
