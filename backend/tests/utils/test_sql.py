# tests/utils/test_sql.py
"""
Tests for SQL utility functions.
"""

import pytest

from app.utils.sql import escape_like_pattern


class TestEscapeLikePattern:
    """Tests for escape_like_pattern function."""

    def test_escape_percent_wildcard(self):
        """Should escape % wildcard."""
        assert escape_like_pattern("test%value") == "test\\%value"

    def test_escape_underscore_wildcard(self):
        """Should escape _ wildcard."""
        assert escape_like_pattern("test_value") == "test\\_value"

    def test_escape_backslash(self):
        """Should escape backslash."""
        assert escape_like_pattern("test\\value") == "test\\\\value"

    def test_escape_multiple_wildcards(self):
        """Should escape multiple wildcards."""
        assert escape_like_pattern("%test%_value_") == "\\%test\\%\\_value\\_"

    def test_no_escape_needed(self):
        """Should return unchanged if no special characters."""
        assert escape_like_pattern("normalvalue") == "normalvalue"

    def test_empty_string(self):
        """Should handle empty string."""
        assert escape_like_pattern("") == ""

    def test_only_wildcards(self):
        """Should escape string of only wildcards."""
        assert escape_like_pattern("%_") == "\\%\\_"

    def test_escape_order_matters(self):
        """Should escape backslash before wildcards to avoid double escaping."""
        # If we have \% in input, it should become \\% (escaped backslash + escaped percent)
        assert escape_like_pattern("\\%") == "\\\\\\%"

    def test_real_world_example(self):
        """Test realistic user input scenarios."""
        # User searching for "50% off"
        assert escape_like_pattern("50% off") == "50\\% off"
        # User searching for file pattern
        assert escape_like_pattern("file_name.txt") == "file\\_name.txt"
