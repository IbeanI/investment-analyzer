# backend/app/services/market_data/yahoo.py
"""
Yahoo Finance market data provider implementation.

This module implements the MarketDataProvider interface using the yfinance library.
Yahoo Finance is a free data source suitable for personal/educational use.

Key features:
- Exchange code mapping (our codes → Yahoo's format)
- Quote type mapping (Yahoo's types → our AssetClass)
- Comprehensive error handling
- Retry mechanism inherited from base class
- Batch fetching for efficient bulk operations

Limitations:
- Rate limits (not officially documented, but exist)
- Data may be delayed (15-20 minutes for some markets)
- Not suitable for high-frequency trading applications

Note: For production use with significant volume, consider paid providers
like Bloomberg, Refinitiv, or Alpha Vantage Premium.
"""

import logging
from typing import Any

import yfinance as yf

from app.models import AssetClass
from app.services.exceptions import (
    ProviderUnavailableError,
    TickerNotFoundError,
    RateLimitError,
)
from app.services.market_data.base import (
    MarketDataProvider,
    AssetInfo,
    BatchResult,
)

logger = logging.getLogger(__name__)


class YahooFinanceProvider(MarketDataProvider):
    """
    Yahoo Finance implementation of MarketDataProvider.

    Uses the yfinance library to fetch asset metadata from Yahoo Finance.

    Configuration:
        timeout: API request timeout in seconds (default: 10)

    Retry Behavior (inherited from MarketDataProvider):
        - Retries on ProviderUnavailableError and RateLimitError
        - Does NOT retry on TickerNotFoundError (permanent failure)
        - Uses exponential backoff: 1s → 2s → 4s
        - Maximum 3 attempts (configurable via class attributes)

    Batch Behavior:
        - Uses yf.Tickers() for efficient bulk fetching
        - Handles partial failures (some tickers found, others not)
        - Chunks large requests to respect MAX_BATCH_SIZE

    Example:
        provider = YahooFinanceProvider(timeout=15)

        # Single fetch
        info = provider.get_asset_info("NVDA", "NASDAQ")
        print(info.name)  # "NVIDIA Corporation"

        # Batch fetch
        result = provider.get_asset_info_batch([
            ("NVDA", "NASDAQ"),
            ("BMW", "XETRA"),
        ])
        print(f"Found {result.success_count} assets")
    """

    # =========================================================================
    # RETRY CONFIGURATION (override base class if needed)
    # =========================================================================
    # Uncomment to customize retry behavior for Yahoo specifically:
    # MAX_RETRY_ATTEMPTS: int = 5    # Yahoo may need more retries
    # RETRY_MIN_WAIT: int = 2        # Longer initial wait

    # =========================================================================
    # EXCHANGE MAPPING
    # =========================================================================
    # Maps our exchange codes to Yahoo Finance suffixes.
    # Yahoo uses suffixes like .DE for German exchanges, .L for London, etc.
    # US exchanges (NASDAQ, NYSE, AMEX) typically have no suffix.
    #
    # This mapping will be expanded based on user requirements.
    # =========================================================================

    EXCHANGE_TO_YAHOO_SUFFIX: dict[str, str] = {
        # United States (no suffix)
        "NASDAQ": "",
        "NYSE": "",
        "AMEX": "",
        "NYSEARCA": "",
        "BATS": "",
        # Germany
        "TGATE": ".DE",
        "XETRA": ".DE",
        "FRA": ".F",
        "FRANKFURT": ".F",
        # United Kingdom
        "LSE": ".L",
        "LONDON": ".L",
        # France
        "EURONEXT": ".PA",
        "EPA": ".PA",
        "PARIS": ".PA",
        # Netherlands
        "AMS": ".AS",
        "AMSTERDAM": ".AS",
        # Japan
        "TSE": ".T",
        "TYO": ".T",
        "TOKYO": ".T",
        # Hong Kong
        "HKEX": ".HK",
        "HKG": ".HK",
        # Australia
        "ASX": ".AX",
        # Canada
        "TSX": ".TO",
        "TORONTO": ".TO",
        # Switzerland
        "SWX": ".SW",
        "SWISS": ".SW",
        # Italy
        "MIL": ".MI",
        "MILAN": ".MI",
        # Spain
        "BME": ".MC",
        "MADRID": ".MC",
        # Singapore
        "SGX": ".SI",
        # South Korea
        "KRX": ".KS",
        "KOSPI": ".KS",
        # India
        "NSE": ".NS",
        "BSE": ".BO",
        # Brazil
        "BOVESPA": ".SA",
        "B3": ".SA",
        # Mexico
        "BMV": ".MX",
    }

    # =========================================================================
    # QUOTE TYPE MAPPING
    # =========================================================================
    # Maps Yahoo's quoteType field to our AssetClass enum.
    # Yahoo returns types like "EQUITY", "ETF", "CRYPTOCURRENCY", etc.
    # =========================================================================

    YAHOO_QUOTE_TYPE_TO_ASSET_CLASS: dict[str, AssetClass] = {
        "EQUITY": AssetClass.STOCK,
        "ETF": AssetClass.ETF,
        "MUTUALFUND": AssetClass.ETF,  # Treat mutual funds as ETF-like
        "INDEX": AssetClass.INDEX,
        "CRYPTOCURRENCY": AssetClass.CRYPTO,
        "CURRENCY": AssetClass.CASH,
        "BOND": AssetClass.BOND,
        "OPTION": AssetClass.OPTION,
        "FUTURE": AssetClass.OTHER,
    }

    # Default timeout for API requests (seconds)
    DEFAULT_TIMEOUT: int = 10

    def __init__(self, timeout: int | None = None) -> None:
        """
        Initialize the Yahoo Finance provider.

        Args:
            timeout: Request timeout in seconds. Defaults to 10 seconds.
        """
        self._timeout = timeout or self.DEFAULT_TIMEOUT

    @property
    def name(self) -> str:
        """Provider identifier."""
        return "yahoo"

    # =========================================================================
    # SINGLE FETCH
    # =========================================================================

    def get_asset_info(self, ticker: str, exchange: str) -> AssetInfo:
        """
        Fetch asset metadata from Yahoo Finance.

        Uses the inherited retry mechanism for resilience against
        transient failures.

        Args:
            ticker: Trading symbol (e.g., "NVDA")
            exchange: Exchange code (e.g., "NASDAQ")

        Returns:
            AssetInfo with metadata from Yahoo Finance.

        Raises:
            TickerNotFoundError: Ticker not recognized by Yahoo (not retried).
            ProviderUnavailableError: Yahoo API unreachable (after retries).
            RateLimitError: Rate limit exceeded (after retries).
        """
        # Normalize inputs
        ticker = ticker.strip().upper()
        exchange = exchange.strip().upper()

        # Build Yahoo symbol
        yahoo_symbol = self._build_yahoo_symbol(ticker, exchange)
        logger.debug(
            f"Fetching asset info for {yahoo_symbol} "
            f"(ticker={ticker}, exchange={exchange})"
        )

        # Fetch data from Yahoo with retry (inherited from base class)
        yahoo_data = self._execute_with_retry(
            self._fetch_ticker_info,
            yahoo_symbol,
            ticker,
            exchange,
        )

        # Map to AssetInfo
        return self._map_to_asset_info(yahoo_data, ticker, exchange)

    # =========================================================================
    # BATCH FETCH
    # =========================================================================

    def get_asset_info_batch(
            self,
            tickers: list[tuple[str, str]],
    ) -> BatchResult:
        """
        Fetch metadata for multiple assets in a single operation.

        Uses yf.Tickers() for efficient batch fetching. Handles partial
        failures gracefully - if some tickers are not found, they are
        reported in BatchResult.failed while successful ones are in
        BatchResult.successful.

        Args:
            tickers: List of (ticker, exchange) tuples to fetch.
                     Example: [("NVDA", "NASDAQ"), ("BMW", "XETRA")]

        Returns:
            BatchResult with successful and failed lookups.

        Raises:
            ProviderUnavailableError: Yahoo completely unreachable (after retries).
            RateLimitError: Rate limit exceeded (after retries).
        """
        if not tickers:
            logger.debug("Empty ticker list, returning empty BatchResult")
            return BatchResult()

        # Normalize all inputs
        normalized_tickers = [
            (ticker.strip().upper(), exchange.strip().upper())
            for ticker, exchange in tickers
        ]

        # Remove duplicates while preserving order
        unique_tickers = list(dict.fromkeys(normalized_tickers))

        logger.info(
            f"Batch fetching {len(unique_tickers)} unique assets "
            f"(from {len(tickers)} requested)"
        )

        # Chunk large requests
        if len(unique_tickers) > self.MAX_BATCH_SIZE:
            return self._fetch_batch_chunked(unique_tickers)

        # Execute batch fetch with retry
        return self._execute_with_retry(
            self._fetch_batch,
            unique_tickers,
        )

    def _fetch_batch_chunked(
            self,
            tickers: list[tuple[str, str]],
    ) -> BatchResult:
        """
        Fetch large batches by chunking into smaller requests.

        Args:
            tickers: List of (ticker, exchange) tuples (normalized)

        Returns:
            Combined BatchResult from all chunks
        """
        logger.info(
            f"Chunking {len(tickers)} tickers into batches of {self.MAX_BATCH_SIZE}"
        )

        combined_result = BatchResult()

        for i in range(0, len(tickers), self.MAX_BATCH_SIZE):
            chunk = tickers[i:i + self.MAX_BATCH_SIZE]
            chunk_num = (i // self.MAX_BATCH_SIZE) + 1
            total_chunks = (len(tickers) + self.MAX_BATCH_SIZE - 1) // self.MAX_BATCH_SIZE

            logger.debug(f"Processing chunk {chunk_num}/{total_chunks} ({len(chunk)} tickers)")

            # Fetch this chunk with retry
            chunk_result = self._execute_with_retry(
                self._fetch_batch,
                chunk,
            )

            # Merge results
            combined_result.successful.update(chunk_result.successful)
            combined_result.failed.update(chunk_result.failed)

        logger.info(
            f"Batch fetch complete: {combined_result.success_count} successful, "
            f"{combined_result.failure_count} failed"
        )

        return combined_result

    def _fetch_batch(
            self,
            tickers: list[tuple[str, str]],
    ) -> BatchResult:
        """
        Execute batch fetch using yf.Tickers().

        This is the core batch implementation that makes a single API call
        for multiple tickers.

        Args:
            tickers: List of (ticker, exchange) tuples (normalized)

        Returns:
            BatchResult with successful and failed lookups

        Raises:
            ProviderUnavailableError: API error (will be retried)
            RateLimitError: Rate limit hit (will be retried)
        """
        result = BatchResult()

        # Build mapping: yahoo_symbol -> (ticker, exchange)
        symbol_mapping: dict[str, tuple[str, str]] = {}
        for ticker, exchange in tickers:
            yahoo_symbol = self._build_yahoo_symbol(ticker, exchange)
            symbol_mapping[yahoo_symbol] = (ticker, exchange)

        # Build space-separated symbol string for yfinance
        symbols_str = " ".join(symbol_mapping.keys())

        logger.debug(f"Fetching batch from Yahoo: {symbols_str}")

        try:
            # Single API call for all tickers
            yf_tickers = yf.Tickers(symbols_str)

            # Process each ticker
            for yahoo_symbol, (ticker, exchange) in symbol_mapping.items():
                try:
                    # Get info for this ticker
                    yf_ticker = yf_tickers.tickers.get(yahoo_symbol)

                    if yf_ticker is None:
                        logger.warning(f"Ticker not in response: {yahoo_symbol}")
                        result.failed[(ticker, exchange)] = TickerNotFoundError(
                            ticker=ticker,
                            exchange=exchange,
                            provider=self.name,
                        )
                        continue

                    info = yf_ticker.info

                    # Validate we got real data
                    if not self._is_valid_ticker_info(info):
                        logger.warning(f"Invalid/empty data for: {yahoo_symbol}")
                        result.failed[(ticker, exchange)] = TickerNotFoundError(
                            ticker=ticker,
                            exchange=exchange,
                            provider=self.name,
                        )
                        continue

                    # Map to AssetInfo
                    asset_info = self._map_to_asset_info(info, ticker, exchange)
                    result.successful[(ticker, exchange)] = asset_info

                    logger.debug(f"Successfully fetched: {ticker} on {exchange}")

                except Exception as e:
                    # Individual ticker error - record and continue
                    logger.warning(f"Error processing {yahoo_symbol}: {e}")
                    result.failed[(ticker, exchange)] = TickerNotFoundError(
                        ticker=ticker,
                        exchange=exchange,
                        provider=self.name,
                    )

        except Exception as e:
            error_message = str(e).lower()

            # Check for rate limiting
            if "rate limit" in error_message or "too many requests" in error_message:
                logger.warning(f"Yahoo Finance rate limit hit during batch: {e}")
                raise RateLimitError(provider=self.name)

            # Check for network/timeout errors
            if any(
                    indicator in error_message
                    for indicator in ["timeout", "connection", "network", "unavailable"]
            ):
                logger.warning(f"Yahoo Finance unavailable during batch (will retry): {e}")
                raise ProviderUnavailableError(provider=self.name, reason=str(e))

            # Unexpected error - treat as provider unavailable
            logger.error(f"Unexpected error during batch fetch: {e}")
            raise ProviderUnavailableError(
                provider=self.name,
                reason=f"Unexpected error: {e}",
            )

        logger.info(
            f"Batch fetch result: {result.success_count} successful, "
            f"{result.failure_count} failed"
        )

        return result

    # =========================================================================
    # HEALTH CHECK
    # =========================================================================

    def is_available(self) -> bool:
        """
        Check if Yahoo Finance is responding.

        Attempts to fetch a well-known ticker (AAPL) as a health check.
        """
        try:
            test_ticker = yf.Ticker("AAPL")
            info = test_ticker.info
            # Check if we got meaningful data
            return info is not None and info.get("symbol") is not None
        except Exception as e:
            logger.warning(f"Yahoo Finance health check failed: {e}")
            return False

    # =========================================================================
    # PRIVATE HELPER METHODS
    # =========================================================================

    def _build_yahoo_symbol(self, ticker: str, exchange: str) -> str:
        """
        Convert ticker + exchange to Yahoo's symbol format.

        Yahoo uses suffixes for non-US exchanges:
        - US: "NVDA" (no suffix)
        - Germany: "BMW.DE"
        - UK: "VUAA.L"

        Args:
            ticker: Normalized ticker symbol
            exchange: Normalized exchange code

        Returns:
            Yahoo-compatible symbol string

        Examples:
            ("NVDA", "NASDAQ") → "NVDA"
            ("BMW", "XETRA") → "BMW.DE"
            ("VUAA", "LSE") → "VUAA.L"
        """
        suffix = self.EXCHANGE_TO_YAHOO_SUFFIX.get(exchange, "")

        if suffix:
            return f"{ticker}{suffix}"
        return ticker

    def _is_valid_ticker_info(self, info: dict[str, Any] | None) -> bool:
        """
        Check if Yahoo returned valid data for a ticker.

        yfinance returns empty dict or minimal info for invalid tickers.

        Args:
            info: Raw info dict from yfinance

        Returns:
            True if the data appears valid, False otherwise
        """
        if not info:
            return False

        # Check for key indicators of valid data
        has_price = info.get("regularMarketPrice") is not None
        has_name = info.get("shortName") or info.get("longName")

        return has_price or has_name

    def _fetch_ticker_info(
            self,
            yahoo_symbol: str,
            original_ticker: str,
            original_exchange: str,
    ) -> dict[str, Any]:
        """
        Fetch raw ticker data from Yahoo Finance API (single ticker).

        This method is called by `_execute_with_retry` from the base class.
        It should raise appropriate exceptions that the retry mechanism
        can handle:
        - TickerNotFoundError: NOT retried (permanent failure)
        - ProviderUnavailableError: Retried (transient failure)
        - RateLimitError: Retried (transient failure)

        Args:
            yahoo_symbol: Yahoo-formatted symbol (e.g., "BMW.DE")
            original_ticker: Original ticker for error messages
            original_exchange: Original exchange for error messages

        Returns:
            Dictionary of ticker information from Yahoo.

        Raises:
            TickerNotFoundError: Symbol not found (not retried).
            ProviderUnavailableError: API error or timeout (retried).
            RateLimitError: Rate limit exceeded (retried).
        """
        try:
            yf_ticker = yf.Ticker(yahoo_symbol)
            info = yf_ticker.info

            # Validate we got real data
            if not self._is_valid_ticker_info(info):
                logger.warning(f"Ticker not found on Yahoo: {yahoo_symbol}")
                raise TickerNotFoundError(
                    ticker=original_ticker,
                    exchange=original_exchange,
                    provider=self.name,
                )

            return info

        except TickerNotFoundError:
            # Re-raise - this is NOT retried (permanent failure)
            raise

        except Exception as e:
            error_message = str(e).lower()

            # Check for rate limiting indicators
            if "rate limit" in error_message or "too many requests" in error_message:
                logger.warning(f"Yahoo Finance rate limit hit: {e}")
                raise RateLimitError(provider=self.name)

            # Check for network/timeout errors
            if any(
                    indicator in error_message
                    for indicator in ["timeout", "connection", "network", "unavailable"]
            ):
                logger.warning(f"Yahoo Finance unavailable (will retry): {e}")
                raise ProviderUnavailableError(provider=self.name, reason=str(e))

            # Unexpected errors - treat as unavailable (will be retried)
            logger.error(f"Unexpected error fetching {yahoo_symbol}: {e}")
            raise ProviderUnavailableError(
                provider=self.name,
                reason=f"Unexpected error: {e}",
            )

    def _map_to_asset_info(
            self,
            yahoo_data: dict[str, Any],
            ticker: str,
            exchange: str,
    ) -> AssetInfo:
        """
        Map Yahoo Finance response to our AssetInfo dataclass.

        Args:
            yahoo_data: Raw data from Yahoo Finance API
            ticker: Original ticker (normalized)
            exchange: Original exchange (normalized)

        Returns:
            AssetInfo populated with Yahoo data.
        """
        # Extract and map asset class
        quote_type = yahoo_data.get("quoteType", "EQUITY")
        asset_class = self._map_quote_type(quote_type)

        # Extract name (prefer longName, fall back to shortName)
        name = yahoo_data.get("longName") or yahoo_data.get("shortName")

        # Extract currency (default to USD if not available)
        currency = yahoo_data.get("currency", "USD")
        if currency:
            currency = currency.upper()

        # Extract sector (may not be available for ETFs, indices, etc.)
        sector = yahoo_data.get("sector")

        # Extract region/country
        region = yahoo_data.get("country")

        # ISIN is typically not provided by Yahoo Finance
        isin = None

        return AssetInfo(
            ticker=ticker,
            exchange=exchange,
            name=name,
            asset_class=asset_class,
            currency=currency,
            sector=sector,
            region=region,
            isin=isin,
        )

    def _map_quote_type(self, yahoo_quote_type: str) -> AssetClass:
        """
        Map Yahoo's quoteType to our AssetClass enum.

        Args:
            yahoo_quote_type: Yahoo's quote type (e.g., "EQUITY", "ETF")

        Returns:
            Corresponding AssetClass enum value.
            Defaults to OTHER if type is not recognized.
        """
        asset_class = self.YAHOO_QUOTE_TYPE_TO_ASSET_CLASS.get(
            yahoo_quote_type,
            AssetClass.OTHER,
        )

        if yahoo_quote_type not in self.YAHOO_QUOTE_TYPE_TO_ASSET_CLASS:
            logger.warning(
                f"Unknown Yahoo quote type '{yahoo_quote_type}', defaulting to OTHER"
            )

        return asset_class
