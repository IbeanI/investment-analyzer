# backend/app/routers/sync.py
"""
Market Data Sync endpoints.

Provides endpoints for synchronizing market data (prices, FX rates)
for portfolios. This is Phase 3 functionality.

Key features:
- Sync portfolio market data from Yahoo Finance
- Check sync status
- Force refresh capability
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Portfolio, SyncStatus
from app.services.market_data import MarketDataSyncService, SyncResult
from app.services.analytics.service import AnalyticsService
from app.dependencies import get_sync_service, get_analytics_service

logger = logging.getLogger(__name__)

# =============================================================================
# ROUTER SETUP
# =============================================================================

router = APIRouter(
    prefix="/portfolios",
    tags=["Market Data Sync"],
)


# =============================================================================
# SCHEMAS
# =============================================================================

class SyncRequest(BaseModel):
    """Request body for sync operation."""
    force_refresh: bool = Field(
        default=False,
        description="If true, re-fetch all data even if recent data exists"
    )


class SyncResponse(BaseModel):
    """Response from sync operation."""
    success: bool
    portfolio_id: int
    status: str = Field(description="completed, partial, or failed")
    assets_synced: int = 0
    assets_failed: int = 0
    prices_fetched: int = 0
    fx_pairs_synced: int = 0
    fx_rates_fetched: int = 0
    warnings: list[str] = []
    error: str | None = None

    model_config = {"from_attributes": True}


class SyncStatusResponse(BaseModel):
    """Response for sync status check."""
    portfolio_id: int
    status: str = Field(description="NEVER, IN_PROGRESS, COMPLETED, PARTIAL, FAILED")
    last_sync_started: str | None = None
    last_sync_completed: str | None = None
    is_stale: bool = False
    staleness_reason: str | None = None

    model_config = {"from_attributes": True}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_portfolio_or_404(db: Session, portfolio_id: int) -> Portfolio:
    """Get portfolio or raise 404."""
    portfolio = db.get(Portfolio, portfolio_id)
    if not portfolio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio {portfolio_id} not found"
        )
    return portfolio


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post(
    "/{portfolio_id}/sync",
    response_model=SyncResponse,
    summary="Sync portfolio market data",
    response_description="Sync result with statistics"
)
def sync_portfolio(
        portfolio_id: int,
        request: SyncRequest = SyncRequest(),
        db: Session = Depends(get_db),
        service: MarketDataSyncService = Depends(get_sync_service),
        analytics_service: AnalyticsService = Depends(get_analytics_service),
) -> SyncResponse:
    """
    Synchronize market data for a portfolio.

    This endpoint fetches:
    - Historical prices for all assets in the portfolio
    - FX rates for currency conversion

    Data is fetched from Yahoo Finance and stored in the database
    for fast valuation lookups.

    **Note:** This may take 10-30 seconds depending on the number of assets.

    Set `force_refresh: true` to re-fetch all data even if recent data exists.
    """
    # Verify portfolio exists
    get_portfolio_or_404(db, portfolio_id)

    logger.info(f"Starting sync for portfolio {portfolio_id} (force={request.force_refresh})")

    try:
        result: SyncResult = service.sync_portfolio(
            db=db,
            portfolio_id=portfolio_id,
            force=request.force_refresh,
        )

        # Invalidate analytics cache after sync (prices/FX rates changed)
        # Do this regardless of partial success since some data may have changed
        analytics_service.invalidate_cache(portfolio_id)

        return SyncResponse(
            success=result.status in ("completed", "partial"),
            portfolio_id=result.portfolio_id,
            status=result.status,
            assets_synced=result.assets_synced,
            assets_failed=result.assets_failed,
            prices_fetched=result.prices_fetched,
            fx_pairs_synced=result.fx_pairs_synced,
            fx_rates_fetched=result.fx_rates_fetched,
            warnings=result.warnings,
            error=result.error,
        )

    except Exception as e:
        logger.error(f"Sync failed for portfolio {portfolio_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {str(e)}"
        )


@router.get(
    "/{portfolio_id}/sync/status",
    response_model=SyncStatusResponse,
    summary="Get sync status",
    response_description="Current sync status for portfolio"
)
def get_sync_status(
        portfolio_id: int,
        db: Session = Depends(get_db),
        service: MarketDataSyncService = Depends(get_sync_service),
) -> SyncStatusResponse:
    """
    Get the current sync status for a portfolio.

    Returns:
    - **status**: Current sync state (NEVER, COMPLETED, etc.)
    - **is_stale**: Whether data needs to be refreshed
    - **staleness_reason**: Why data is considered stale (if applicable)
    """
    # Verify portfolio exists
    get_portfolio_or_404(db, portfolio_id)

    # Get sync status from database
    sync_status = db.scalar(
        select(SyncStatus).where(SyncStatus.portfolio_id == portfolio_id)
    )

    # Check staleness
    is_stale, staleness_reason = service.is_data_stale(db, portfolio_id)

    if sync_status:
        return SyncStatusResponse(
            portfolio_id=portfolio_id,
            status=sync_status.status.value,
            last_sync_started=sync_status.last_sync_started.isoformat() if sync_status.last_sync_started else None,
            last_sync_completed=sync_status.last_sync_completed.isoformat() if sync_status.last_sync_completed else None,
            is_stale=is_stale,
            staleness_reason=staleness_reason,
        )
    else:
        return SyncStatusResponse(
            portfolio_id=portfolio_id,
            status="NEVER",
            last_sync_started=None,
            last_sync_completed=None,
            is_stale=True,
            staleness_reason="Portfolio has never been synced",
        )
