# backend/app/utils/sql.py
"""
SQL utility functions.

This module provides utilities for safe SQL query construction:
- escape_like_pattern: Escape special characters in LIKE patterns

Usage:
    from app.utils.sql import escape_like_pattern

    # Safely build a search pattern
    user_input = "test%_value"
    safe_pattern = f"%{escape_like_pattern(user_input)}%"
    query = query.where(Column.name.ilike(safe_pattern))
"""


def escape_like_pattern(value: str) -> str:
    """
    Escape special characters in a SQL LIKE pattern.

    SQL LIKE patterns use special characters:
    - % matches any sequence of characters
    - _ matches any single character
    - \\ is the escape character

    If user input contains these characters, they could manipulate
    the query behavior. This function escapes them to be treated literally.

    Args:
        value: The user-provided search string

    Returns:
        The escaped string safe for use in LIKE patterns

    Example:
        >>> escape_like_pattern("test%value")
        'test\\\\%value'
        >>> escape_like_pattern("test_value")
        'test\\\\_value'
        >>> escape_like_pattern("normal")
        'normal'
    """
    # Escape backslash first (since it's the escape character)
    # Then escape the wildcards
    return (
        value
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
