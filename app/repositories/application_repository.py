"""
Application repository for managing job application data.

This module provides specialized queries for applications, including
filtering by job/company, status-based filtering, and aggregations
for statistics and analytics.
"""

from __future__ import annotations
from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta
from sqlalchemy import select, func, and_, case, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
import logging

from app.models.application import Application
from app.models.user import User
from app.models.job import Job
from .base import BaseRepository

logger = logging.getLogger(__name__)


class ApplicationRepository(BaseRepository[Application]):
    """
    Repository for Application model with specialized queries.

    Provides methods for:
    - Filtering applications by job or company
    - Status-based filtering
    - Application counts and statistics
    - Recent applicant queries
    """

    def __init__(self):
        """Initialize with Application model."""
        super().__init__(Application)

    async def get(
        self,
        db: AsyncSession,
        id: UUID
    ) -> Optional[Application]:
        """
        Get application by ID with relationships loaded.

        This override loads the user and job relationships needed for notifications.

        Args:
            db: Active database session
            id: UUID of the application

        Returns:
            Application instance with relationships loaded, or None if not found

        Example:
            app = await repo.get(db, application_id)
            if app:
                print(f"{app.user.email} applied to {app.job.title} at {app.job.company.name}")
        """
        try:
            stmt = (
                select(Application)
                .where(Application.id == id)
                .options(
                    selectinload(Application.user),
                    selectinload(Application.job).selectinload(Job.company)
                )
            )
            result = await db.execute(stmt)
            return result.scalar_one_or_none()

        except SQLAlchemyError as e:
            logger.error(f"Error fetching application {id} with relationships: {e}")
            raise

    async def get_applications_for_job(
        self,
        db: AsyncSession,
        job_id: UUID,
        skip: int = 0,
        limit: int = 100,
        status_filter: Optional[str] = None
    ) -> tuple[list[Application], int]:
        """
        Get paginated applications for a specific job.

        Args:
            db: Active database session
            job_id: UUID of the job
            skip: Number of records to skip (offset)
            limit: Maximum number of records to return
            status_filter: Optional status to filter by

        Returns:
            Tuple of (list of applications with user data loaded, total count)

        Example:
            apps, total = await repo.get_applications_for_job(
                db, job_id, skip=0, limit=20, status_filter="SUBMITTED"
            )
        """
        try:
            # Build base query with user relationship loaded
            query = (
                select(Application)
                .where(Application.job_id == job_id)
                .options(selectinload(Application.user))
                .order_by(desc(Application.created_at))
            )

            # Add status filter if provided
            if status_filter:
                query = query.where(Application.status == status_filter)

            # Get paginated results
            paginated_query = query.offset(skip).limit(limit)
            result = await db.execute(paginated_query)
            applications = list(result.scalars().all())

            # Get total count with same filters
            count_query = select(func.count()).select_from(Application).where(Application.job_id == job_id)
            if status_filter:
                count_query = count_query.where(Application.status == status_filter)

            count_result = await db.execute(count_query)
            total = count_result.scalar_one()

            return applications, total

        except SQLAlchemyError as e:
            logger.error(f"Error fetching applications for job {job_id}: {e}")
            raise

    async def get_applications_for_company(
        self,
        db: AsyncSession,
        company_id: UUID,
        skip: int = 0,
        limit: int = 100,
        status_filter: Optional[str] = None
    ) -> tuple[list[Application], int]:
        """
        Get paginated applications for all jobs of a company.

        Args:
            db: Active database session
            company_id: UUID of the company
            skip: Number of records to skip
            limit: Maximum number of records to return
            status_filter: Optional status to filter by

        Returns:
            Tuple of (list of applications with user and job loaded, total count)

        Example:
            apps, total = await repo.get_applications_for_company(
                db, company_id, skip=0, limit=50
            )
        """
        try:
            # Build query joining through Job to filter by company
            query = (
                select(Application)
                .join(Job, Application.job_id == Job.id)
                .where(Job.company_id == company_id)
                .options(
                    selectinload(Application.user),
                    selectinload(Application.job)
                )
                .order_by(desc(Application.created_at))
            )

            # Add status filter if provided
            if status_filter:
                query = query.where(Application.status == status_filter)

            # Get paginated results
            paginated_query = query.offset(skip).limit(limit)
            result = await db.execute(paginated_query)
            applications = list(result.scalars().all())

            # Get total count with same filters
            count_query = (
                select(func.count())
                .select_from(Application)
                .join(Job, Application.job_id == Job.id)
                .where(Job.company_id == company_id)
            )
            if status_filter:
                count_query = count_query.where(Application.status == status_filter)

            count_result = await db.execute(count_query)
            total = count_result.scalar_one()

            return applications, total

        except SQLAlchemyError as e:
            logger.error(f"Error fetching applications for company {company_id}: {e}")
            raise

    async def get_job_application_counts(
        self,
        db: AsyncSession,
        job_ids: list[UUID]
    ) -> dict[UUID, dict]:
        """
        Get application counts by status for multiple jobs.

        This performs a single optimized query using GROUP BY and CASE
        to count applications in different statuses for each job.

        Args:
            db: Active database session
            job_ids: List of job UUIDs

        Returns:
            Dictionary mapping job_id to counts:
            {
                job_id: {
                    "total": 10,
                    "pending": 5,
                    "accepted": 3,
                    "rejected": 2
                }
            }

        Example:
            counts = await repo.get_job_application_counts(db, [job1_id, job2_id])
            print(f"Job 1 has {counts[job1_id]['total']} applications")
        """
        try:
            if not job_ids:
                return {}

            # Build query with conditional counts
            # Map frontend statuses: pending (in-progress), accepted (HIRED), rejected (REJECTED)
            query = (
                select(
                    Application.job_id,
                    func.count(Application.id).label('total'),
                    func.sum(
                        case(
                            (Application.status.in_([
                                'SUBMITTED',
                                'WAITING_FOR_REVIEW',
                                'HR_MEETING',
                                'TECHNICAL_INTERVIEW',
                                'FINAL_INTERVIEW'
                            ]), 1),
                            else_=0
                        )
                    ).label('pending'),
                    func.sum(
                        case((Application.status == 'HIRED', 1), else_=0)
                    ).label('accepted'),
                    func.sum(
                        case((Application.status == 'REJECTED', 1), else_=0)
                    ).label('rejected')
                )
                .where(Application.job_id.in_(job_ids))
                .group_by(Application.job_id)
            )

            result = await db.execute(query)
            rows = result.all()

            # Convert to dictionary format
            counts = {}
            for row in rows:
                counts[row.job_id] = {
                    "total": row.total or 0,
                    "pending": row.pending or 0,
                    "accepted": row.accepted or 0,
                    "rejected": row.rejected or 0
                }

            # Fill in zeros for jobs with no applications
            for job_id in job_ids:
                if job_id not in counts:
                    counts[job_id] = {
                        "total": 0,
                        "pending": 0,
                        "accepted": 0,
                        "rejected": 0
                    }

            return counts

        except SQLAlchemyError as e:
            logger.error(f"Error fetching application counts for jobs: {e}")
            raise

    async def get_recent_applicants(
        self,
        db: AsyncSession,
        job_id: UUID,
        limit: int = 3
    ) -> list[dict]:
        """
        Get recent applicants for a job with basic user information.

        Args:
            db: Active database session
            job_id: UUID of the job
            limit: Maximum number of applicants to return (default: 3)

        Returns:
            List of dictionaries with applicant information:
            [
                {
                    "user_full_name": "John Doe",
                    "user_email": "john@example.com",
                    "status": "SUBMITTED",
                    "created_at": datetime(...)
                }
            ]

        Example:
            recent = await repo.get_recent_applicants(db, job_id, limit=5)
            for applicant in recent:
                print(f"{applicant['user_email']} applied on {applicant['created_at']}")
        """
        try:
            query = (
                select(
                    User.full_name,
                    User.email,
                    Application.status,
                    Application.created_at
                )
                .join(User, Application.user_id == User.id)
                .where(Application.job_id == job_id)
                .order_by(desc(Application.created_at))
                .limit(limit)
            )

            result = await db.execute(query)
            rows = result.all()

            return [
                {
                    "user_full_name": row.full_name,
                    "user_email": row.email,
                    "status": row.status,
                    "created_at": row.created_at
                }
                for row in rows
            ]

        except SQLAlchemyError as e:
            logger.error(f"Error fetching recent applicants for job {job_id}: {e}")
            raise

    async def get_company_statistics(
        self,
        db: AsyncSession,
        company_id: UUID
    ) -> dict:
        """
        Get application statistics for a company.

        Performs aggregations to calculate:
        - Total applications
        - Applications in last 30 days
        - Applications in last 7 days
        - Conversion rate (accepted / total)

        Args:
            db: Active database session
            company_id: UUID of the company

        Returns:
            Dictionary with statistics:
            {
                "total_applications": 150,
                "applications_last_30_days": 45,
                "applications_last_7_days": 12,
                "conversion_rate": 0.25
            }

        Example:
            stats = await repo.get_company_statistics(db, company_id)
            print(f"Conversion rate: {stats['conversion_rate'] * 100:.1f}%")
        """
        try:
            now = datetime.utcnow()
            thirty_days_ago = now - timedelta(days=30)
            seven_days_ago = now - timedelta(days=7)

            # Single query with multiple aggregations
            query = (
                select(
                    func.count(Application.id).label('total'),
                    func.sum(
                        case(
                            (Application.created_at >= thirty_days_ago, 1),
                            else_=0
                        )
                    ).label('last_30_days'),
                    func.sum(
                        case(
                            (Application.created_at >= seven_days_ago, 1),
                            else_=0
                        )
                    ).label('last_7_days'),
                    func.sum(
                        case((Application.status == 'HIRED', 1), else_=0)
                    ).label('accepted')
                )
                .select_from(Application)
                .join(Job, Application.job_id == Job.id)
                .where(Job.company_id == company_id)
            )

            result = await db.execute(query)
            row = result.one()

            total = row.total or 0
            accepted = row.accepted or 0
            conversion_rate = (accepted / total) if total > 0 else 0.0

            return {
                "total_applications": total,
                "applications_last_30_days": row.last_30_days or 0,
                "applications_last_7_days": row.last_7_days or 0,
                "conversion_rate": conversion_rate
            }

        except SQLAlchemyError as e:
            logger.error(f"Error fetching company statistics for {company_id}: {e}")
            raise
