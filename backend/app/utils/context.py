# backend/app/utils/context.py
"""
Request context management for the Investment Portfolio Analyzer.

This module provides thread-safe context storage for request-scoped data:
- Correlation ID for request tracing
- User ID (future: when auth is implemented)
- Other request metadata

Uses Python's contextvars for async-safe storage that automatically
propagates through async/await calls.

Usage:
    from app.utils.context import get_correlation_id, set_correlation_id

    # In middleware
    set_correlation_id("abc-123")

    # In any service/handler
    correlation_id = get_correlation_id()  # Returns "abc-123"
"""

from contextvars import ContextVar
from typing import Any

# =============================================================================
# CONTEXT VARIABLES
# =============================================================================

# Correlation ID for request tracing
_correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# Additional request context (extensible)
_request_context_var: ContextVar[dict[str, Any]] = ContextVar("request_context", default={})


# =============================================================================
# CORRELATION ID
# =============================================================================

def get_correlation_id() -> str | None:
    """
    Get the current request's correlation ID.

    Returns:
        The correlation ID for the current request, or None if not set.
    """
    return _correlation_id_var.get()


def set_correlation_id(correlation_id: str) -> None:
    """
    Set the correlation ID for the current request.

    This should be called by middleware at the start of each request.

    Args:
        correlation_id: Unique identifier for this request
    """
    _correlation_id_var.set(correlation_id)


def clear_correlation_id() -> None:
    """
    Clear the correlation ID.

    This should be called by middleware at the end of each request.
    """
    _correlation_id_var.set(None)


# =============================================================================
# EXTENDED CONTEXT (for future use)
# =============================================================================

def get_request_context() -> dict[str, Any]:
    """
    Get the full request context dictionary.

    Returns:
        Dictionary containing all request context data.
    """
    return _request_context_var.get().copy()


def set_request_context(key: str, value: Any) -> None:
    """
    Set a value in the request context.

    Args:
        key: Context key
        value: Context value
    """
    ctx = _request_context_var.get().copy()
    ctx[key] = value
    _request_context_var.set(ctx)


def clear_request_context() -> None:
    """
    Clear all request context.

    This should be called by middleware at the end of each request.
    """
    _request_context_var.set({})
