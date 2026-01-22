# backend/app/middleware/rate_limit.py
"""
Rate limiting middleware for API protection.

This module provides rate limiting using slowapi to:
- Prevent DoS attacks and API abuse
- Protect external API quotas (Yahoo Finance)
- Ensure fair resource distribution among clients

Rate limits are configured in app/services/constants.py and can be
customized per endpoint type (read, write, sync, upload, etc.).

Key by: Client IP address (X-Forwarded-For or direct IP)
Storage: In-memory (can be upgraded to Redis for distributed deployments)

Usage:
    from app.middleware.rate_limit import limiter, RATE_LIMIT_DEFAULT

    @router.get("/items")
    @limiter.limit(RATE_LIMIT_DEFAULT)
    async def get_items(request: Request):
        ...

    # Or use predefined limits:
    @router.post("/sync")
    @limiter.limit(RATE_LIMIT_SYNC)
    async def sync_data(request: Request):
        ...
"""

import logging

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.services.constants import (
    RATE_LIMIT_DEFAULT,
    RATE_LIMIT_WRITE,
    RATE_LIMIT_SYNC,
    RATE_LIMIT_UPLOAD,
    RATE_LIMIT_HEALTH,
    RATE_LIMIT_ANALYTICS,
    RATE_LIMIT_AUTH_LOGIN,
    RATE_LIMIT_AUTH_REGISTER,
    RATE_LIMIT_AUTH_PASSWORD_RESET,
    RATE_LIMIT_AUTH_EMAIL,
    RATE_LIMIT_AUTH_REFRESH,
)

logger = logging.getLogger(__name__)


def _get_client_ip(request: Request) -> str:
    """
    Extract client IP address from request.

    Checks X-Forwarded-For header first (for requests behind proxy/load balancer),
    then falls back to direct client IP.

    Args:
        request: Starlette/FastAPI request object

    Returns:
        Client IP address string
    """
    # Check for forwarded header (behind reverse proxy)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs; first is the original client
        return forwarded_for.split(",")[0].strip()

    # Check for real IP header (nginx)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # Fall back to direct client address
    return get_remote_address(request)


# =============================================================================
# LIMITER INSTANCE
# =============================================================================

# Create the limiter with IP-based key extraction
# In-memory storage is used by default (suitable for single-instance deployments)
# For multi-instance deployments, configure Redis storage:
#   limiter = Limiter(key_func=_get_client_ip, storage_uri="redis://localhost:6379")
limiter = Limiter(
    key_func=_get_client_ip,
    default_limits=[RATE_LIMIT_DEFAULT],
)


# =============================================================================
# RATE LIMIT EXCEEDED HANDLER
# =============================================================================

async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """
    Handle rate limit exceeded errors with consistent error format.

    Returns a 429 Too Many Requests response with:
    - Standard error format matching other API errors
    - Retry-After header indicating when to retry
    - Rate limit headers showing current limits

    Args:
        request: The request that exceeded the rate limit
        exc: The RateLimitExceeded exception

    Returns:
        JSONResponse with 429 status and error details
    """
    # Extract retry-after from the exception detail
    # slowapi provides this in the format "Rate limit exceeded: X per Y"
    retry_after = 60  # Default to 60 seconds

    # Try to parse the limit from exception
    limit_info = str(exc.detail) if exc.detail else "Rate limit exceeded"

    logger.warning(
        f"Rate limit exceeded for {_get_client_ip(request)}: {limit_info}"
    )

    return JSONResponse(
        status_code=429,
        content={
            "error": "RateLimitError",
            "message": f"Too many requests. {limit_info}",
            "details": {
                "retry_after": retry_after,
            },
        },
        headers={
            "Retry-After": str(retry_after),
        },
    )


# =============================================================================
# EXPORTS
# =============================================================================

# Re-export constants for convenient imports
__all__ = [
    "limiter",
    "rate_limit_exceeded_handler",
    "SlowAPIMiddleware",
    # Rate limit constants
    "RATE_LIMIT_DEFAULT",
    "RATE_LIMIT_WRITE",
    "RATE_LIMIT_SYNC",
    "RATE_LIMIT_UPLOAD",
    "RATE_LIMIT_HEALTH",
    "RATE_LIMIT_ANALYTICS",
    # Auth-specific rate limits
    "RATE_LIMIT_AUTH_LOGIN",
    "RATE_LIMIT_AUTH_REGISTER",
    "RATE_LIMIT_AUTH_PASSWORD_RESET",
    "RATE_LIMIT_AUTH_EMAIL",
    "RATE_LIMIT_AUTH_REFRESH",
]
