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
# DATA CLASSES
# =============================================================================

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


@dataclass
class BatchResult:
    """
    Result of a batch asset info fetch operation.

    Supports partial success: some tickers may succeed while others fail.
    This allows the caller to decide how to handle failures (skip, retry, abort).

    Attributes:
        successful: Dict mapping (ticker, exchange) to AssetInfo for found assets
        failed: Dict mapping (ticker, exchange) to Exception for failed lookups

    Example:
        result = provider.get_asset_info_batch([
            ("NVDA", "NASDAQ"),
            ("INVALID", "NYSE"),
            ("AAPL", "NASDAQ"),
        ])

        # result.successful = {
        #     ("NVDA", "NASDAQ"): AssetInfo(...),
        #     ("AAPL", "NASDAQ"): AssetInfo(...),
        # }
        # result.failed = {
        #     ("INVALID", "NYSE"): TickerNotFoundError(...),
        # }

        print(f"Found {result.success_count}/{result.total_count} assets")
    """

    successful: dict[tuple[str, str], AssetInfo] = field(default_factory=dict)
    failed: dict[tuple[str, str], Exception] = field(default_factory=dict)

    @property
    def success_count(self) -> int:
        """Number of successfully fetched assets."""
        return len(self.successful)

    @property
    def failure_count(self) -> int:
        """Number of failed asset lookups."""
        return len(self.failed)

    @property
    def total_count(self) -> int:
        """Total number of assets requested."""
        return self.success_count + self.failure_count

    @property
    def all_successful(self) -> bool:
        """True if all requests succeeded."""
        return self.failure_count == 0

    @property
    def all_failed(self) -> bool:
        """True if all requests failed."""
        return self.success_count == 0

    def get_asset(self, ticker: str, exchange: str) -> AssetInfo | None:
        """
        Get AssetInfo for a specific ticker/exchange, or None if not found.

        Args:
            ticker: Trading symbol
            exchange: Exchange code

        Returns:
            AssetInfo if found, None otherwise
        """
        return self.successful.get((ticker.upper(), exchange.upper()))

    def get_error(self, ticker: str, exchange: str) -> Exception | None:
        """
        Get the error for a specific ticker/exchange, or None if successful.

        Args:
            ticker: Trading symbol
            exchange: Exchange code

        Returns:
            Exception if failed, None otherwise
        """
        return self.failed.get((ticker.upper(), exchange.upper()))


# =============================================================================
# ABSTRACT BASE CLASS
# =============================================================================

class MarketDataProvider(ABC):
    """
    Abstract base class for market data providers.

    All market data providers (Yahoo Finance, Bloomberg, Alpha Vantage, etc.)
    must implement this interface to be usable by the asset resolution service.

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

    Example implementation:
        class YahooFinanceProvider(MarketDataProvider):
            # Optionally override retry config
            MAX_RETRY_ATTEMPTS = 5  # More retries for Yahoo

            @property
            def name(self) -> str:
                return "yahoo"

            def get_asset_info(self, ticker: str, exchange: str) -> AssetInfo:
                return self._execute_with_retry(
                    self._fetch_from_api,
                    ticker,
                    exchange,
                )

            def get_asset_info_batch(
                self,
                tickers: list[tuple[str, str]]
            ) -> BatchResult:
                return self._execute_with_retry(
                    self._fetch_batch_from_api,
                    tickers,
                )
    """

    # =========================================================================
    # RETRY CONFIGURATION (can be overridden by subclasses)
    # =========================================================================

    MAX_RETRY_ATTEMPTS: int = 3  # Total attempts (1 initial + 2 retries)
    RETRY_MIN_WAIT: int = 1  # Minimum wait between retries (seconds)
    RETRY_MAX_WAIT: int = 10  # Maximum wait between retries (seconds)
    RETRY_MULTIPLIER: int = 1  # Multiplier for exponential backoff

    # =========================================================================
    # BATCH CONFIGURATION (can be overridden by subclasses)
    # =========================================================================

    MAX_BATCH_SIZE: int = 100  # Maximum tickers per batch request

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

        This method retrieves static information about an asset such as
        its name, sector, currency, and asset class. It does NOT fetch
        price data (that will be added in Phase 3).

        Implementations SHOULD use `_execute_with_retry` for API calls
        to ensure consistent retry behavior.

        Args:
            ticker: Trading symbol (e.g., "NVDA", "AAPL")
                    Should be normalized to uppercase by the caller.
            exchange: Exchange code (e.g., "NASDAQ", "XETRA")
                      Should be normalized to uppercase by the caller.

        Returns:
            AssetInfo containing all available metadata for the asset.

        Raises:
            TickerNotFoundError: The ticker is not recognized by this provider.
            ProviderUnavailableError: The provider API is unreachable (after retries).
            RateLimitError: Too many requests to the provider (after retries).
        """
        pass

    @abstractmethod
    def get_asset_info_batch(
            self,
            tickers: list[tuple[str, str]],
    ) -> BatchResult:
        """
        Fetch metadata for multiple assets in a single operation.

        This method is optimized for bulk operations like CSV imports.
        It supports partial success - some tickers may be found while
        others fail.

        Implementations SHOULD:
        - Use batch API calls where available (e.g., yf.Tickers)
        - Handle partial failures gracefully
        - Respect MAX_BATCH_SIZE and chunk large requests
        - Use `_execute_with_retry` for API calls

        Args:
            tickers: List of (ticker, exchange) tuples to fetch.
                     Example: [("NVDA", "NASDAQ"), ("BMW", "XETRA")]

        Returns:
            BatchResult containing:
            - successful: Dict of (ticker, exchange) -> AssetInfo
            - failed: Dict of (ticker, exchange) -> Exception

        Raises:
            ProviderUnavailableError: Provider completely unreachable (after retries).
            RateLimitError: Rate limit exceeded (after retries).

        Note:
            Individual ticker failures (TickerNotFoundError) are captured
            in BatchResult.failed, not raised as exceptions.

        Example:
            result = provider.get_asset_info_batch([
                ("NVDA", "NASDAQ"),
                ("INVALID", "NYSE"),
            ])

            if result.all_successful:
                print("All assets found!")
            else:
                for key, error in result.failed.items():
                    print(f"Failed: {key} - {error}")
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
    # RETRY MECHANISM (inherited by all subclasses)
    # =========================================================================

    def _execute_with_retry(
            self,
            operation: Callable[..., T],
            *args: Any,
            **kwargs: Any,
    ) -> T:
        """
        Execute an operation with retry logic.

        This method wraps any callable with exponential backoff retry.
        It retries on transient failures (network issues, rate limits)
        but NOT on permanent failures (ticker not found).

        Subclasses can customize retry behavior by overriding class attributes:
        - MAX_RETRY_ATTEMPTS
        - RETRY_MIN_WAIT
        - RETRY_MAX_WAIT
        - RETRY_MULTIPLIER

        Args:
            operation: The callable to execute (e.g., API fetch method)
            *args: Positional arguments to pass to the operation
            **kwargs: Keyword arguments to pass to the operation

        Returns:
            The return value of the operation

        Raises:
            ProviderUnavailableError: After all retry attempts exhausted
            RateLimitError: After all retry attempts exhausted
            Any other exception: Immediately (not retried)

        Example:
            def get_asset_info(self, ticker, exchange):
                return self._execute_with_retry(
                    self._call_api,
                    ticker,
                    exchange,
                )
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
        def execute_operation() -> T:
            return operation(*args, **kwargs)

        return execute_operation()

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
    #
    # @abstractmethod
    # def get_current_prices_batch(
    #     self,
    #     tickers: list[tuple[str, str]],
    # ) -> BatchPriceResult:
    #     """Fetch current prices for multiple assets."""
    #     pass
