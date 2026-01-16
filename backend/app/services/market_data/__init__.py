# backend/app/services/market_data/__init__.py
"""
Market data services package.

This package contains:
- Abstract interface for market data providers (base.py)
- Yahoo Finance implementation (yahoo.py)
- Market data sync orchestration (sync_service.py)

Usage:
    # Provider interface and data classes
    from app.services.market_data import (
        MarketDataProvider,
        AssetInfo,
        BatchResult,
        OHLCVData,
        HistoricalPricesResult,
    )

    # Yahoo Finance provider
    from app.services.market_data import YahooFinanceProvider

    # Sync service
    from app.services.market_data import (
        MarketDataSyncService,
        SyncResult,
        PortfolioAnalysis,
    )

Architecture:
    MarketDataProvider (ABC)
    └── YahooFinanceProvider (concrete)
    └── BloombergProvider (future)

    MarketDataSyncService
    └── Orchestrates price fetching
    └── Uses FXRateService for FX rates
    └── Updates SyncStatus
"""

# Base provider interface and data classes
from app.services.market_data.base import (
    MarketDataProvider,
    AssetInfo,
    BatchResult,
    OHLCVData,
    HistoricalPricesResult,
    BatchPricesResult,
)
# Sync service
from app.services.market_data.sync_service import (
    MarketDataSyncService,
    SyncResult,
    AssetSyncResult,
    PortfolioAnalysis,
    AssetSyncInfo,
)
# Concrete implementations
from app.services.market_data.yahoo import YahooFinanceProvider

__all__ = [
    # Abstract interface
    "MarketDataProvider",
    # Data classes - metadata
    "AssetInfo",
    "BatchResult",
    # Data classes - prices
    "OHLCVData",
    "HistoricalPricesResult",
    "BatchPricesResult",
    # Concrete implementations
    "YahooFinanceProvider",
    # Sync service
    "MarketDataSyncService",
    "SyncResult",
    "AssetSyncResult",
    "PortfolioAnalysis",
    "AssetSyncInfo",
]
