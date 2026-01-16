# backend/app/services/market_data/base.py
"""
Abstract interface for market data providers.

This module defines the contract that all market data providers must follow.
Using an abstract base class allows for:
- Easy addition of new providers (Bloomberg, Alpha Vantage, etc.)
- Provider fallback strategies
- Mock implementations for testing
- Consistent retry behavior across all providers

Design Principles:
- Interface Segregation: Only essential methods in the base class
- Dependency Inversion: Services depend on abstractions, not concrete implementations
- Open/Closed: New providers can be added without modifying existing code
- DRY: Common retry logic implemented once in base class
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TypeVar, Callable, Any

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from app.models import AssetClass
from app.services.exceptions import (
    ProviderUnavailableError,
    RateLimitError,
)

logger = logging.getLogger(__name__)

# Type variable for generic return type in retry method
T = TypeVar('T')


# =============================================================================
# DATA CLASSES - ASSET METADATA
# =============================================================================

@dataclass(frozen=True)
class AssetInfo:
    """
    Asset metadata returned from a market data provider.

    This is a read-only data transfer object containing asset information.
    Using frozen=True makes it immutable and hashable (suitable for caching).

    Note: This represents METADATA (relatively static), not PRICES (dynamic).

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
        if not self.currency:
            raise ValueError("currency is required")


@dataclass
class BatchResult:
    """
    Result of a batch asset info fetch operation.

    Tracks which lookups succeeded and which failed, allowing partial success.

    Attributes:
        successful: Dict mapping (ticker, exchange) to AssetInfo
        failed: Dict mapping (ticker, exchange) to the exception that occurred
    """

    successful: dict[tuple[str, str], AssetInfo] = field(default_factory=dict)
    failed: dict[tuple[str, str], Exception] = field(default_factory=dict)

    @property
    def success_count(self) -> int:
        return len(self.successful)

    @property
    def failure_count(self) -> int:
        return len(self.failed)

    @property
    def total_count(self) -> int:
        return self.success_count + self.failure_count

    @property
    def all_successful(self) -> bool:
        return self.failure_count == 0


# =============================================================================
# DATA CLASSES - PRICE DATA (OHLCV)
# =============================================================================

@dataclass(frozen=True)
class OHLCVData:
    """
    Single day's OHLCV (Open, High, Low, Close, Volume) price data.

    This is the standard format for daily price data from market data providers.
    Using frozen=True makes it immutable and suitable for caching.

    Attributes:
        date: Trading date (no time component)
        open: Opening price
        high: Highest price during the day
        low: Lowest price during the day
        close: Closing price (primary valuation price)
        volume: Trading volume (number of shares traded)
        adjusted_close: Close price adjusted for splits/dividends (optional)
    """

    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None = None
    adjusted_close: Decimal | None = None

    def __post_init__(self) -> None:
        """Validate price data."""
        if self.close <= 0:
            raise ValueError(f"close price must be positive, got {self.close}")
        # High should be >= Low (basic sanity check)
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) cannot be less than low ({self.low})")


@dataclass
class HistoricalPricesResult:
    """
    Result of fetching historical prices for an asset.

    Tracks the fetch outcome and any issues encountered.

    Attributes:
        ticker: The ticker symbol requested
        exchange: The exchange code requested
        prices: List of OHLCV data points (empty if failed)
        success: Whether the fetch was successful
        error: Error message if fetch failed
        from_date: Requested start date
        to_date: Requested end date
        actual_from_date: Actual earliest date in returned data
        actual_to_date: Actual latest date in returned data
    """

    ticker: str
    exchange: str
    prices: list[OHLCVData] = field(default_factory=list)
    success: bool = True
    error: str | None = None
    from_date: date | None = None
    to_date: date | None = None
    actual_from_date: date | None = None
    actual_to_date: date | None = None

    def __post_init__(self) -> None:
        """Set actual date range from prices if not provided."""
        if self.prices and self.actual_from_date is None:
            self.actual_from_date = min(p.date for p in self.prices)
        if self.prices and self.actual_to_date is None:
            self.actual_to_date = max(p.date for p in self.prices)

    @property
    def days_fetched(self) -> int:
        """Number of trading days fetched."""
        return len(self.prices)


@dataclass
class BatchPricesResult:
    """
    Result of fetching historical prices for multiple assets.

    Attributes:
        results: Dict mapping (ticker, exchange) to HistoricalPricesResult
    """

    results: dict[tuple[str, str], HistoricalPricesResult] = field(default_factory=dict)

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results.values() if r.success)

    @property
    def failure_count(self) -> int:
        return sum(1 for r in self.results.values() if not r.success)

    @property
    def total_prices_fetched(self) -> int:
        return sum(r.days_fetched for r in self.results.values())

    @property
    def all_successful(self) -> bool:
        return self.failure_count == 0


# =============================================================================
# ABSTRACT BASE CLASS
# =============================================================================

class MarketDataProvider(ABC):
    """
    Abstract base class for market data providers.

    All market data providers (Yahoo Finance, Bloomberg, Alpha Vantage, etc.)
    must implement this interface to be usable by the application services.

    Retry Behavior:
        The base class provides a `_execute_with_retry` method that implements
        exponential backoff retry logic. Subclasses can override the retry
        configuration by setting class attributes:

        - MAX_RETRY_ATTEMPTS: Total attempts (default: 3)
        - RETRY_MIN_WAIT: Minimum wait in seconds (default: 1)
        - RETRY_MAX_WAIT: Maximum wait in seconds (default: 10)
        - RETRY_MULTIPLIER: Exponential multiplier (default: 1)

    Retryable Exceptions:
        - ProviderUnavailableError: Network issues, timeouts, server errors
        - RateLimitError: API rate limit exceeded

    Non-Retryable Exceptions:
        - TickerNotFoundError: Permanent failure (ticker doesn't exist)
    """

    # =========================================================================
    # RETRY CONFIGURATION (can be overridden by subclasses)
    # =========================================================================

    MAX_RETRY_ATTEMPTS: int = 3
    RETRY_MIN_WAIT: int = 1
    RETRY_MAX_WAIT: int = 10
    RETRY_MULTIPLIER: int = 1

    # =========================================================================
    # BATCH CONFIGURATION (can be overridden by subclasses)
    # =========================================================================

    MAX_BATCH_SIZE: int = 100

    # =========================================================================
    # ABSTRACT PROPERTIES AND METHODS
    # =========================================================================

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
        Fetch metadata for a single asset.

        Args:
            ticker: Trading symbol (e.g., "NVDA", "AAPL")
            exchange: Exchange code (e.g., "NASDAQ", "XETRA")

        Returns:
            AssetInfo with the asset's metadata

        Raises:
            TickerNotFoundError: Ticker not found on the exchange
            ProviderUnavailableError: Network or API error (retryable)
            RateLimitError: Rate limit exceeded (retryable)
        """
        pass

    @abstractmethod
    def get_asset_info_batch(
            self,
            tickers: list[tuple[str, str]]
    ) -> BatchResult:
        """
        Fetch metadata for multiple assets.

        This method handles partial failures - some lookups may succeed
        while others fail. Check BatchResult.failed for failures.

        Args:
            tickers: List of (ticker, exchange) tuples

        Returns:
            BatchResult with successful and failed lookups
        """
        pass

    @abstractmethod
    def get_historical_prices(
            self,
            ticker: str,
            exchange: str,
            start_date: date,
            end_date: date,
    ) -> HistoricalPricesResult:
        """
        Fetch historical OHLCV price data for a single asset.

        Args:
            ticker: Trading symbol (e.g., "NVDA", "AAPL")
            exchange: Exchange code (e.g., "NASDAQ", "XETRA")
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            HistoricalPricesResult with OHLCV data

        Raises:
            TickerNotFoundError: Ticker not found on the exchange
            ProviderUnavailableError: Network or API error (retryable)
            RateLimitError: Rate limit exceeded (retryable)
        """
        pass

    def get_historical_prices_batch(
            self,
            requests: list[tuple[str, str, date, date]],
    ) -> BatchPricesResult:
        """
        Fetch historical prices for multiple assets.

        Default implementation calls get_historical_prices() for each request.
        Subclasses can override for more efficient batch fetching.

        Args:
            requests: List of (ticker, exchange, start_date, end_date) tuples

        Returns:
            BatchPricesResult with results for each request
        """
        result = BatchPricesResult()

        for ticker, exchange, start_date, end_date in requests:
            key = (ticker.upper(), exchange.upper())
            try:
                prices_result = self.get_historical_prices(
                    ticker, exchange, start_date, end_date
                )
                result.results[key] = prices_result
            except Exception as e:
                logger.error(f"Failed to fetch prices for {ticker}/{exchange}: {e}")
                result.results[key] = HistoricalPricesResult(
                    ticker=ticker.upper(),
                    exchange=exchange.upper(),
                    success=False,
                    error=str(e),
                    from_date=start_date,
                    to_date=end_date,
                )

        return result

    # =========================================================================
    # RETRY HELPER METHOD
    # =========================================================================

    def _execute_with_retry(
            self,
            func: Callable[..., T],
            *args: Any,
            **kwargs: Any,
    ) -> T:
        """
        Execute a function with retry logic for transient failures.

        Uses exponential backoff for retryable exceptions:
        - ProviderUnavailableError
        - RateLimitError

        Does NOT retry on:
        - TickerNotFoundError (permanent failure)
        - Other exceptions

        Args:
            func: Function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Return value of func

        Raises:
            The last exception if all retries fail
        """

        @retry(
            stop=stop_after_attempt(self.MAX_RETRY_ATTEMPTS),
            wait=wait_exponential(
                multiplier=self.RETRY_MULTIPLIER,
                min=self.RETRY_MIN_WAIT,
                max=self.RETRY_MAX_WAIT,
            ),
            retry=retry_if_exception_type((ProviderUnavailableError, RateLimitError)),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        def _inner() -> T:
            return func(*args, **kwargs)

        return _inner()

    # =========================================================================
    # OPTIONAL METHODS (with default implementations)
    # =========================================================================

    def is_available(self) -> bool:
        """
        Check if the provider is currently available.

        Default implementation returns True. Subclasses can override
        to implement health checks.

        Returns:
            True if provider is available, False otherwise
        """
        return True
