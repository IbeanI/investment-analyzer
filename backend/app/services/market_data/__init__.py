# backend/app/services/market_data/__init__.py
"""
Market data providers package.

This package contains the abstract interface for market data providers
and concrete implementations (Yahoo Finance, etc.).

Usage:
    from app.services.market_data import MarketDataProvider, AssetInfo
    from app.services.market_data import YahooFinanceProvider

Architecture:
    MarketDataProvider (ABC)
    └── YahooFinanceProvider (concrete)
    └── BloombergProvider (future)
    └── AlphaVantageProvider (future)
"""

from app.services.market_data.base import MarketDataProvider, AssetInfo
from app.services.market_data.yahoo import YahooFinanceProvider

__all__ = [
    # Abstract interface
    "MarketDataProvider",
    "AssetInfo",
    # Concrete implementations
    "YahooFinanceProvider",
]
