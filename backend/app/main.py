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
    """Handle ticker not found by provider (404)."""
    logger.warning(f"Ticker not found: {exc.ticker} on {exc.exchange} via {exc.provider}")
    return JSONResponse(
        status_code=404,
        content=ErrorDetail(
            error="TickerNotFoundError",
            message=str(exc),
            details={
                "ticker": exc.ticker,
                "exchange": exc.exchange,
                "provider": exc.provider,
            },
        ).model_dump(),
    )


@app.exception_handler(ProviderUnavailableError)
async def provider_unavailable_handler(request: Request, exc: ProviderUnavailableError) -> JSONResponse:
    """Handle provider unavailable errors (503)."""
    logger.error(f"Provider unavailable: {exc.provider} - {exc.message}")
    return JSONResponse(
        status_code=503,
        content=ErrorDetail(
            error="ProviderUnavailableError",
            message=str(exc),
            details={"provider": exc.provider},
        ).model_dump(),
        headers={"Retry-After": "60"},  # Suggest retry after 1 minute
    )


@app.exception_handler(RateLimitError)
async def rate_limit_handler(request: Request, exc: RateLimitError) -> JSONResponse:
    """Handle rate limit errors (429)."""
    logger.warning(f"Rate limit exceeded: {exc.provider}")
    retry_after = exc.retry_after or 60
    return JSONResponse(
        status_code=429,
        content=ErrorDetail(
            error="RateLimitError",
            message=str(exc),
            details={"provider": exc.provider, "retry_after": retry_after},
        ).model_dump(),
        headers={"Retry-After": str(retry_after)},
    )


@app.exception_handler(MarketDataError)
async def market_data_error_handler(request: Request, exc: MarketDataError) -> JSONResponse:
    """Handle generic market data errors (502)."""
    logger.error(f"Market data error: {exc.message}")
    return JSONResponse(
        status_code=502,
        content=ErrorDetail(
            error="MarketDataError",
            message=str(exc),
            details={
                "provider": exc.provider,
                "ticker": exc.ticker,
                "exchange": exc.exchange,
            },
        ).model_dump(),
    )


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    """
    Handle any unhandled service errors (500).

    This is the catch-all for service layer exceptions that don't have
    a specific handler. These indicate unexpected errors that should
    be investigated.
    """
    logger.error(f"Unhandled service error: {exc.message}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorDetail(
            error="ServiceError",
            message="An unexpected error occurred. Please try again later.",
            details=None,  # Don't expose internal details in production
        ).model_dump(),
    )


# =============================================================================
# ROUTER REGISTRATION
# =============================================================================

app.include_router(assets_router)
app.include_router(portfolios_router)
app.include_router(transactions_router)
app.include_router(upload_router)


# =============================================================================
# GLOBAL ENDPOINTS
# =============================================================================

@app.get("/", tags=["Health"])
def read_root() -> dict[str, str]:
    """Root endpoint returning API status."""
    return {
        "message": f"Welcome to {settings.app_name}",
        "status": "operational",
        "docs": "/docs",
    }


@app.get("/health/db", tags=["Health"])
def check_db(db: Session = Depends(get_db)) -> dict[str, str]:
    """Health check endpoint to verify database connectivity."""
    db.execute(text("SELECT 1"))
    return {"status": "healthy", "database": "connected"}
