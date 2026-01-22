# backend/app/utils/__init__.py
"""
Utility modules for the Investment Portfolio Analyzer.

This package contains cross-cutting utilities used throughout the application:
- logging: Logging configuration and setup with correlation ID support
- context: Request context management for correlation IDs
- date_utils: Date manipulation helpers (business days, etc.)
- sql: SQL query construction helpers (LIKE escaping, etc.)

Usage:
    from app.utils import setup_logging, get_logger
    from app.utils import get_correlation_id, set_correlation_id
    from app.utils import escape_like_pattern
    from app.utils.date_utils import get_business_days
"""

from app.utils.context import (
    get_correlation_id,
    set_correlation_id,
    clear_correlation_id,
    get_request_context,
    set_request_context,
    clear_request_context,
)
from app.utils.logging import setup_logging, get_logger
from app.utils.sql import escape_like_pattern

__all__ = [
    # Logging
    "setup_logging",
    "get_logger",
    # Context
    "get_correlation_id",
    "set_correlation_id",
    "clear_correlation_id",
    "get_request_context",
    "set_request_context",
    "clear_request_context",
    # SQL
    "escape_like_pattern",
]
