# backend/app/schemas/market_data.py
"""
Pydantic schemas for Market Data synchronization.

These schemas handle:
- Sync requests and responses
- Sync status queries
- Coverage reporting
"""

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# SYNC REQUEST SCHEMAS
# =============================================================================

class MarketDataSyncRequest(BaseModel):
    """Schema for triggering a market data sync."""

    portfolio_id: int = Field(..., gt=0, description="Portfolio to sync data for")
    force_full: bool = Field(
        default=False,
        description="If True, re-fetch all data regardless of existing coverage"
    )


class MarketDataRefreshRequest(BaseModel):
    """Schema for refreshing recent market data."""

    portfolio_id: int = Field(..., gt=0, description="Portfolio to refresh data for")


# =============================================================================
# COVERAGE SCHEMAS
# =============================================================================

class AssetCoverage(BaseModel):
    """Coverage information for a single asset."""

    asset_id: int
    ticker: str
    exchange: str
    from_date: dt.date | None = Field(..., description="Earliest date with data")
    to_date: dt.date | None = Field(..., description="Latest date with data")
    total_days: int = Field(..., description="Number of days with data")
    gaps: list[str] = Field(
        default_factory=list,
        description="Date ranges without data (e.g., ['2023-01-01 to 2023-01-15'])"
    )
    has_synthetic: bool = Field(
        default=False,
        description="Whether any data is synthetic (from proxy)"
    )


class FXCoverage(BaseModel):
    """Coverage information for a currency pair."""

    base_currency: str
    quote_currency: str
    from_date: dt.date | None
    to_date: dt.date | None
    total_days: int


class CoverageSummary(BaseModel):
    """Complete coverage summary for a portfolio."""

    assets: list[AssetCoverage]
    fx_pairs: list[FXCoverage]


# =============================================================================
# SYNC STATUS SCHEMAS
# =============================================================================

class SyncStatusResponse(BaseModel):
    """Schema for sync status response."""

    portfolio_id: int
    status: str = Field(
        ...,
        description="Sync status: never, in_progress, completed, failed"
    )
    last_sync_started: dt.datetime | None = Field(
        ...,
        description="When the last sync started"
    )
    last_sync_completed: dt.datetime | None = Field(
        ...,
        description="When the last sync completed"
    )
    last_error: str | None = Field(
        default=None,
        description="Error message if last sync failed"
    )
    coverage: CoverageSummary | None = Field(
        default=None,
        description="Data coverage summary"
    )

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# SYNC RESULT SCHEMAS
# =============================================================================

class SyncWarning(BaseModel):
    """A warning generated during sync."""

    asset_id: int | None = None
    ticker: str | None = None
    message: str


class SyncResult(BaseModel):
    """Result of a sync operation."""

    status: str = Field(
        ...,
        description="Result status: completed, in_progress, failed"
    )
    portfolio_id: int
    sync_started: dt.datetime
    sync_completed: dt.datetime | None = None

    # Stats
    date_range: dict = Field(
        ...,
        description="Date range synced: {from: dt.date, to: dt.date}"
    )
    assets_synced: int = Field(..., description="Number of assets processed")
    prices_fetched: int = Field(..., description="Number of price records fetched")
    fx_pairs_synced: list[str] = Field(
        default_factory=list,
        description="FX pairs synced (e.g., ['USD/EUR', 'GBP/EUR'])"
    )
    fx_rates_fetched: int = Field(..., description="Number of FX rate records fetched")

    # Warnings (non-fatal issues)
    warnings: list[SyncWarning] = Field(
        default_factory=list,
        description="Non-fatal issues encountered during sync"
    )

    # Error (if failed)
    error: str | None = Field(
        default=None,
        description="Error message if sync failed"
    )


# =============================================================================
# MARKET DATA RESPONSE SCHEMAS
# =============================================================================

class MarketDataPointResponse(BaseModel):
    """Schema for a single market data point."""

    id: int
    asset_id: int
    date: dt.date  # Daily data - no time component
    close_price: Decimal
    adjusted_close: Decimal | None = None
    volume: int | None = None
    provider: str
    is_synthetic: bool
    proxy_source_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class MarketDataRangeResponse(BaseModel):
    """Schema for market data over a date range."""

    asset_id: int
    ticker: str
    exchange: str
    from_date: dt.date
    to_date: dt.date
    data: list[MarketDataPointResponse]
    total: int
