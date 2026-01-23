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
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Portfolio, SyncStatus, User
from app.services.market_data import MarketDataSyncService, SyncResult
from app.services.analytics.service import AnalyticsService
from app.dependencies import get_sync_service, get_analytics_service, get_portfolio_with_owner_check
from app.middleware.rate_limit import limiter, RATE_LIMIT_SYNC, RATE_LIMIT_DEFAULT

# Full re-sync can only be done once per hour
FULL_RESYNC_COOLDOWN_HOURS = 1

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
    last_full_sync: str | None = None
    is_stale: bool = False
    staleness_reason: str | None = None

    model_config = {"from_attributes": True}


class FullResyncResponse(BaseModel):
    """Response from full re-sync operation."""
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
    next_full_resync_available: str | None = Field(
        default=None,
        description="ISO timestamp when next full re-sync will be available"
    )

    model_config = {"from_attributes": True}


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post(
    "/{portfolio_id}/sync",
    response_model=SyncResponse,
    summary="Sync portfolio market data",
    response_description="Sync result with statistics"
)
@limiter.limit(RATE_LIMIT_SYNC)
def sync_portfolio(
        request: Request,  # Required for rate limiting
        portfolio: Portfolio = Depends(get_portfolio_with_owner_check),
        sync_request: SyncRequest = SyncRequest(),
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

    Raises **403** if you don't own the portfolio.
    """
    portfolio_id = portfolio.id

    logger.info(f"Starting sync for portfolio {portfolio_id} (force={sync_request.force_refresh})")

    try:
        result: SyncResult = service.sync_portfolio(
            db=db,
            portfolio_id=portfolio_id,
            force=sync_request.force_refresh,
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
@limiter.limit(RATE_LIMIT_DEFAULT)
def get_sync_status(
        request: Request,  # Required for rate limiting
        portfolio: Portfolio = Depends(get_portfolio_with_owner_check),
        db: Session = Depends(get_db),
        service: MarketDataSyncService = Depends(get_sync_service),
) -> SyncStatusResponse:
    """
    Get the current sync status for a portfolio.

    Returns:
    - **status**: Current sync state (NEVER, COMPLETED, etc.)
    - **is_stale**: Whether data needs to be refreshed
    - **staleness_reason**: Why data is considered stale (if applicable)

    Raises **403** if you don't own the portfolio.
    """
    portfolio_id = portfolio.id

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
            last_full_sync=sync_status.last_full_sync.isoformat() if sync_status.last_full_sync else None,
            is_stale=is_stale,
            staleness_reason=staleness_reason,
        )
    else:
        return SyncStatusResponse(
            portfolio_id=portfolio_id,
            status="NEVER",
            last_sync_started=None,
            last_sync_completed=None,
            last_full_sync=None,
            is_stale=True,
            staleness_reason="Portfolio has never been synced",
        )


@router.post(
    "/{portfolio_id}/sync/full",
    response_model=FullResyncResponse,
    summary="Full re-sync portfolio market data",
    response_description="Full re-sync result with statistics"
)
@limiter.limit(RATE_LIMIT_SYNC)
def full_resync_portfolio(
        request: Request,  # Required for rate limiting
        portfolio: Portfolio = Depends(get_portfolio_with_owner_check),
        db: Session = Depends(get_db),
        service: MarketDataSyncService = Depends(get_sync_service),
        analytics_service: AnalyticsService = Depends(get_analytics_service),
) -> FullResyncResponse:
    """
    Perform a full re-sync of all market data for a portfolio.

    This operation:
    - Clears "no data" markers for dates that previously had no data
    - Re-fetches all historical prices from Yahoo Finance
    - Re-fetches all FX rates

    **Rate Limited:** Can only be performed once per hour per portfolio.

    Use this when:
    - You suspect data provider has corrected historical data
    - Initial sync had errors and you want to retry
    - You need to verify data integrity

    For regular daily updates, use the standard `/sync` endpoint instead.

    Raises **403** if you don't own the portfolio.
    Raises **429** if a full re-sync was performed within the last hour.
    """
    portfolio_id = portfolio.id

    # Check rate limit: only allow full re-sync once per hour
    sync_status = db.scalar(
        select(SyncStatus).where(SyncStatus.portfolio_id == portfolio_id)
    )

    now = datetime.now(timezone.utc)
    cooldown = timedelta(hours=FULL_RESYNC_COOLDOWN_HOURS)

    if sync_status and sync_status.last_full_sync:
        time_since_last = now - sync_status.last_full_sync
        if time_since_last < cooldown:
            next_available = sync_status.last_full_sync + cooldown
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Full re-sync can only be performed once per hour. "
                       f"Next available: {next_available.isoformat()}"
            )

    logger.info(f"Starting full re-sync for portfolio {portfolio_id}")

    try:
        result: SyncResult = service.sync_portfolio(
            db=db,
            portfolio_id=portfolio_id,
            force=True,  # Force re-fetch all data
        )

        # Update last_full_sync timestamp
        if sync_status:
            sync_status.last_full_sync = now
            db.commit()

        # Invalidate analytics cache after sync
        analytics_service.invalidate_cache(portfolio_id)

        next_available = now + cooldown

        return FullResyncResponse(
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
            next_full_resync_available=next_available.isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Full re-sync failed for portfolio {portfolio_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Full re-sync failed: {str(e)}"
        )
