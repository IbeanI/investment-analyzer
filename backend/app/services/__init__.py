# backend/app/services/__init__.py
"""
Service layer for business logic.

This package contains the service layer which encapsulates business logic
separate from the API (router) layer. Services:
- Have NO knowledge of HTTP (no HTTPException, no status codes)
- Raise domain-specific exceptions
- Receive database sessions as parameters (not via Depends)
- Are easily testable via dependency injection

Usage:
    from app.services import AssetResolutionService
    from app.services import FXRateService
    from app.services import MarketDataSyncService
    from app.services import ValuationService
    from app.services import (
        AssetNotFoundError,
        AssetDeactivatedError,
        MarketDataError,
        FXRateNotFoundError,
    )

Architecture:
    services/
    ├── __init__.py              # This file - main exports
    ├── exceptions.py            # Domain exceptions
    ├── asset_resolution.py      # Asset resolution service
    ├── fx_rate_service.py       # FX rate service (Phase 3)
    ├── market_data/             # Market data package
    │   ├── base.py              # Abstract provider interface
    │   ├── yahoo.py             # Yahoo Finance implementation
    │   └── sync_service.py      # Sync orchestration service
    └── valuation/               # Valuation service (Phase 4)
        ├── types.py             # Internal data types
        ├── calculators.py       # Calculation logic
        ├── history_calculator.py # Time series calculations
        └── service.py           # Main service orchestrator
"""

# Asset resolution
from app.services.asset_resolution import AssetResolutionService, BatchResolutionResult
# Exceptions
from app.services.exceptions import (
    # Base exceptions
    ServiceError,
    # Asset resolution exceptions
    AssetResolutionError,
    AssetNotFoundError,
    AssetDeactivatedError,
    # Market data exceptions
    MarketDataError,
    ProviderUnavailableError,
    TickerNotFoundError,
    RateLimitError,
    # FX rate exceptions (Phase 3)
    FXRateError,
    FXRateNotFoundError,
    FXProviderError,
)
# FX Rate Service (Phase 3)
from app.services.fx_rate_service import FXRateService, FXSyncResult, FXRateResult
# Market Data (Phase 3)
from app.services.market_data import (
    # Provider interface
    MarketDataProvider,
    AssetInfo,
    BatchResult,
    OHLCVData,
    HistoricalPricesResult,
    # Concrete providers
    YahooFinanceProvider,
    # Sync service
    MarketDataSyncService,
    SyncResult,
    PortfolioAnalysis,
)
# Valuation Service (Phase 4)
from app.services.valuation import ValuationService

__all__ = [
    # ==========================================================================
    # Services
    # ==========================================================================
    "AssetResolutionService",
    "BatchResolutionResult",
    # FX Rate Service
    "FXRateService",
    "FXSyncResult",
    "FXRateResult",
    # Market Data Sync Service
    "MarketDataSyncService",
    "SyncResult",
    "PortfolioAnalysis",
    # Market Data Provider
    "MarketDataProvider",
    "YahooFinanceProvider",
    "AssetInfo",
    "BatchResult",
    "OHLCVData",
    "HistoricalPricesResult",
    # Valuation Service (Phase 4)
    "ValuationService",

    # ==========================================================================
    # Exceptions
    # ==========================================================================
    # Base
    "ServiceError",
    # Asset resolution
    "AssetResolutionError",
    "AssetNotFoundError",
    "AssetDeactivatedError",
    # Market data
    "MarketDataError",
    "ProviderUnavailableError",
    "TickerNotFoundError",
    "RateLimitError",
    # FX rate
    "FXRateError",
    "FXRateNotFoundError",
    "FXProviderError",
]
