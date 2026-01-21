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
    from app.services import AnalyticsService
    from app.services import PortfolioSettingsService
    from app.services import (
        AssetNotFoundError,
        AssetDeactivatedError,
        MarketDataError,
        FXRateNotFoundError,
    )

Architecture:
    services/
    ├── __init__.py                  # This file - main exports
    ├── exceptions.py                # Domain exceptions
    ├── constants.py                 # Business constants and limits
    ├── protocols.py                 # Service interfaces (Protocol classes)
    ├── circuit_breaker.py           # Circuit breaker for external APIs
    ├── asset_resolution.py          # Asset resolution service
    ├── fx_rate_service.py           # FX rate service
    ├── portfolio_settings_service.py # Portfolio settings management
    ├── proxy_mapping_service.py     # Proxy asset mapping for backcasting
    ├── analytics/                   # Analytics engine
    │   ├── service.py               # Main analytics orchestrator
    │   ├── types.py                 # Analytics data types
    │   ├── returns.py               # Return calculations (TWR, IRR, CAGR)
    │   ├── risk.py                  # Risk metrics (Volatility, Sharpe, VaR)
    │   └── benchmark.py             # Benchmark comparison (Beta, Alpha)
    ├── market_data/                 # Market data package
    │   ├── base.py                  # Abstract provider interface
    │   ├── yahoo.py                 # Yahoo Finance implementation
    │   └── sync_service.py          # Sync orchestration service
    ├── upload/                      # File upload processing
    │   ├── service.py               # Upload orchestration service
    │   └── parsers/                 # File format parsers
    │       ├── base.py              # Abstract parser interface
    │       └── csv_parser.py        # CSV implementation
    └── valuation/                   # Valuation service
        ├── service.py               # Main valuation orchestrator
        ├── types.py                 # Valuation data types
        ├── calculators.py           # Point-in-time calculations
        └── history_calculator.py    # Time series calculations
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
# Portfolio Settings Service
from app.services.portfolio_settings_service import (
    PortfolioSettingsService,
    SettingsUpdateResult,
)
# Proxy Mapping Service
from app.services.proxy_mapping_service import (
    ProxyMappingService,
    ProxyConfig,
    ProxyMappingResult,
    ProxyApplied,
    ProxySkipped,
    ProxyFailed,
)
# Valuation Service
from app.services.valuation import ValuationService
# Analytics Service
from app.services.analytics import AnalyticsService

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
    # Valuation Service
    "ValuationService",
    # Analytics Service
    "AnalyticsService",

    # Portfolio Settings Service
    "PortfolioSettingsService",
    "SettingsUpdateResult",

    # Proxy Mapping Service
    "ProxyMappingService",
    "ProxyConfig",
    "ProxyMappingResult",
    "ProxyApplied",
    "ProxySkipped",
    "ProxyFailed",

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
