# backend/app/main.py
"""
FastAPI application entry point.

This file:
- Configures application-wide logging
- Creates the FastAPI application
- Registers all routers
- Defines global endpoints (health checks)
"""

from fastapi import FastAPI, Depends
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
from app.utils import setup_logging

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
