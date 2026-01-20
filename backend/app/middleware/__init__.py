# backend/app/middleware/__init__.py
"""
Middleware components for the Investment Portfolio Analyzer.

This package contains ASGI middleware for:
- Correlation ID tracking for request tracing
- (future) Request timing and metrics
- (future) Rate limiting

Usage:
    from app.middleware import CorrelationIdMiddleware

    app.add_middleware(CorrelationIdMiddleware)
"""

from app.middleware.correlation import CorrelationIdMiddleware

__all__ = [
    "CorrelationIdMiddleware",
]
