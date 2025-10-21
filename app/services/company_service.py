"""
Company service for business logic related to company management.

This module handles company operations including fetching company data,
updating company information, and retrieving company statistics.
"""

from __future__ import annotations
from typing import Optional
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.models.company import Company
from app.models.user import User, UserRole
from app.repositories.company_repository import CompanyRepository

logger = logging.getLogger(__name__)


class CompanyService:
    """
    Service for managing companies.

    This service coordinates company operations with proper business
    logic and authorization checks.
    """

    def __init__(
        self,
        company_repo: Optional[CompanyRepository] = None
    ):
        """
        Initialize service with repository.

        Args:
            company_repo: CompanyRepository instance (creates new if None)
        """
        self.company_repo = company_repo or CompanyRepository()

    async def get_company_with_stats(
        self,
        db: AsyncSession,
        company_id: UUID
    ) -> tuple[Company, int, int]:
        """
        Get company information with statistics.

        Args:
            db: Active database session
            company_id: UUID of the company

        Returns:
            Tuple of (Company instance, job_count, employee_count)

        Raises:
            HTTPException: 404 if company not found

        Example:
            company, jobs, employees = await service.get_company_with_stats(db, company_id)
            print(f"{company.name} has {jobs} jobs and {employees} employees")
        """
        try:
            company, job_count, employee_count = await self.company_repo.get_company_with_stats(
                db, company_id
            )

            if not company:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Company {company_id} not found"
                )

            return company, job_count, employee_count

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting company {company_id} with stats: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve company information"
            )

    async def update_company(
        self,
        db: AsyncSession,
        company_id: UUID,
        company_update: dict,
        current_user: User
    ) -> Company:
        """
        Update company information.

        Only company admins can update company information, and they can
        only update their own company.

        Args:
            db: Active database session
            company_id: UUID of the company to update
            company_update: Dictionary with fields to update
            current_user: Current authenticated user

        Returns:
            Updated Company instance

        Raises:
            HTTPException: 404 if not found, 403 if unauthorized

        Example:
            company = await service.update_company(
                db,
                company_id,
                {"description": "We build amazing products", "size": "51-200"},
                current_user
            )
            await db.commit()
        """
        try:
            # Verify user is a company admin
            if current_user.role != UserRole.COMPANY_ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only company admins can update company information"
                )

            # Verify user belongs to the company
            if not current_user.company_id or current_user.company_id != company_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only update your own company"
                )

            # Get existing company
            company = await self.company_repo.get(db, company_id)
            if not company:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Company {company_id} not found"
                )

            # Prevent updating certain protected fields
            protected_fields = {"id", "created_at", "is_verified"}
            for field in protected_fields:
                if field in company_update:
                    del company_update[field]
                    logger.warning(
                        f"Attempted to update protected field '{field}' by user {current_user.id}"
                    )

            # Update company
            updated_company = await self.company_repo.update(db, company, company_update)

            logger.info(f"Company {company_id} updated by user {current_user.id}")

            return updated_company

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating company {company_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update company"
            )

    async def get_companies_list(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[list[Company], int]:
        """
        Get list of active and verified companies.

        This is used for public company listings.

        Args:
            db: Active database session
            skip: Number of records to skip (offset)
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of companies, total count)

        Example:
            companies, total = await service.get_companies_list(db, skip=0, limit=20)
            for company in companies:
                print(f"{company.name} - {company.industry}")
        """
        try:
            companies, total = await self.company_repo.get_active_companies(
                db, skip=skip, limit=limit
            )

            return companies, total

        except Exception as e:
            logger.error(f"Error getting companies list: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve companies"
            )

    async def get_company_by_id(
        self,
        db: AsyncSession,
        company_id: UUID
    ) -> Company:
        """
        Get company by ID.

        Args:
            db: Active database session
            company_id: UUID of the company

        Returns:
            Company instance

        Raises:
            HTTPException: 404 if not found

        Example:
            company = await service.get_company_by_id(db, company_id)
            print(company.name)
        """
        try:
            company = await self.company_repo.get(db, company_id)
            if not company:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Company {company_id} not found"
                )

            return company

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting company {company_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve company"
            )

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
            companies, total = await service.search_companies(
                db,
                search_term="Tech",
                industry="Software",
                location="San Francisco"
            )
        """
        try:
            companies, total = await self.company_repo.search_companies(
                db,
                search_term=search_term,
                industry=industry,
                location=location,
                skip=skip,
                limit=limit
            )

            return companies, total

        except Exception as e:
            logger.error(f"Error searching companies: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to search companies"
            )

    async def verify_company_ownership(
        self,
        current_user: User,
        company_id: UUID
    ) -> None:
        """
        Verify that a user owns/belongs to a company.

        Args:
            current_user: Current authenticated user
            company_id: UUID of the company

        Raises:
            HTTPException: 403 if user doesn't belong to the company

        Example:
            await service.verify_company_ownership(current_user, company_id)
        """
        if not current_user.company_id or current_user.company_id != company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this company"
            )
