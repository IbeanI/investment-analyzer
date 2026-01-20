# backend/app/schemas/pagination.py
"""
Standardized pagination schemas for list endpoints.

This module provides reusable pagination components:
- PaginationParams: Query parameter handling
- PaginationMeta: Response metadata with computed fields
- Paginated[T]: Generic paginated response wrapper

Usage:
    from app.schemas.pagination import PaginationMeta, paginate

    # In router
    @router.get("/items")
    def list_items(
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        items = db.query(Item).offset(skip).limit(limit).all()
        total = db.query(func.count(Item.id)).scalar()

        return {
            "items": items,
            "pagination": PaginationMeta.create(
                total=total,
                skip=skip,
                limit=limit,
            ),
        }

Pagination Metadata:
    - total: Total items matching query
    - skip: Items skipped (offset)
    - limit: Max items per page
    - page: Current page number (1-indexed)
    - pages: Total number of pages
    - has_next: Whether more pages exist
    - has_previous: Whether previous pages exist
"""

from typing import Generic, TypeVar
from pydantic import BaseModel, Field, computed_field

T = TypeVar("T")


class PaginationMeta(BaseModel):
    """
    Pagination metadata for list responses.

    Provides computed fields for convenient client-side pagination handling.

    Attributes:
        total: Total number of items matching the query
        skip: Number of items skipped (offset)
        limit: Maximum items returned per page
        page: Current page number (1-indexed, computed)
        pages: Total number of pages (computed)
        has_next: Whether there are more pages (computed)
        has_previous: Whether there are previous pages (computed)
    """

    total: int = Field(..., ge=0, description="Total number of items matching query")
    skip: int = Field(..., ge=0, description="Number of items skipped (offset)")
    limit: int = Field(..., ge=1, description="Maximum items per page")

    @computed_field
    @property
    def page(self) -> int:
        """Current page number (1-indexed)."""
        if self.limit <= 0:
            return 1
        return (self.skip // self.limit) + 1

    @computed_field
    @property
    def pages(self) -> int:
        """Total number of pages."""
        if self.limit <= 0 or self.total <= 0:
            return 1
        return (self.total + self.limit - 1) // self.limit  # Ceiling division

    @computed_field
    @property
    def has_next(self) -> bool:
        """Whether there are more pages after current."""
        return self.skip + self.limit < self.total

    @computed_field
    @property
    def has_previous(self) -> bool:
        """Whether there are pages before current."""
        return self.skip > 0

    @classmethod
    def create(cls, total: int, skip: int, limit: int) -> "PaginationMeta":
        """
        Factory method to create pagination metadata.

        Args:
            total: Total items matching query
            skip: Items to skip (offset)
            limit: Max items per page

        Returns:
            PaginationMeta instance
        """
        return cls(total=total, skip=skip, limit=limit)


class PaginatedResponse(BaseModel, Generic[T]):
    """
    Generic paginated response wrapper.

    Can be used as a base for typed paginated responses.

    Example:
        class UserListResponse(PaginatedResponse[UserResponse]):
            pass
    """

    items: list[T] = Field(..., description="List of items for current page")
    pagination: PaginationMeta = Field(..., description="Pagination metadata")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def create_pagination_meta(total: int, skip: int, limit: int) -> PaginationMeta:
    """
    Create pagination metadata from query results.

    Convenience function for creating PaginationMeta in routers.

    Args:
        total: Total items matching query
        skip: Items skipped (offset)
        limit: Max items per page

    Returns:
        PaginationMeta with computed fields
    """
    return PaginationMeta.create(total=total, skip=skip, limit=limit)


# =============================================================================
# BACKWARD COMPATIBLE DICT HELPER
# =============================================================================

def paginate_dict(total: int, skip: int, limit: int) -> dict:
    """
    Create pagination dict for backward compatibility.

    Returns a dict that includes both old fields (total, skip, limit)
    and new computed fields (page, pages, has_next, has_previous).

    Args:
        total: Total items matching query
        skip: Items skipped (offset)
        limit: Max items per page

    Returns:
        Dict with all pagination fields
    """
    meta = PaginationMeta.create(total=total, skip=skip, limit=limit)
    return {
        "total": meta.total,
        "skip": meta.skip,
        "limit": meta.limit,
        "page": meta.page,
        "pages": meta.pages,
        "has_next": meta.has_next,
        "has_previous": meta.has_previous,
    }
