"""
Pagination utilities for consistent pagination across the API.

This module provides helper functions and models for implementing
cursor-based and offset-based pagination patterns.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional
import math


def calculate_offset(page: int, limit: int) -> int:
    """
    Calculate database offset from page number and limit.

    Args:
        page: Page number (1-indexed)
        limit: Number of items per page

    Returns:
        Database offset (0-indexed)

    Example:
        >>> calculate_offset(1, 20)
        0
        >>> calculate_offset(2, 20)
        20
        >>> calculate_offset(3, 10)
        20
    """
    if page < 1:
        raise ValueError("Page must be >= 1")
    if limit < 1:
        raise ValueError("Limit must be >= 1")

    return (page - 1) * limit


def calculate_total_pages(total: int, limit: int) -> int:
    """
    Calculate total number of pages given total items and page size.

    Args:
        total: Total number of items
        limit: Number of items per page

    Returns:
        Total number of pages (minimum 0)

    Example:
        >>> calculate_total_pages(100, 20)
        5
        >>> calculate_total_pages(95, 20)
        5
        >>> calculate_total_pages(0, 20)
        0
    """
    if total < 0:
        raise ValueError("Total must be >= 0")
    if limit < 1:
        raise ValueError("Limit must be >= 1")

    if total == 0:
        return 0

    return math.ceil(total / limit)


class PaginationParams(BaseModel):
    """
    Pydantic model for pagination query parameters with validation.

    Attributes:
        page: Page number (1-indexed, default: 1)
        limit: Items per page (1-100, default: 20)

    Example:
        >>> params = PaginationParams(page=2, limit=50)
        >>> params.page
        2
        >>> params.limit
        50
    """
    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    limit: int = Field(default=20, ge=1, le=100, description="Items per page (max 100)")

    @field_validator('page')
    @classmethod
    def validate_page(cls, v: int) -> int:
        """Validate page is a positive integer."""
        if v < 1:
            raise ValueError('page must be >= 1')
        return v

    @field_validator('limit')
    @classmethod
    def validate_limit(cls, v: int) -> int:
        """Validate limit is between 1 and 100."""
        if v < 1:
            raise ValueError('limit must be >= 1')
        if v > 100:
            raise ValueError('limit must be <= 100')
        return v

    def get_offset(self) -> int:
        """Calculate database offset from page and limit."""
        return calculate_offset(self.page, self.limit)


class PaginationMeta(BaseModel):
    """
    Metadata for paginated responses.

    Attributes:
        page: Current page number
        limit: Items per page
        total: Total number of items
        total_pages: Total number of pages
        has_next: Whether there is a next page
        has_previous: Whether there is a previous page
    """
    page: int
    limit: int
    total: int
    total_pages: int
    has_next: bool
    has_previous: bool

    @classmethod
    def from_params(
        cls,
        params: PaginationParams,
        total: int
    ) -> "PaginationMeta":
        """
        Create pagination metadata from parameters and total count.

        Args:
            params: Pagination parameters
            total: Total number of items

        Returns:
            PaginationMeta instance
        """
        total_pages = calculate_total_pages(total, params.limit)
        has_next = params.page < total_pages
        has_previous = params.page > 1

        return cls(
            page=params.page,
            limit=params.limit,
            total=total,
            total_pages=total_pages,
            has_next=has_next,
            has_previous=has_previous
        )
