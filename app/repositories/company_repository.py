"""
Company repository for managing company data.

This module provides specialized queries for companies, including
filtering by status, aggregating statistics, and relationship loading.
"""

from __future__ import annotations
from typing import Optional
from uuid import UUID
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
import logging

from app.models.company import Company
from app.models.job import Job
from app.models.user import User
from .base import BaseRepository

logger = logging.getLogger(__name__)


class CompanyRepository(BaseRepository[Company]):
    """
    Repository for Company model with specialized queries.

    Provides methods for:
    - Active/verified company filtering
    - Company statistics (job count, employee count)
    - Batch operations
    """

    def __init__(self):
        """Initialize with Company model."""
        super().__init__(Company)

    async def get_active_companies(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[list[Company], int]:
        """
        Get paginated active and verified companies.

        Filters for companies that are both active and verified,
        suitable for public listings.

        Args:
            db: Active database session
            skip: Number of records to skip (offset)
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of companies, total count)

        Example:
            companies, total = await repo.get_active_companies(db, skip=0, limit=20)
        """
        try:
            # Build query for active and verified companies
            query = (
                select(Company)
                .where(and_(
                    Company.is_active == True,
                    Company.is_verified == True
                ))
                .order_by(Company.name)
            )

            # Get paginated results
            paginated_query = query.offset(skip).limit(limit)
            result = await db.execute(paginated_query)
            companies = list(result.scalars().all())

            # Get total count with same filters
            count_query = (
                select(func.count())
                .select_from(Company)
                .where(and_(
                    Company.is_active == True,
                    Company.is_verified == True
                ))
            )
            count_result = await db.execute(count_query)
            total = count_result.scalar_one()

            return companies, total

        except SQLAlchemyError as e:
            logger.error(f"Error fetching active companies: {e}")
            raise

    async def get_company_with_stats(
        self,
        db: AsyncSession,
        company_id: UUID
    ) -> tuple[Optional[Company], int, int]:
        """
        Get a company with aggregated statistics.

        Retrieves the company and calculates:
        - Number of active jobs
        - Number of employees (users belonging to the company)

        Args:
            db: Active database session
            company_id: UUID of the company

        Returns:
            Tuple of (Company instance or None, active job count, employee count)

        Example:
            company, jobs, employees = await repo.get_company_with_stats(db, company_id)
            if company:
                print(f"{company.name} has {jobs} jobs and {employees} employees")
        """
        try:
            # Get company
            company_stmt = select(Company).where(Company.id == company_id)
            company_result = await db.execute(company_stmt)
            company = company_result.scalar_one_or_none()

            if not company:
                return None, 0, 0

            # Count active jobs
            jobs_stmt = (
                select(func.count())
                .select_from(Job)
                .where(and_(
                    Job.company_id == company_id,
                    Job.is_active == True
                ))
            )
            jobs_result = await db.execute(jobs_stmt)
            job_count = jobs_result.scalar_one()

            # Count employees (users with this company_id)
            employees_stmt = (
                select(func.count())
                .select_from(User)
                .where(User.company_id == company_id)
            )
            employees_result = await db.execute(employees_stmt)
            employee_count = employees_result.scalar_one()

            return company, job_count, employee_count

        except SQLAlchemyError as e:
            logger.error(f"Error fetching company {company_id} with stats: {e}")
            raise

    async def get_by_name(
        self,
        db: AsyncSession,
        name: str
    ) -> Optional[Company]:
        """
        Get a company by exact name match.

        Args:
            db: Active database session
            name: Exact company name

        Returns:
            Company instance if found, None otherwise

        Example:
            company = await repo.get_by_name(db, "Acme Corp")
        """
        try:
            stmt = select(Company).where(Company.name == name)
            result = await db.execute(stmt)
            return result.scalar_one_or_none()

        except SQLAlchemyError as e:
            logger.error(f"Error fetching company by name '{name}': {e}")
            raise

    async def search_companies(
        self,
        db: AsyncSession,
        search_term: Optional[str] = None,
        industry: Optional[str] = None,
        location: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[list[Company], int]:
        """
        Search companies with filters.

        Args:
            db: Active database session
            search_term: Optional search term (searches name)
            industry: Optional industry filter
            location: Optional location filter
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of companies, total count)

        Example:
            companies, total = await repo.search_companies(
                db, search_term="Tech", industry="Software", location="San Francisco"
            )
        """
        try:
            # Build base query for active and verified companies
            query = select(Company).where(and_(
                Company.is_active == True,
                Company.is_verified == True
            ))

            # Add filters
            if search_term:
                query = query.where(Company.name.ilike(f"%{search_term}%"))

            if industry:
                query = query.where(Company.industry.ilike(f"%{industry}%"))

            if location:
                query = query.where(Company.location.ilike(f"%{location}%"))

            # Order and paginate
            query = query.order_by(Company.name)

            # Get paginated results
            paginated_query = query.offset(skip).limit(limit)
            result = await db.execute(paginated_query)
            companies = list(result.scalars().all())

            # Get total count
            count_query = select(func.count()).select_from(Company).where(and_(
                Company.is_active == True,
                Company.is_verified == True
            ))
            if search_term:
                count_query = count_query.where(Company.name.ilike(f"%{search_term}%"))
            if industry:
                count_query = count_query.where(Company.industry.ilike(f"%{industry}%"))
            if location:
                count_query = count_query.where(Company.location.ilike(f"%{location}%"))

            count_result = await db.execute(count_query)
            total = count_result.scalar_one()

            return companies, total

        except SQLAlchemyError as e:
            logger.error(f"Error searching companies: {e}")
            raise

    async def get_companies_by_ids(
        self,
        db: AsyncSession,
        company_ids: list[UUID]
    ) -> list[Company]:
        """
        Get multiple companies by their IDs.

        Args:
            db: Active database session
            company_ids: List of company UUIDs

        Returns:
            List of Company instances

        Example:
            companies = await repo.get_companies_by_ids(db, [id1, id2, id3])
        """
        try:
            if not company_ids:
                return []

            stmt = select(Company).where(Company.id.in_(company_ids))
            result = await db.execute(stmt)
            return list(result.scalars().all())

        except SQLAlchemyError as e:
            logger.error(f"Error fetching companies by IDs: {e}")
            raise

    async def verify_company(
        self,
        db: AsyncSession,
        company_id: UUID,
        verified: bool = True
    ) -> Optional[Company]:
        """
        Update company verification status.

        Args:
            db: Active database session
            company_id: UUID of the company
            verified: Verification status to set

        Returns:
            Updated Company instance or None if not found

        Example:
            company = await repo.verify_company(db, company_id, True)
            await db.commit()
        """
        try:
            company = await self.get(db, company_id)
            if not company:
                return None

            company.is_verified = verified
            await db.flush()
            await db.refresh(company)
            return company

        except SQLAlchemyError as e:
            logger.error(f"Error verifying company {company_id}: {e}")
            await db.rollback()
            raise
