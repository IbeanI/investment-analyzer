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

from fastapi import FastAPI, Depends, Request
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
from app.schemas.errors import ErrorDetail
from app.services.exceptions import (
    ServiceError,
    AssetNotFoundError,
    AssetDeactivatedError,
    TickerNotFoundError,
    ProviderUnavailableError,
    RateLimitError,
    MarketDataError,
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
