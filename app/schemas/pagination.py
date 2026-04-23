"""
Shared pagination schemas.

New code should import from here rather than app.schemas.company.
CursorPaginatedResponse is the preferred pattern for list endpoints.
OffsetPaginatedResponse is reserved for search endpoints where page-jumping is needed.
"""
from app.schemas.company import CursorPaginatedResponse, PaginatedResponse

__all__ = ["CursorPaginatedResponse", "PaginatedResponse"]
