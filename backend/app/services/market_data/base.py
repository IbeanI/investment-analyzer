# backend/app/services/market_data/base.py
"""
Abstract interface for market data providers.

This module defines the contract that all market data providers must follow.
Using an abstract base class allows for:
- Easy addition of new providers (Bloomberg, Alpha Vantage, etc.)
- Provider fallback strategies
- Mock implementations for testing

Design Principles:
- Interface Segregation: Only essential methods in the base class
- Dependency Inversion: Services depend on abstractions, not concrete implementations
- Open/Closed: New providers can be added without modifying existing code
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models import AssetClass


@dataclass(frozen=True)
class AssetInfo:
    """
    Asset metadata returned from a market data provider.

    This is a read-only data transfer object containing asset information.
    Using frozen=True makes it immutable and hashable (suitable for caching).

    Note: This represents METADATA (relatively static), not PRICES (dynamic).
    Price data will be handled separately in Phase 3.

    Attributes:
        ticker: Trading symbol, normalized to uppercase (e.g., "NVDA")
        exchange: Exchange code, normalized to uppercase (e.g., "NASDAQ")
        name: Full company/fund name (e.g., "NVIDIA Corporation")
        asset_class: Type of security (STOCK, ETF, BOND, etc.)
        currency: Trading currency in ISO 4217 format (e.g., "USD")
        sector: Industry sector (e.g., "Technology")
        region: Geographic region (e.g., "United States")
        isin: International Securities Identification Number (if available)
    """

    ticker: str
    exchange: str
    name: str | None
    asset_class: AssetClass
    currency: str
    sector: str | None = None
    region: str | None = None
    isin: str | None = None

    def __post_init__(self) -> None:
        """Validate required fields after initialization."""
        if not self.ticker:
            raise ValueError("ticker is required")
        if not self.exchange:
            raise ValueError("exchange is required")
        if not self.currency:
            raise ValueError("currency is required")


class MarketDataProvider(ABC):
    """
    Abstract base class for market data providers.

    All market data providers (Yahoo Finance, Bloomberg, Alpha Vantage, etc.)
    must implement this interface to be usable by the asset resolution service.

    Example implementation:
        class YahooFinanceProvider(MarketDataProvider):
            @property
            def name(self) -> str:
                return "yahoo"

            def get_asset_info(self, ticker: str, exchange: str) -> AssetInfo:
                # Yahoo-specific implementation
                ...

            def is_available(self) -> bool:
                # Health check implementation
                ...
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique identifier for this provider.

        Used for logging, error messages, and provider selection.

        Returns:
            Provider name (e.g., "yahoo", "bloomberg", "alpha_vantage")
        """
        pass

    @abstractmethod
    def get_asset_info(self, ticker: str, exchange: str) -> AssetInfo:
        """
        Fetch metadata for an asset.

        This method retrieves static information about an asset such as
        its name, sector, currency, and asset class. It does NOT fetch
        price data (that will be added in Phase 3).

        Args:
            ticker: Trading symbol (e.g., "NVDA", "AAPL")
                    Should be normalized to uppercase by the caller.
            exchange: Exchange code (e.g., "NASDAQ", "XETRA")
                      Should be normalized to uppercase by the caller.

        Returns:
            AssetInfo containing all available metadata for the asset.

        Raises:
            TickerNotFoundError: The ticker is not recognized by this provider.
            ProviderUnavailableError: The provider API is unreachable.
            RateLimitError: Too many requests to the provider.
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if the provider is currently available.

        This is a lightweight health check that can be used for:
        - Monitoring and alerting
        - Provider selection in fallback scenarios
        - Circuit breaker patterns

        Returns:
            True if the provider is responding normally, False otherwise.
        """
        pass

    # =========================================================================
    # PLACEHOLDER FOR PHASE 3 (Price Data)
    # =========================================================================
    #
    # The following methods will be added in Phase 3 when we implement
    # portfolio valuation and historical analysis:
    #
    # @abstractmethod
    # def get_current_price(self, ticker: str, exchange: str) -> Decimal:
    #     """Fetch the current/latest price for an asset."""
    #     pass
    #
    # @abstractmethod
    # def get_historical_prices(
    #     self,
    #     ticker: str,
    #     exchange: str,
    #     start_date: date,
    #     end_date: date,
    # ) -> list[PriceData]:
    #     """Fetch historical price data for an asset."""
    #     pass
