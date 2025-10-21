"""
Statistics service for generating company and application analytics.

This module provides business logic for calculating and aggregating
various statistics related to jobs, applications, and company metrics.
"""

from __future__ import annotations
from typing import Optional
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.repositories.application_repository import ApplicationRepository
from app.repositories.job_repository import JobRepository
from app.utils.status_mapper import map_status_to_frontend

logger = logging.getLogger(__name__)


class StatisticsService:
    """
    Service for generating statistics and analytics.

    This service coordinates between repositories to generate
    comprehensive statistics for companies, jobs, and applications.
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

    async def get_dashboard_stats(
        self,
        db: AsyncSession,
        company_id: UUID
    ) -> dict:
        """
        Get comprehensive dashboard statistics for a company.

        Combines job counts and application statistics into a single
        dashboard view.

        Args:
            db: Active database session
            company_id: UUID of the company

        Returns:
            Dictionary with dashboard statistics:
            {
                "total_jobs": 25,
                "active_jobs": 20,
                "total_applications": 150,
                "applications_last_30_days": 45,
                "applications_last_7_days": 12,
                "conversion_rate": 0.25
            }

        Example:
            stats = await service.get_dashboard_stats(db, company_id)
            print(f"Active jobs: {stats['active_jobs']}")
        """
        try:
            # Get job counts
            active_jobs_count = await self.job_repo.get_active_jobs_count(db, company_id)
            all_jobs, _ = await self.job_repo.get_company_jobs(
                db, company_id, skip=0, limit=1, active_only=False
            )
            total_jobs_query = await self.job_repo.get_company_jobs(
                db, company_id, skip=0, limit=0, active_only=False
            )
            total_jobs = total_jobs_query[1]  # Get count from tuple

            # Get application statistics
            app_stats = await self.application_repo.get_company_statistics(db, company_id)

            return {
                "total_jobs": total_jobs,
                "active_jobs": active_jobs_count,
                "total_applications": app_stats["total_applications"],
                "applications_last_30_days": app_stats["applications_last_30_days"],
                "applications_last_7_days": app_stats["applications_last_7_days"],
                "conversion_rate": app_stats["conversion_rate"]
            }

        except Exception as e:
            logger.error(f"Error getting dashboard stats for company {company_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve dashboard statistics"
            )

    async def get_application_metrics(
        self,
        db: AsyncSession,
        company_id: UUID
    ) -> dict:
        """
        Get detailed application metrics for a company.

        Args:
            db: Active database session
            company_id: UUID of the company

        Returns:
            Dictionary with application metrics matching CompanyApplicationMetrics schema

        Example:
            metrics = await service.get_application_metrics(db, company_id)
        """
        try:
            stats = await self.application_repo.get_company_statistics(db, company_id)
            return stats

        except Exception as e:
            logger.error(f"Error getting application metrics for company {company_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve application metrics"
            )

    async def get_jobs_application_stats(
        self,
        db: AsyncSession,
        company_id: UUID,
        active_only: bool = True
    ) -> list[dict]:
        """
        Get application statistics for each job of a company.

        Args:
            db: Active database session
            company_id: UUID of the company
            active_only: If True, only include active jobs

        Returns:
            List of dictionaries with job and application counts:
            [
                {
                    "job_id": UUID,
                    "job_title": "Software Engineer",
                    "is_active": True,
                    "total_applications": 15,
                    "pending_applications": 8,
                    "accepted_applications": 5,
                    "rejected_applications": 2
                }
            ]

        Example:
            stats = await service.get_jobs_application_stats(db, company_id)
            for job_stat in stats:
                print(f"{job_stat['job_title']}: {job_stat['total_applications']} apps")
        """
        try:
            # Get company jobs
            jobs, _ = await self.job_repo.get_company_jobs(
                db, company_id, skip=0, limit=1000, active_only=active_only
            )

            if not jobs:
                return []

            # Get application counts for all jobs
            job_ids = [job.id for job in jobs]
            counts = await self.application_repo.get_job_application_counts(db, job_ids)

            # Combine job info with counts
            result = []
            for job in jobs:
                job_counts = counts.get(job.id, {
                    "total": 0,
                    "pending": 0,
                    "accepted": 0,
                    "rejected": 0
                })

                result.append({
                    "job_id": job.id,
                    "job_title": job.title,
                    "is_active": job.is_active,
                    "total_applications": job_counts["total"],
                    "pending_applications": job_counts["pending"],
                    "accepted_applications": job_counts["accepted"],
                    "rejected_applications": job_counts["rejected"]
                })

            return result

        except Exception as e:
            logger.error(f"Error getting job application stats for company {company_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve job application statistics"
            )

    async def get_jobs_overview(
        self,
        db: AsyncSession,
        company_id: UUID,
        page: int = 1,
        limit: int = 20,
        active_only: bool = True
    ) -> dict:
        """
        Get paginated jobs with application counts and recent applicants.

        This is a comprehensive endpoint that combines job information
        with application statistics and recent applicant data.

        Args:
            db: Active database session
            company_id: UUID of the company
            page: Page number (1-indexed)
            limit: Items per page
            active_only: If True, only include active jobs

        Returns:
            Dictionary with:
            {
                "jobs": [
                    {
                        "id": UUID,
                        "title": "Software Engineer",
                        "created_at": datetime,
                        "status": "active",
                        "application_counts": {
                            "total": 15,
                            "pending": 8,
                            "accepted": 5,
                            "rejected": 2
                        },
                        "recent_applicants": [
                            {
                                "user_full_name": "John Doe",
                                "user_email": "john@example.com",
                                "status": "SUBMITTED",
                                "created_at": datetime
                            }
                        ]
                    }
                ],
                "pagination": {
                    "page": 1,
                    "limit": 20,
                    "total": 25,
                    "total_pages": 2
                },
                "summary": {
                    "total_jobs": 25,
                    "total_applications": 150
                }
            }

        Example:
            overview = await service.get_jobs_overview(db, company_id, page=1, limit=20)
            for job in overview['jobs']:
                print(f"{job['title']}: {job['application_counts']['total']} applications")
        """
        try:
            # Calculate offset
            skip = (page - 1) * limit

            # Get paginated jobs
            jobs, total_jobs = await self.job_repo.get_company_jobs(
                db, company_id, skip=skip, limit=limit, active_only=active_only
            )

            if not jobs:
                return {
                    "jobs": [],
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": 0,
                        "total_pages": 0
                    },
                    "summary": {
                        "total_jobs": 0,
                        "total_applications": 0
                    }
                }

            # Get application counts for these jobs
            job_ids = [job.id for job in jobs]
            counts = await self.application_repo.get_job_application_counts(db, job_ids)

            # Get recent applicants for each job
            jobs_with_details = []
            total_applications = 0

            for job in jobs:
                job_counts = counts.get(job.id, {
                    "total": 0,
                    "pending": 0,
                    "accepted": 0,
                    "rejected": 0
                })
                total_applications += job_counts["total"]

                # Get recent applicants (limit to 3)
                recent_applicants = await self.application_repo.get_recent_applicants(
                    db, job.id, limit=3
                )

                # Map backend statuses to frontend
                for applicant in recent_applicants:
                    applicant["status"] = map_status_to_frontend(applicant["status"])

                jobs_with_details.append({
                    "id": job.id,
                    "title": job.title,
                    "created_at": job.created_at,
                    "status": "active" if job.is_active else "inactive",
                    "application_counts": {
                        "total": job_counts["total"],
                        "pending": job_counts["pending"],
                        "accepted": job_counts["accepted"],
                        "rejected": job_counts["rejected"]
                    },
                    "recent_applicants": recent_applicants
                })

            # Calculate total pages
            import math
            total_pages = math.ceil(total_jobs / limit) if total_jobs > 0 else 0

            return {
                "jobs": jobs_with_details,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": total_jobs,
                    "total_pages": total_pages
                },
                "summary": {
                    "total_jobs": total_jobs,
                    "total_applications": total_applications
                }
            }

        except Exception as e:
            logger.error(f"Error getting jobs overview for company {company_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve jobs overview"
            )
