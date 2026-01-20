# tests/schemas/test_pagination.py
"""
Tests for the pagination schema implementation.
"""

import pytest
from pydantic import ValidationError

from app.schemas.pagination import (
    PaginationMeta,
    PaginatedResponse,
    create_pagination_meta,
    paginate_dict,
)


class TestPaginationMeta:
    """Tests for PaginationMeta class."""

    def test_create_basic(self):
        """Should create pagination meta with basic values."""
        meta = PaginationMeta.create(total=100, skip=0, limit=10)

        assert meta.total == 100
        assert meta.skip == 0
        assert meta.limit == 10

    def test_page_calculation_first_page(self):
        """Should calculate page 1 when skip=0."""
        meta = PaginationMeta.create(total=100, skip=0, limit=10)
        assert meta.page == 1

    def test_page_calculation_second_page(self):
        """Should calculate page 2 when skip=limit."""
        meta = PaginationMeta.create(total=100, skip=10, limit=10)
        assert meta.page == 2

    def test_page_calculation_middle_page(self):
        """Should calculate correct page in middle of results."""
        meta = PaginationMeta.create(total=100, skip=50, limit=10)
        assert meta.page == 6

    def test_page_calculation_last_page(self):
        """Should calculate correct page at end."""
        meta = PaginationMeta.create(total=100, skip=90, limit=10)
        assert meta.page == 10

    def test_pages_calculation_exact(self):
        """Should calculate pages when total is divisible by limit."""
        meta = PaginationMeta.create(total=100, skip=0, limit=10)
        assert meta.pages == 10

    def test_pages_calculation_with_remainder(self):
        """Should round up pages when total has remainder."""
        meta = PaginationMeta.create(total=105, skip=0, limit=10)
        assert meta.pages == 11

    def test_pages_calculation_single_page(self):
        """Should return 1 page when total < limit."""
        meta = PaginationMeta.create(total=5, skip=0, limit=10)
        assert meta.pages == 1

    def test_pages_calculation_empty_results(self):
        """Should return 1 page when total is 0."""
        meta = PaginationMeta.create(total=0, skip=0, limit=10)
        assert meta.pages == 1

    def test_has_next_true(self):
        """Should return True when more pages exist."""
        meta = PaginationMeta.create(total=100, skip=0, limit=10)
        assert meta.has_next is True

    def test_has_next_false_last_page(self):
        """Should return False on last page."""
        meta = PaginationMeta.create(total=100, skip=90, limit=10)
        assert meta.has_next is False

    def test_has_next_false_beyond_total(self):
        """Should return False when skip + limit >= total."""
        meta = PaginationMeta.create(total=100, skip=95, limit=10)
        assert meta.has_next is False

    def test_has_previous_false_first_page(self):
        """Should return False on first page."""
        meta = PaginationMeta.create(total=100, skip=0, limit=10)
        assert meta.has_previous is False

    def test_has_previous_true(self):
        """Should return True when previous pages exist."""
        meta = PaginationMeta.create(total=100, skip=10, limit=10)
        assert meta.has_previous is True

    def test_validation_total_negative(self):
        """Should reject negative total."""
        with pytest.raises(ValidationError):
            PaginationMeta(total=-1, skip=0, limit=10)

    def test_validation_skip_negative(self):
        """Should reject negative skip."""
        with pytest.raises(ValidationError):
            PaginationMeta(total=100, skip=-1, limit=10)

    def test_validation_limit_zero(self):
        """Should reject limit of 0."""
        with pytest.raises(ValidationError):
            PaginationMeta(total=100, skip=0, limit=0)

    def test_serialization(self):
        """Should serialize all fields including computed ones."""
        meta = PaginationMeta.create(total=100, skip=20, limit=10)
        data = meta.model_dump()

        assert data["total"] == 100
        assert data["skip"] == 20
        assert data["limit"] == 10
        assert data["page"] == 3
        assert data["pages"] == 10
        assert data["has_next"] is True
        assert data["has_previous"] is True


class TestPaginatedResponse:
    """Tests for generic PaginatedResponse class."""

    def test_paginated_response_creation(self):
        """Should create paginated response with items and pagination."""
        from pydantic import BaseModel

        class Item(BaseModel):
            id: int
            name: str

        items = [Item(id=1, name="test1"), Item(id=2, name="test2")]
        pagination = PaginationMeta.create(total=2, skip=0, limit=10)

        response = PaginatedResponse[Item](items=items, pagination=pagination)

        assert len(response.items) == 2
        assert response.items[0].id == 1
        assert response.pagination.total == 2


class TestHelperFunctions:
    """Tests for pagination helper functions."""

    def test_create_pagination_meta(self):
        """Should create PaginationMeta via helper function."""
        meta = create_pagination_meta(total=50, skip=10, limit=10)

        assert meta.total == 50
        assert meta.skip == 10
        assert meta.limit == 10
        assert meta.page == 2

    def test_paginate_dict(self):
        """Should return dict with all pagination fields."""
        result = paginate_dict(total=100, skip=20, limit=10)

        assert result["total"] == 100
        assert result["skip"] == 20
        assert result["limit"] == 10
        assert result["page"] == 3
        assert result["pages"] == 10
        assert result["has_next"] is True
        assert result["has_previous"] is True


class TestEdgeCases:
    """Tests for edge cases in pagination."""

    def test_single_item_single_page(self):
        """Should handle single item correctly."""
        meta = PaginationMeta.create(total=1, skip=0, limit=10)

        assert meta.page == 1
        assert meta.pages == 1
        assert meta.has_next is False
        assert meta.has_previous is False

    def test_exact_one_page(self):
        """Should handle exactly one page of results."""
        meta = PaginationMeta.create(total=10, skip=0, limit=10)

        assert meta.page == 1
        assert meta.pages == 1
        assert meta.has_next is False
        assert meta.has_previous is False

    def test_large_skip_value(self):
        """Should handle skip larger than total."""
        meta = PaginationMeta.create(total=10, skip=100, limit=10)

        assert meta.page == 11
        assert meta.has_next is False
        assert meta.has_previous is True

    def test_large_limit_value(self):
        """Should handle very large limit."""
        meta = PaginationMeta.create(total=10, skip=0, limit=1000)

        assert meta.page == 1
        assert meta.pages == 1
        assert meta.has_next is False
        assert meta.has_previous is False

    def test_skip_not_aligned_to_limit(self):
        """Should handle skip values not aligned to limit boundaries."""
        meta = PaginationMeta.create(total=100, skip=15, limit=10)

        # page = (15 // 10) + 1 = 2
        assert meta.page == 2
        # Still has more items (15 + 10 = 25 < 100)
        assert meta.has_next is True
        assert meta.has_previous is True
