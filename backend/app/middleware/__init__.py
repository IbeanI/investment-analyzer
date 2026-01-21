# backend/app/middleware/__init__.py
"""
Middleware components for the Investment Portfolio Analyzer.

This package contains ASGI middleware for:
- Correlation ID tracking for request tracing
- Rate limiting for API protection

Usage:
    from app.middleware import CorrelationIdMiddleware, limiter

    app.add_middleware(CorrelationIdMiddleware)
    app.state.limiter = limiter
"""

from app.middleware.correlation import CorrelationIdMiddleware
from app.middleware.rate_limit import (
    limiter,
    rate_limit_exceeded_handler,
    SlowAPIMiddleware,
    RATE_LIMIT_DEFAULT,
    RATE_LIMIT_WRITE,
    RATE_LIMIT_SYNC,
    RATE_LIMIT_UPLOAD,
    RATE_LIMIT_HEALTH,
    RATE_LIMIT_ANALYTICS,
)

__all__ = [
    "CorrelationIdMiddleware",
    "limiter",
    "rate_limit_exceeded_handler",
    "SlowAPIMiddleware",
    "RATE_LIMIT_DEFAULT",
    "RATE_LIMIT_WRITE",
    "RATE_LIMIT_SYNC",
    "RATE_LIMIT_UPLOAD",
    "RATE_LIMIT_HEALTH",
    "RATE_LIMIT_ANALYTICS",
]
