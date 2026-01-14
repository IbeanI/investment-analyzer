# backend/app/services/market_data/yahoo.py
"""
Yahoo Finance market data provider implementation.

This module implements the MarketDataProvider interface using the yfinance library.
Yahoo Finance is a free data source suitable for personal/educational use.

Key features:
- Exchange code mapping (our codes → Yahoo's format)
- Quote type mapping (Yahoo's types → our AssetClass)
- Comprehensive error handling
- Timeout configuration

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
from app.services.market_data.base import MarketDataProvider, AssetInfo

logger = logging.getLogger(__name__)


class YahooFinanceProvider(MarketDataProvider):
    """
    Yahoo Finance implementation of MarketDataProvider.

    Uses the yfinance library to fetch asset metadata from Yahoo Finance.

    Configuration:
        timeout: API request timeout in seconds (default: 10)

    Example:
        provider = YahooFinanceProvider(timeout=15)
        info = provider.get_asset_info("NVDA", "NASDAQ")
        print(info.name)  # "NVIDIA Corporation"
    """

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
        "FUTURE": AssetClass.FUTURE,
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

    def get_asset_info(self, ticker: str, exchange: str) -> AssetInfo:
        """
        Fetch asset metadata from Yahoo Finance.

        Args:
            ticker: Trading symbol (e.g., "NVDA")
            exchange: Exchange code (e.g., "NASDAQ")

        Returns:
            AssetInfo with metadata from Yahoo Finance.

        Raises:
            TickerNotFoundError: Ticker not recognized by Yahoo.
            ProviderUnavailableError: Yahoo API is unreachable.
            RateLimitError: Too many requests to Yahoo.
        """
        # Normalize inputs
        ticker = ticker.strip().upper()
        exchange = exchange.strip().upper()

        # Build Yahoo symbol
        yahoo_symbol = self._build_yahoo_symbol(ticker, exchange)
        logger.debug(f"Fetching asset info for {yahoo_symbol} (ticker={ticker}, exchange={exchange})")

        # Fetch data from Yahoo
        yahoo_data = self._fetch_ticker_info(yahoo_symbol, ticker, exchange)

        # Map to AssetInfo
        return self._map_to_asset_info(yahoo_data, ticker, exchange)

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
    # PRIVATE METHODS
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

    def _fetch_ticker_info(
            self,
            yahoo_symbol: str,
            original_ticker: str,
            original_exchange: str,
    ) -> dict[str, Any]:
        """
        Fetch raw ticker data from Yahoo Finance API.

        Args:
            yahoo_symbol: Yahoo-formatted symbol (e.g., "BMW.DE")
            original_ticker: Original ticker for error messages
            original_exchange: Original exchange for error messages

        Returns:
            Dictionary of ticker information from Yahoo.

        Raises:
            TickerNotFoundError: Symbol not found.
            ProviderUnavailableError: API error or timeout.
            RateLimitError: Rate limit exceeded.
        """
        try:
            yf_ticker = yf.Ticker(yahoo_symbol)
            info = yf_ticker.info

            # yfinance returns an empty dict or minimal info for invalid tickers
            if not info or info.get("regularMarketPrice") is None:
                # Double-check by looking for other indicators
                if not info.get("shortName") and not info.get("longName"):
                    logger.warning(f"Ticker not found on Yahoo: {yahoo_symbol}")
                    raise TickerNotFoundError(
                        ticker=original_ticker,
                        exchange=original_exchange,
                        provider=self.name,
                    )

            return info

        except TickerNotFoundError:
            # Re-raise our own exceptions
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
                logger.error(f"Yahoo Finance unavailable: {e}")
                raise ProviderUnavailableError(provider=self.name, reason=str(e))

            # Log unexpected errors and treat as unavailable
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
