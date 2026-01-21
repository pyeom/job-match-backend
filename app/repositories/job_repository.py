"""
Job repository for managing job posting data.

This module provides specialized queries for jobs, including
company-specific queries, discovery filtering, and relationship loading.
"""

from __future__ import annotations
from typing import Optional, List
from uuid import UUID
from sqlalchemy import select, func, and_, desc, asc, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
import logging

from app.models.job import Job
from app.models.company import Company
from app.models.user import User
from .base import BaseRepository

logger = logging.getLogger(__name__)


class JobRepository(BaseRepository[Job]):
    """
    Repository for Job model with specialized queries.

    Provides methods for:
    - Company-specific job queries
    - Active job filtering
    - Job discovery with exclusions
    - Eager loading of company relationships
    """

    def __init__(self):
        """Initialize with Job model."""
        super().__init__(Job)

    async def get(
        self,
        db: AsyncSession,
        id: UUID
    ) -> Optional[Job]:
        """
        Get job by ID with company relationship loaded.

        This override loads the company relationship needed for notifications.

        Args:
            db: Active database session
            id: UUID of the job

        Returns:
            Job instance with company loaded, or None if not found

        Example:
            job = await repo.get(db, job_id)
            if job:
                print(f"{job.title} at {job.company.name}")
        """
        try:
            stmt = (
                select(Job)
                .where(Job.id == id)
                .options(selectinload(Job.company))
            )
            result = await db.execute(stmt)
            return result.scalar_one_or_none()

        except SQLAlchemyError as e:
            logger.error(f"Error fetching job {id} with company: {e}")
            raise

    async def get_company_jobs(
        self,
        db: AsyncSession,
        company_id: UUID,
        skip: int = 0,
        limit: int = 100,
        active_only: bool = True
    ) -> tuple[list[Job], int]:
        """
        Get paginated jobs for a specific company.

        Args:
            db: Active database session
            company_id: UUID of the company
            skip: Number of records to skip (offset)
            limit: Maximum number of records to return
            active_only: If True, only return active jobs (default: True)

        Returns:
            Tuple of (list of jobs, total count)

        Example:
            jobs, total = await repo.get_company_jobs(
                db, company_id, skip=0, limit=20, active_only=True
            )
        """
        try:
            # Build base query
            query = (
                select(Job)
                .where(Job.company_id == company_id)
                .order_by(desc(Job.created_at))
            )

            # Add active filter if requested
            if active_only:
                query = query.where(Job.is_active == True)

            # Get paginated results
            paginated_query = query.offset(skip).limit(limit)
            result = await db.execute(paginated_query)
            jobs = list(result.scalars().all())

            # Get total count with same filters
            count_query = (
                select(func.count())
                .select_from(Job)
                .where(Job.company_id == company_id)
            )
            if active_only:
                count_query = count_query.where(Job.is_active == True)

            count_result = await db.execute(count_query)
            total = count_result.scalar_one()

            return jobs, total

        except SQLAlchemyError as e:
            logger.error(f"Error fetching jobs for company {company_id}: {e}")
            raise

    async def get_job_with_company(
        self,
        db: AsyncSession,
        job_id: UUID
    ) -> Optional[Job]:
        """
        Get a job with its company relationship eagerly loaded.

        This is useful when you need both job and company data to avoid
        N+1 query issues.

        Args:
            db: Active database session
            job_id: UUID of the job

        Returns:
            Job instance with company loaded, or None if not found

        Example:
            job = await repo.get_job_with_company(db, job_id)
            if job:
                print(f"{job.title} at {job.company.name}")
        """
        try:
            stmt = (
                select(Job)
                .where(Job.id == job_id)
                .options(selectinload(Job.company))
            )
            result = await db.execute(stmt)
            return result.scalar_one_or_none()

        except SQLAlchemyError as e:
            logger.error(f"Error fetching job {job_id} with company: {e}")
            raise

    async def get_jobs_for_discovery(
        self,
        db: AsyncSession,
        user_id: UUID,
        limit: int = 50,
        exclude_job_ids: Optional[list[UUID]] = None
    ) -> list[Job]:
        """
        Get jobs for the discovery feed.

        Filters for:
        - Active jobs only
        - Excludes jobs the user has already swiped on
        - Orders by creation date (newest first) or score if available

        Args:
            db: Active database session
            user_id: UUID of the user (for future personalization)
            limit: Maximum number of jobs to return
            exclude_job_ids: Optional list of job IDs to exclude (already swiped)

        Returns:
            List of Job instances

        Example:
            jobs = await repo.get_jobs_for_discovery(
                db, user_id, limit=20, exclude_job_ids=swiped_ids
            )
        """
        try:
            # Build query for active jobs
            query = (
                select(Job)
                .where(Job.is_active == True)
                .options(selectinload(Job.company))
                .order_by(desc(Job.created_at))
                .limit(limit)
            )

            # Exclude already swiped jobs
            if exclude_job_ids:
                query = query.where(~Job.id.in_(exclude_job_ids))

            result = await db.execute(query)
            jobs = list(result.scalars().all())

            return jobs

        except SQLAlchemyError as e:
            logger.error(f"Error fetching discovery jobs for user {user_id}: {e}")
            raise

    async def get_active_jobs_count(
        self,
        db: AsyncSession,
        company_id: UUID
    ) -> int:
        """
        Get count of active jobs for a company.

        Args:
            db: Active database session
            company_id: UUID of the company

        Returns:
            Count of active jobs

        Example:
            count = await repo.get_active_jobs_count(db, company_id)
            print(f"Company has {count} active jobs")
        """
        try:
            stmt = (
                select(func.count())
                .select_from(Job)
                .where(and_(
                    Job.company_id == company_id,
                    Job.is_active == True
                ))
            )
            result = await db.execute(stmt)
            return result.scalar_one()

        except SQLAlchemyError as e:
            logger.error(f"Error counting active jobs for company {company_id}: {e}")
            raise

    async def get_jobs_with_companies(
        self,
        db: AsyncSession,
        job_ids: list[UUID]
    ) -> list[Job]:
        """
        Get multiple jobs with their companies eagerly loaded.

        Args:
            db: Active database session
            job_ids: List of job UUIDs

        Returns:
            List of Job instances with companies loaded

        Example:
            jobs = await repo.get_jobs_with_companies(db, [id1, id2, id3])
            for job in jobs:
                print(f"{job.title} at {job.company.name}")
        """
        try:
            if not job_ids:
                return []

            stmt = (
                select(Job)
                .where(Job.id.in_(job_ids))
                .options(selectinload(Job.company))
            )
            result = await db.execute(stmt)
            return list(result.scalars().all())

        except SQLAlchemyError as e:
            logger.error(f"Error fetching jobs with companies: {e}")
            raise

    async def search_jobs(
        self,
        db: AsyncSession,
        search_term: Optional[str] = None,
        location: Optional[str] = None,
        seniority: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[list[Job], int]:
        """
        Search jobs with filters.

        Args:
            db: Active database session
            search_term: Optional search term (searches title)
            location: Optional location filter
            seniority: Optional seniority level filter
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of jobs, total count)

        Example:
            jobs, total = await repo.search_jobs(
                db, search_term="Python", location="Remote", seniority="Senior"
            )
        """
        try:
            # Build base query
            query = select(Job).where(Job.is_active == True)

            # Add filters
            if search_term:
                query = query.where(Job.title.ilike(f"%{search_term}%"))

            if location:
                query = query.where(Job.location.ilike(f"%{location}%"))

            if seniority:
                query = query.where(Job.seniority == seniority)

            # Order and paginate
            query = query.order_by(desc(Job.created_at))

            # Get paginated results
            paginated_query = query.offset(skip).limit(limit)
            result = await db.execute(paginated_query)
            jobs = list(result.scalars().all())

            # Get total count
            count_query = select(func.count()).select_from(Job).where(Job.is_active == True)
            if search_term:
                count_query = count_query.where(Job.title.ilike(f"%{search_term}%"))
            if location:
                count_query = count_query.where(Job.location.ilike(f"%{location}%"))
            if seniority:
                count_query = count_query.where(Job.seniority == seniority)

            count_result = await db.execute(count_query)
            total = count_result.scalar_one()

            return jobs, total

        except SQLAlchemyError as e:
            logger.error(f"Error searching jobs: {e}")
            raise

    async def search_jobs_advanced(
        self,
        db: AsyncSession,
        user: Optional[User] = None,
        keyword: Optional[str] = None,
        salary_min: Optional[int] = None,
        salary_max: Optional[int] = None,
        currency: Optional[str] = None,
        locations: Optional[List[str]] = None,
        work_arrangement: Optional[List[str]] = None,
        seniority_levels: Optional[List[str]] = None,
        job_types: Optional[List[str]] = None,
        skills: Optional[List[str]] = None,
        sort_by: str = "match_score",
        sort_order: str = "desc",
        skip: int = 0,
        limit: int = 20
    ) -> tuple[list[tuple[Job, int]], int]:
        """
        Advanced job search with comprehensive filters and ML-based scoring.

        Args:
            db: Active database session
            user: Optional user for personalized scoring
            keyword: Search job title, company name, description
            salary_min: Minimum salary filter
            salary_max: Maximum salary filter
            currency: Currency filter (USD, EUR, etc.)
            locations: Multi-select location filter
            work_arrangement: Remote/Hybrid/On-site filter
            seniority_levels: Seniority levels filter
            job_types: Job types filter
            skills: Skills/tags filter
            sort_by: Sort field (match_score, posted_date, salary)
            sort_order: Sort order (asc, desc)
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            Tuple of (list of (job, score) tuples, total count)

        Example:
            jobs, total = await repo.search_jobs_advanced(
                db, user=current_user, keyword="Python",
                seniority_levels=["Mid", "Senior"], skills=["FastAPI"]
            )
        """
        try:
            from app.services.scoring_service import scoring_service

            # Build base query with company relationship
            query = (
                select(Job)
                .options(selectinload(Job.company))
                .where(Job.is_active == True)
            )

            # Apply keyword filter (searches title, company name, description)
            if keyword:
                keyword_filter = or_(
                    Job.title.ilike(f"%{keyword}%"),
                    Job.short_description.ilike(f"%{keyword}%"),
                    Job.description.ilike(f"%{keyword}%"),
                    Company.name.ilike(f"%{keyword}%")
                )
                query = query.join(Company).where(keyword_filter)
            else:
                # Still need to join for ordering/filtering by company if needed
                query = query.join(Company)

            # Apply salary filters
            if salary_min is not None:
                query = query.where(Job.salary_min >= salary_min)
            if salary_max is not None:
                query = query.where(Job.salary_max <= salary_max)

            # Apply currency filter
            if currency:
                query = query.where(Job.currency == currency)

            # Apply location filters
            if locations:
                location_conditions = [Job.location.ilike(f"%{loc}%") for loc in locations]
                query = query.where(or_(*location_conditions))

            # Apply work arrangement filter
            if work_arrangement:
                query = query.where(Job.work_arrangement.in_(work_arrangement))

            # Apply seniority filter
            if seniority_levels:
                query = query.where(Job.seniority.in_(seniority_levels))

            # Apply job type filter
            if job_types:
                query = query.where(Job.job_type.in_(job_types))

            # Apply skills/tags filter (check if ANY of the skills match)
            if skills:
                # Use JSON contains for array overlap
                skills_conditions = [
                    func.jsonb_exists(Job.tags.cast(JSONB), skill)
                    for skill in skills
                ]
                query = query.where(or_(*skills_conditions))

            # Get total count before pagination
            count_query = select(func.count()).select_from(query.subquery())
            count_result = await db.execute(count_query)
            total = count_result.scalar_one()

            # For ML-based scoring, fetch larger candidate pool
            if sort_by == "match_score" and user and user.profile_embedding is not None:
                # Fetch more candidates for re-ranking (up to 500 or 10x limit)
                candidate_limit = min(500, limit * 10)

                # Order by vector similarity initially
                candidate_query = query.order_by(
                    Job.job_embedding.cosine_distance(user.profile_embedding)
                ).limit(candidate_limit)

                result = await db.execute(candidate_query)
                candidate_jobs = list(result.scalars().all())

                # Re-rank with full hybrid scoring
                scored_jobs = []
                for job in candidate_jobs:
                    if job.job_embedding is not None:
                        try:
                            score = scoring_service.calculate_job_score(
                                user_embedding=user.profile_embedding,
                                job_embedding=job.job_embedding,
                                user_skills=user.skills,
                                user_seniority=user.seniority,
                                user_preferences=user.preferred_locations,
                                job_tags=job.tags,
                                job_seniority=job.seniority,
                                job_location=job.location,
                                job_remote=job.remote or False,
                                job_created_at=job.created_at
                            )
                            scored_jobs.append((job, score))
                        except Exception as e:
                            logger.error(f"ML scoring failed for job {job.id}: {e}")
                            scored_jobs.append((job, 70))
                    else:
                        scored_jobs.append((job, 60))

                # Sort by score
                if sort_order == "asc":
                    scored_jobs.sort(key=lambda x: x[1])
                else:
                    scored_jobs.sort(key=lambda x: x[1], reverse=True)

                # Apply pagination
                paginated_jobs = scored_jobs[skip:skip + limit]

                return paginated_jobs, total

            else:
                # Simple sorting without ML scoring
                if sort_by == "posted_date":
                    order_col = Job.created_at
                elif sort_by == "salary":
                    order_col = Job.salary_max
                else:
                    # Default to created_at for non-ML users
                    order_col = Job.created_at

                if sort_order == "asc":
                    query = query.order_by(asc(order_col))
                else:
                    query = query.order_by(desc(order_col))

                # Apply pagination
                paginated_query = query.offset(skip).limit(limit)
                result = await db.execute(paginated_query)
                jobs = list(result.scalars().all())

                # Return jobs with default scores
                scored_jobs = [(job, 65) for job in jobs]

                return scored_jobs, total

        except SQLAlchemyError as e:
            logger.error(f"Error in advanced job search: {e}")
            raise
