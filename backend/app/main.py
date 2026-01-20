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

# WORKING VERSION? YES

import logging

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
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
)
from app.routers.portfolio_settings import router as portfolio_settings_router
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
# MIDDLEWARE (order matters: last added = first executed)
# =============================================================================

from app.middleware import CorrelationIdMiddleware

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

app.include_router(assets_router)  # /assets/*
app.include_router(portfolios_router)  # /portfolios/*
app.include_router(transactions_router)  # /transactions/*
app.include_router(upload_router)  # /upload/*
app.include_router(sync_router)  # /portfolios/{id}/sync/* (Phase 3)
app.include_router(valuation_router)  # /portfolios/{id}/valuation/* (Phase 4)
app.include_router(analytics_router)  # /portfolios/{id}/analytics/* (Phase 5)
app.include_router(portfolio_settings_router)  # /portfolios/{id}/settings


# =============================================================================
# GLOBAL ENDPOINTS
# =============================================================================

@app.get("/", tags=["Health"])
def root():
    """
    API root - returns basic application info.
    """
    return {
        "message": f"Welcome to {settings.app_name}!",
        "docs": "/docs",
        "redoc": "/redoc",
    }


@app.get("/health", tags=["Health"])
def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint.

    Verifies:
    - Application is running
    - Database connection is working
    """
    try:
        # Execute simple query to verify database connection
        db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "unhealthy"

    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "database": db_status,
    }
