# backend/app/main.py
"""
FastAPI application entry point.

This file:
- Configures application-wide logging
- Creates the FastAPI application
- Registers global exception handlers
- Registers all routers
- Defines global endpoints (health checks)
"""

import logging

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.routers import (
    assets_router,
    portfolios_router,
    transactions_router,
    upload_router,
    sync_router,
    valuation_router,
    analytics_router,
    users_router,
)
from app.routers.portfolio_settings import router as portfolio_settings_router
from app.routers.auth import router as auth_router
from app.schemas.errors import ErrorDetail, ValidationErrorDetail
from app.services.exceptions import (
    ServiceError,
    AssetNotFoundError,
    AssetDeactivatedError,
    TickerNotFoundError,
    ProviderUnavailableError,
    RateLimitError,
    MarketDataError,
    # Centralized exceptions
    PortfolioNotFoundError,
    ValidationError,
    InvalidIntervalError,
    FXConversionError,
    BenchmarkNotSyncedError,
    CircuitBreakerOpen,
    # Authentication exceptions
    AuthenticationError,
    InvalidCredentialsError,
    UserExistsError,
    EmailNotVerifiedError,
    TokenExpiredError,
    TokenRevokedError,
    OAuthError,
    UserNotFoundError,
    UserInactiveError,
    # Authorization exceptions
    AuthorizationError,
    PermissionDeniedError,
)
from app.utils import setup_logging

logger = logging.getLogger(__name__)

# =============================================================================
# LOGGING SETUP (must be before app creation)
# =============================================================================

setup_logging()

# =============================================================================
# APPLICATION SETUP
# =============================================================================

app = FastAPI(
    title=settings.app_name,
    description="Institution-grade investment portfolio analysis API",
    version="0.1.0",
)


# =============================================================================
# CORS MIDDLEWARE
# =============================================================================
# Must be added before other middleware
# Configure allowed origins for frontend access
# Origins are configured via CORS_ORIGINS environment variable

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)


# =============================================================================
# MIDDLEWARE (order matters: last added = first executed)
# =============================================================================

from slowapi.errors import RateLimitExceeded
from app.middleware import (
    CorrelationIdMiddleware,
    limiter,
    rate_limit_exceeded_handler,
    SlowAPIMiddleware,
    RATE_LIMIT_HEALTH,
)

# Attach limiter to app state (required by slowapi)
app.state.limiter = limiter

# Add rate limiting middleware
# Must be added before other middleware that might modify the response
app.add_middleware(SlowAPIMiddleware)

# Add correlation ID tracking for request tracing
# This extracts/generates correlation IDs and adds them to response headers
app.add_middleware(CorrelationIdMiddleware)


# =============================================================================
# GLOBAL EXCEPTION HANDLERS
# =============================================================================
# These handlers catch service-layer exceptions and convert them to
# consistent HTTP responses. Routers can still catch exceptions locally
# if they need to add endpoint-specific context.
# =============================================================================

# Rate limit exceeded handler (from slowapi)
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


@app.exception_handler(AssetNotFoundError)
async def asset_not_found_handler(request: Request, exc: AssetNotFoundError) -> JSONResponse:
    """Handle asset not found errors (404)."""
    logger.warning(f"Asset not found: {exc.ticker} on {exc.exchange}")
    return JSONResponse(
        status_code=404,
        content=ErrorDetail(
            error="AssetNotFoundError",
            message=str(exc),
            details={"ticker": exc.ticker, "exchange": exc.exchange},
        ).model_dump(),
    )


@app.exception_handler(AssetDeactivatedError)
async def asset_deactivated_handler(request: Request, exc: AssetDeactivatedError) -> JSONResponse:
    """Handle deactivated asset errors (400)."""
    logger.warning(f"Asset deactivated: {exc.ticker} on {exc.exchange}")
    return JSONResponse(
        status_code=400,
        content=ErrorDetail(
            error="AssetDeactivatedError",
            message=str(exc),
            details={"ticker": exc.ticker, "exchange": exc.exchange},
        ).model_dump(),
    )


@app.exception_handler(TickerNotFoundError)
async def ticker_not_found_handler(request: Request, exc: TickerNotFoundError) -> JSONResponse:
    """Handle ticker not found on market data provider (404)."""
    logger.warning(f"Ticker not found on provider: {exc.ticker}")
    return JSONResponse(
        status_code=404,
        content=ErrorDetail(
            error="TickerNotFoundError",
            message=str(exc),
            details={"ticker": exc.ticker},
        ).model_dump(),
    )


@app.exception_handler(ProviderUnavailableError)
async def provider_unavailable_handler(request: Request, exc: ProviderUnavailableError) -> JSONResponse:
    """Handle market data provider unavailable (503)."""
    logger.error(f"Provider unavailable: {exc}")
    return JSONResponse(
        status_code=503,
        content=ErrorDetail(
            error="ProviderUnavailableError",
            message=str(exc),
            details=None,
        ).model_dump(),
    )


@app.exception_handler(RateLimitError)
async def rate_limit_handler(request: Request, exc: RateLimitError) -> JSONResponse:
    """Handle rate limit exceeded (429)."""
    logger.warning(f"Rate limit exceeded: {exc}")
    return JSONResponse(
        status_code=429,
        content=ErrorDetail(
            error="RateLimitError",
            message=str(exc),
            details={"retry_after": exc.retry_after} if exc.retry_after else None,
        ).model_dump(),
    )


@app.exception_handler(CircuitBreakerOpen)
async def circuit_breaker_handler(request: Request, exc: CircuitBreakerOpen) -> JSONResponse:
    """Handle circuit breaker open (503 with Retry-After)."""
    logger.warning(f"Circuit breaker open: {exc.breaker_name}")
    retry_after = int(exc.time_remaining) + 1  # Round up
    return JSONResponse(
        status_code=503,
        content=ErrorDetail(
            error="CircuitBreakerOpen",
            message=f"Service temporarily unavailable. The {exc.breaker_name} circuit breaker is open.",
            details={
                "breaker_name": exc.breaker_name,
                "retry_after": retry_after,
            },
        ).model_dump(),
        headers={"Retry-After": str(retry_after)},
    )


@app.exception_handler(MarketDataError)
async def market_data_error_handler(request: Request, exc: MarketDataError) -> JSONResponse:
    """Handle generic market data errors (500)."""
    logger.error(f"Market data error: {exc}")
    return JSONResponse(
        status_code=500,
        content=ErrorDetail(
            error="MarketDataError",
            message=str(exc),
            details=None,
        ).model_dump(),
    )


@app.exception_handler(PortfolioNotFoundError)
async def portfolio_not_found_handler(
    request: Request, exc: PortfolioNotFoundError
) -> JSONResponse:
    """Handle portfolio not found errors (404)."""
    logger.warning(f"Portfolio not found: {exc.portfolio_id}")
    return JSONResponse(
        status_code=404,
        content=ErrorDetail(
            error="PortfolioNotFoundError",
            message=str(exc),
            details={"portfolio_id": exc.portfolio_id},
        ).model_dump(),
    )


@app.exception_handler(InvalidIntervalError)
async def invalid_interval_handler(
    request: Request, exc: InvalidIntervalError
) -> JSONResponse:
    """Handle invalid interval errors (400)."""
    logger.warning(f"Invalid interval: {exc.interval}")
    return JSONResponse(
        status_code=400,
        content=ErrorDetail(
            error="InvalidIntervalError",
            message=str(exc),
            details={"interval": exc.interval, "valid_options": ["daily", "weekly", "monthly"]},
        ).model_dump(),
    )


@app.exception_handler(ValidationError)
async def validation_error_handler(
    request: Request, exc: ValidationError
) -> JSONResponse:
    """Handle validation errors (400)."""
    logger.warning(f"Validation error: {exc}")
    return JSONResponse(
        status_code=400,
        content=ErrorDetail(
            error="ValidationError",
            message=str(exc),
            details={"field": exc.field} if exc.field else None,
        ).model_dump(),
    )


@app.exception_handler(FXConversionError)
async def fx_conversion_error_handler(
    request: Request, exc: FXConversionError
) -> JSONResponse:
    """Handle FX conversion errors (400)."""
    logger.warning(f"FX conversion error: {exc}")
    return JSONResponse(
        status_code=400,
        content=ErrorDetail(
            error="FXConversionError",
            message=str(exc),
            details={
                "base_currency": exc.base_currency,
                "quote_currency": exc.quote_currency,
            } if exc.base_currency else None,
        ).model_dump(),
    )


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    """Handle generic service errors (500)."""
    logger.error(f"Service error: {exc}")
    return JSONResponse(
        status_code=500,
        content=ErrorDetail(
            error="ServiceError",
            message=str(exc),
            details=None,
        ).model_dump(),
    )


@app.exception_handler(BenchmarkNotSyncedError)
async def benchmark_not_synced_handler(
    request: Request, exc: BenchmarkNotSyncedError
) -> JSONResponse:
    """Handle benchmark not synced errors (400)."""
    logger.warning(f"Benchmark not synced: {exc.symbol}")
    return JSONResponse(
        status_code=400,
        content=ErrorDetail(
            error="BenchmarkNotSyncedError",
            message=exc.message,
            details={"benchmark_symbol": exc.symbol},
        ).model_dump(),
    )


# =============================================================================
# AUTHENTICATION EXCEPTION HANDLERS
# =============================================================================


@app.exception_handler(InvalidCredentialsError)
async def invalid_credentials_handler(
    request: Request, exc: InvalidCredentialsError
) -> JSONResponse:
    """Handle invalid credentials errors (401)."""
    logger.warning(f"Invalid credentials attempt")
    return JSONResponse(
        status_code=401,
        content=ErrorDetail(
            error="InvalidCredentialsError",
            message=str(exc),
            details=None,
        ).model_dump(),
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(UserExistsError)
async def user_exists_handler(
    request: Request, exc: UserExistsError
) -> JSONResponse:
    """Handle user already exists errors (409)."""
    logger.warning(f"Registration attempt with existing email: {exc.email}")
    return JSONResponse(
        status_code=409,
        content=ErrorDetail(
            error="UserExistsError",
            message=str(exc),
            details={"email": exc.email},
        ).model_dump(),
    )


@app.exception_handler(EmailNotVerifiedError)
async def email_not_verified_handler(
    request: Request, exc: EmailNotVerifiedError
) -> JSONResponse:
    """Handle email not verified errors (403)."""
    logger.warning(f"Login attempt with unverified email: {exc.email}")
    return JSONResponse(
        status_code=403,
        content=ErrorDetail(
            error="EmailNotVerifiedError",
            message=str(exc),
            details={"email": exc.email},
        ).model_dump(),
    )


@app.exception_handler(TokenExpiredError)
async def token_expired_handler(
    request: Request, exc: TokenExpiredError
) -> JSONResponse:
    """Handle token expired errors (401)."""
    logger.warning(f"Expired token used: {exc.token_type}")
    return JSONResponse(
        status_code=401,
        content=ErrorDetail(
            error="TokenExpiredError",
            message=str(exc),
            details={"token_type": exc.token_type},
        ).model_dump(),
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(TokenRevokedError)
async def token_revoked_handler(
    request: Request, exc: TokenRevokedError
) -> JSONResponse:
    """Handle token revoked errors (401)."""
    logger.warning("Revoked token used (possible replay attack)")
    return JSONResponse(
        status_code=401,
        content=ErrorDetail(
            error="TokenRevokedError",
            message=str(exc),
            details=None,
        ).model_dump(),
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(OAuthError)
async def oauth_error_handler(
    request: Request, exc: OAuthError
) -> JSONResponse:
    """Handle OAuth errors (400)."""
    logger.error(f"OAuth error with {exc.provider}: {exc.reason}")
    return JSONResponse(
        status_code=400,
        content=ErrorDetail(
            error="OAuthError",
            message=str(exc),
            details={"provider": exc.provider, "reason": exc.reason},
        ).model_dump(),
    )


@app.exception_handler(UserInactiveError)
async def user_inactive_handler(
    request: Request, exc: UserInactiveError
) -> JSONResponse:
    """Handle inactive user errors (403)."""
    logger.warning("Login attempt by inactive user")
    return JSONResponse(
        status_code=403,
        content=ErrorDetail(
            error="UserInactiveError",
            message=str(exc),
            details=None,
        ).model_dump(),
    )


@app.exception_handler(PermissionDeniedError)
async def permission_denied_handler(
    request: Request, exc: PermissionDeniedError
) -> JSONResponse:
    """Handle permission denied errors (403)."""
    logger.warning(f"Permission denied: {exc.resource_type} {exc.resource_id}")
    return JSONResponse(
        status_code=403,
        content=ErrorDetail(
            error="PermissionDeniedError",
            message=str(exc),
            details={
                "resource_type": exc.resource_type,
                "resource_id": exc.resource_id,
            },
        ).model_dump(),
    )


@app.exception_handler(AuthenticationError)
async def authentication_error_handler(
    request: Request, exc: AuthenticationError
) -> JSONResponse:
    """Handle generic authentication errors (401)."""
    logger.warning(f"Authentication error: {exc}")
    return JSONResponse(
        status_code=401,
        content=ErrorDetail(
            error="AuthenticationError",
            message=str(exc),
            details=None,
        ).model_dump(),
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Handle all HTTPExceptions with consistent error format.

    Converts FastAPI's default {"detail": "..."} format to our standard
    ErrorDetail format for API consistency.
    """
    # Determine error type from status code
    error_types = {
        400: "BadRequestError",
        401: "UnauthorizedError",
        403: "ForbiddenError",
        404: "NotFoundError",
        405: "MethodNotAllowedError",
        409: "ConflictError",
        422: "ValidationError",
        429: "RateLimitError",
        500: "InternalServerError",
        503: "ServiceUnavailableError",
    }
    error_type = error_types.get(exc.status_code, "HTTPError")

    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorDetail(
            error=error_type,
            message=str(exc.detail) if exc.detail else "An error occurred",
            details=None,
        ).model_dump(),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Handle Pydantic validation errors with consistent format.

    Converts the default 422 validation error to our ValidationErrorDetail format.
    """
    # Extract validation errors in a cleaner format
    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        })

    return JSONResponse(
        status_code=422,
        content=ValidationErrorDetail(
            error="ValidationError",
            message="Request validation failed",
            details=errors,
        ).model_dump(),
    )


# =============================================================================
# ROUTER REGISTRATION
# =============================================================================

app.include_router(auth_router)  # /auth/*
app.include_router(assets_router)  # /assets/*
app.include_router(portfolios_router)  # /portfolios/*
app.include_router(transactions_router)  # /transactions/*
app.include_router(upload_router)  # /upload/*
app.include_router(sync_router)  # /portfolios/{id}/sync/* (Phase 3)
app.include_router(valuation_router)  # /portfolios/{id}/valuation/* (Phase 4)
app.include_router(analytics_router)  # /portfolios/{id}/analytics/* (Phase 5)
app.include_router(portfolio_settings_router)  # /portfolios/{id}/settings
app.include_router(users_router)  # /users/me/*


# =============================================================================
# GLOBAL ENDPOINTS
# =============================================================================

@app.get("/", tags=["Health"])
@limiter.limit(RATE_LIMIT_HEALTH)
def root(request: Request):
    """
    API root - returns basic application info.
    """
    return {
        "message": f"Welcome to {settings.app_name}!",
        "docs": "/docs",
        "redoc": "/redoc",
    }


@app.get("/health", tags=["Health"])
@limiter.limit(RATE_LIMIT_HEALTH)
def health_check(request: Request, db: Session = Depends(get_db)):
    """
    Comprehensive health check endpoint.

    Returns detailed health status of all dependencies.
    Returns HTTP 503 if critical dependencies (database) are unhealthy.
    Returns HTTP 200 with degraded status if non-critical dependencies are unhealthy.

    **Response Status Codes:**
    - 200: All systems healthy, or non-critical systems degraded
    - 503: Critical systems (database) unhealthy - do not route traffic here

    **Usage by Load Balancers:**
    Configure your load balancer to use this endpoint for health checks.
    Instances returning 503 should be removed from the pool.
    """
    from app.dependencies import get_market_data_provider

    checks = {}
    critical_healthy = True
    overall_status = "healthy"

    # Check 1: Database (CRITICAL)
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {
            "status": "healthy",
            "critical": True,
        }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        checks["database"] = {
            "status": "unhealthy",
            "critical": True,
            "error": str(e),
        }
        critical_healthy = False
        overall_status = "unhealthy"

    # Check 2: Yahoo Finance API (circuit breaker state) - NON-CRITICAL
    try:
        provider = get_market_data_provider()
        circuit_breaker = provider._get_circuit_breaker()
        cb_state = circuit_breaker.state.value
        cb_stats = circuit_breaker.stats

        if circuit_breaker.is_open:
            checks["yahoo_finance"] = {
                "status": "unhealthy",
                "critical": False,
                "circuit_breaker_state": cb_state,
                "failed_calls": cb_stats.failed_calls,
                "rejected_calls": cb_stats.rejected_calls,
            }
            if overall_status == "healthy":
                overall_status = "degraded"
        else:
            checks["yahoo_finance"] = {
                "status": "healthy",
                "critical": False,
                "circuit_breaker_state": cb_state,
                "total_calls": cb_stats.total_calls,
                "successful_calls": cb_stats.successful_calls,
            }
    except Exception as e:
        logger.warning(f"Yahoo Finance health check failed: {e}")
        checks["yahoo_finance"] = {
            "status": "unknown",
            "critical": False,
            "error": str(e),
        }

    response_data = {
        "status": overall_status,
        "checks": checks,
    }

    # Return 503 if critical dependencies are unhealthy
    if not critical_healthy:
        return JSONResponse(
            status_code=503,
            content=response_data,
        )

    return response_data


@app.get("/health/live", tags=["Health"])
@limiter.limit(RATE_LIMIT_HEALTH)
def liveness_check(request: Request):
    """
    Kubernetes liveness probe endpoint.

    Returns HTTP 200 if the application is running.
    This check should ALWAYS succeed if the process is alive.

    **Usage:**
    Configure as Kubernetes livenessProbe. If this fails,
    Kubernetes will restart the container.

    **Note:** This does NOT check dependencies - use /health/ready for that.
    """
    return {"status": "alive"}


@app.get("/health/ready", tags=["Health"])
@limiter.limit(RATE_LIMIT_HEALTH)
def readiness_check(request: Request, db: Session = Depends(get_db)):
    """
    Kubernetes readiness probe endpoint.

    Returns HTTP 200 if the application is ready to serve traffic.
    Returns HTTP 503 if critical dependencies are unavailable.

    **Usage:**
    Configure as Kubernetes readinessProbe. Pods returning 503
    will be removed from service endpoints until they become ready.

    **Checks:**
    - Database connectivity (critical - causes 503 if down)
    """
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "error": "Database unavailable",
            },
        )
