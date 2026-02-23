"""
Job service for business logic related to job postings.

This module handles job creation, updates, and deletion with proper
authorization checks and embedding generation integration.
"""

from __future__ import annotations
from typing import Optional
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.models.job import Job
from app.models.user import User, UserRole
from app.repositories.job_repository import JobRepository
from app.services.embedding_service import EmbeddingService
from app.core.cache import get_cached_job, set_cached_job, invalidate_job_cache

logger = logging.getLogger(__name__)


class JobService:
    """
    Service for managing job postings.

    This service coordinates between repositories and the embedding service
    to handle job lifecycle operations with proper business logic and
    authorization checks.
    """

    def __init__(
        self,
        job_repo: Optional[JobRepository] = None,
        embedding_service: Optional[EmbeddingService] = None
    ):
        """
        Initialize service with repositories and services.

        Args:
            job_repo: JobRepository instance (creates new if None)
            embedding_service: EmbeddingService instance (creates new if None)
        """
        self.job_repo = job_repo or JobRepository()
        self.embedding_service = embedding_service or EmbeddingService()

    def _verify_company_permission(
        self,
        current_user: User,
        company_id: UUID,
        operation: str = "perform this operation"
    ) -> None:
        """
        Verify that a user has permission to manage jobs for a company.

        Args:
            current_user: Current authenticated user
            company_id: UUID of the company
            operation: Description of the operation (for error message)

        Raises:
            HTTPException: 403 if user doesn't have permission
        """
        # User must be a company recruiter or admin
        if current_user.role not in [UserRole.COMPANY_RECRUITER, UserRole.COMPANY_ADMIN]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Only company recruiters and admins can {operation}"
            )

        # User must belong to the company
        if not current_user.company_id or current_user.company_id != company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You can only {operation} for your own company"
            )

    async def create_job(
        self,
        db: AsyncSession,
        company_id: UUID,
        job_data: dict,
        current_user: User
    ) -> Job:
        """
        Create a new job posting.

        Verifies user permissions, creates the job, and attempts to generate
        an embedding. If embedding generation fails, the job is still created
        but without an embedding (logged as error).

        Args:
            db: Active database session
            company_id: UUID of the company
            job_data: Dictionary with job fields (title, description, etc.)
            current_user: Current authenticated user

        Returns:
            Created Job instance

        Raises:
            HTTPException: 403 if unauthorized, 500 if creation fails

        Example:
            job = await service.create_job(
                db,
                company_id,
                {
                    "title": "Software Engineer",
                    "description": "Build amazing things",
                    "location": "Remote",
                    "tags": ["Python", "FastAPI"]
                },
                current_user
            )
            await db.commit()
        """
        try:
            # Verify permissions
            self._verify_company_permission(current_user, company_id, "create jobs")

            # Ensure company_id is set correctly
            job_data["company_id"] = company_id

            # Create job
            job = await self.job_repo.create(db, job_data)

            # Try to generate embedding
            try:
                embedding = self.embedding_service.generate_job_embedding_from_parts(
                    title=job.title,
                    company=str(company_id),  # Will be replaced with company name in production
                    short_description=job.short_description,
                    description=job.description,
                    tags=job.tags or []
                )

                # Update job with embedding
                await self.job_repo.update(db, job, {"job_embedding": embedding})

                logger.info(f"Job {job.id} created with embedding by user {current_user.id}")

            except Exception as e:
                logger.error(f"Failed to generate embedding for job {job.id}: {e}")
                logger.info(f"Job {job.id} created without embedding")

            return job

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating job for company {company_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create job"
            )

    async def update_job(
        self,
        db: AsyncSession,
        company_id: UUID,
        job_id: UUID,
        job_update: dict,
        current_user: User
    ) -> Job:
        """
        Update an existing job posting.

        Verifies permissions and job ownership. If content fields (title,
        description, tags) are updated, regenerates the job embedding.

        Args:
            db: Active database session
            company_id: UUID of the company
            job_id: UUID of the job to update
            job_update: Dictionary with fields to update
            current_user: Current authenticated user

        Returns:
            Updated Job instance

        Raises:
            HTTPException: 404 if not found, 403 if unauthorized

        Example:
            job = await service.update_job(
                db,
                company_id,
                job_id,
                {"title": "Senior Software Engineer", "salary_max": 150000},
                current_user
            )
            await db.commit()
        """
        try:
            # Verify permissions
            self._verify_company_permission(current_user, company_id, "update jobs")

            # Get existing job
            job = await self.job_repo.get(db, job_id)
            if not job:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Job {job_id} not found"
                )

            # Verify job belongs to company
            if job.company_id != company_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Job does not belong to your company"
                )

            # Check if content fields changed (need to regenerate embedding)
            content_fields = {"title", "short_description", "description", "tags"}
            content_changed = any(field in job_update for field in content_fields)

            # Update job
            updated_job = await self.job_repo.update(db, job, job_update)

            # Regenerate embedding if content changed
            if content_changed:
                try:
                    embedding = self.embedding_service.generate_job_embedding_from_parts(
                        title=updated_job.title,
                        company=str(company_id),
                        short_description=updated_job.short_description,
                        description=updated_job.description,
                        tags=updated_job.tags or []
                    )

                    await self.job_repo.update(db, updated_job, {"job_embedding": embedding})

                    logger.info(f"Job {job_id} updated with new embedding by user {current_user.id}")

                except Exception as e:
                    logger.error(f"Failed to regenerate embedding for job {job_id}: {e}")
                    logger.warning(f"Job {job_id} updated but embedding not regenerated")

            else:
                logger.info(f"Job {job_id} updated (no embedding regeneration) by user {current_user.id}")

            # Invalidate cached job details so the next read reflects the update
            await invalidate_job_cache(str(job_id))

            return updated_job

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating job {job_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update job"
            )

    async def delete_job(
        self,
        db: AsyncSession,
        company_id: UUID,
        job_id: UUID,
        current_user: User
    ) -> None:
        """
        Soft delete a job posting.

        Sets is_active to False instead of actually deleting the record.
        This preserves historical data and application records.

        Args:
            db: Active database session
            company_id: UUID of the company
            job_id: UUID of the job to delete
            current_user: Current authenticated user

        Raises:
            HTTPException: 404 if not found, 403 if unauthorized

        Example:
            await service.delete_job(db, company_id, job_id, current_user)
            await db.commit()
        """
        try:
            # Verify permissions
            self._verify_company_permission(current_user, company_id, "delete jobs")

            # Get existing job
            job = await self.job_repo.get(db, job_id)
            if not job:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Job {job_id} not found"
                )

            # Verify job belongs to company
            if job.company_id != company_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Job does not belong to your company"
                )

            # Soft delete by setting is_active to False
            await self.job_repo.update(db, job, {"is_active": False})

            logger.info(f"Job {job_id} soft deleted by user {current_user.id}")

            # Invalidate cached job details so stale is_active=True is not served
            await invalidate_job_cache(str(job_id))

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting job {job_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete job"
            )

    async def get_job_details(
        self,
        db: AsyncSession,
        job_id: UUID
    ) -> Job:
        """
        Get job details with company information.

        Args:
            db: Active database session
            job_id: UUID of the job

        Returns:
            Job instance with company loaded

        Raises:
            HTTPException: 404 if not found

        Example:
            job = await service.get_job_details(db, job_id)
            print(f"{job.title} at {job.company.name}")
        """
        try:
            # Check cache first — fall through to DB on any miss or error
            cached = await get_cached_job(str(job_id))
            if cached is not None:
                logger.debug("Job cache hit for %s", job_id)
                return cached

            job = await self.job_repo.get_job_with_company(db, job_id)
            if not job:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Job {job_id} not found"
                )

            # Populate cache for subsequent requests
            await set_cached_job(str(job_id), job)

            return job

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting job details for {job_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve job details"
            )
