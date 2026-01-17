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
- Historical OHLCV price data fetching

Limitations:
- Rate limits (not officially documented, but exist)
- Data may be delayed (15-20 minutes for some markets)
- Not suitable for high-frequency trading applications

Note: For production use with significant volume, consider paid providers
like Bloomberg, Refinitiv, or Alpha Vantage Premium.
"""

import logging
import math
from datetime import date, timedelta
from decimal import Decimal
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
    OHLCVData,
    HistoricalPricesResult,
)

logger = logging.getLogger(__name__)


class YahooFinanceProvider(MarketDataProvider):
    """
    Yahoo Finance implementation of MarketDataProvider.

    Uses the yfinance library to fetch asset metadata and historical prices
    from Yahoo Finance.

    Configuration:
        timeout: API request timeout in seconds (default: 10)

    Retry Behavior (inherited from MarketDataProvider):
        - Retries on ProviderUnavailableError and RateLimitError
        - Does NOT retry on TickerNotFoundError (permanent failure)
        - Uses exponential backoff: 1s → 2s → 4s
        - Maximum 3 attempts (configurable via class attributes)

    Example:
        provider = YahooFinanceProvider(timeout=15)

        # Fetch asset metadata
        info = provider.get_asset_info("NVDA", "NASDAQ")
        print(info.name)  # "NVIDIA Corporation"

        # Fetch historical prices
        prices = provider.get_historical_prices(
            "NVDA", "NASDAQ",
            date(2024, 1, 1), date(2024, 12, 31)
        )
        print(f"Fetched {prices.days_fetched} days of data")
    """

    # =========================================================================
    # EXCHANGE MAPPING
    # =========================================================================
    # Maps our exchange codes to Yahoo Finance suffixes.
    # Yahoo uses suffixes for non-US exchanges (e.g., ".DE" for Germany).
    # US exchanges (NASDAQ, NYSE) use no suffix.

    EXCHANGE_SUFFIXES: dict[str, str] = {
        # US
        "NASDAQ": "",
        "NYSE": "",
        "NYSEARCA": "",
        "NYSEMKT": "",
        "BATS": "",
        "AMEX": "",
        "NMS": "",

        # Germany
        "IBIS": ".DE",
        "IBIS2": ".DE",
        "XETRA": ".DE",
        "FRA": ".F",
        "FRANKFURT": ".F",
        "TGATE": ".DE",

        # UK
        "LSE": ".L",
        "LONDON": ".L",
        "LON": ".L",

        # France
        "EPA": ".PA",
        "EURONEXT": ".PA",
        "SBF": ".PA",
        "PARIS": ".PA",

        # Netherlands
        "AMS": ".AS",
        "AEB": ".AS",

        # Belgium
        "BRU": ".BR",
        "EBR": ".BR",

        # Italy
        "BVME": ".MI",
        "MIL": ".MI",
        "BIT": ".MI",

        # Spain
        "BME": ".MC",
        "MCE": ".MC",

        # Switzerland
        "SWX": ".SW",
        "VTX": ".SW",

        # Japan
        "TYO": ".T",
        "TSE": ".T",
        "JPX": ".T",

        # Hong Kong
        "HKG": ".HK",
        "HKEX": ".HK",

        # China
        "SHA": ".SS",
        "SSE": ".SS",
        "SHE": ".SZ",
        "SZSE": ".SZ",

        # Canada
        "TSX": ".TO",
        "TORONTO": ".TO",
        "CVE": ".V",

        # Australia
        "ASX": ".AX",

        # India
        "NSE": ".NS",
        "BSE": ".BO",

        # Korea
        "KOSPI": ".KS",
        "KOSDAQ": ".KQ",

        # Nordics
        "STO": ".ST",  # Sweden
        "CPH": ".CO",  # Denmark
        "HEL": ".HE",  # Finland
        "OSL": ".OL",  # Norway

        # Latin America
        "B3": ".SA",  # Brazil
        "BMV": ".MX",  # Mexico
        "BCBA": ".BA",  # Argentina
        "SN": ".SN",  # Chile

        # Middle East
        "TASE": ".TA",
        "TADAWUL": ".SR",

        # Africa
        "JSE": ".JO",
    }

    # =========================================================================
    # QUOTE TYPE MAPPING
    # =========================================================================
    # Maps Yahoo Finance quote types to our AssetClass enum.

    QUOTE_TYPE_MAPPING: dict[str, AssetClass] = {
        "EQUITY": AssetClass.STOCK,
        "ETF": AssetClass.ETF,
        "MUTUALFUND": AssetClass.ETF,  # Treat mutual funds as ETFs
        "INDEX": AssetClass.INDEX,
        "CURRENCY": AssetClass.CASH,
        "CRYPTOCURRENCY": AssetClass.CRYPTO,
        "BOND": AssetClass.BOND,
        "OPTION": AssetClass.OPTION,
        "FUTURE": AssetClass.OTHER,  # Map to OTHER as it's not commonly used
    }

    # =========================================================================
    # INITIALIZATION
    # =========================================================================

    def __init__(self, timeout: int = 10) -> None:
        """
        Initialize the Yahoo Finance provider.

        Args:
            timeout: Request timeout in seconds
        """
        self._timeout = timeout
        logger.info(f"YahooFinanceProvider initialized (timeout={timeout}s)")

    @property
    def name(self) -> str:
        return "yahoo"

    # =========================================================================
    # ASSET METADATA METHODS
    # =========================================================================

    def get_asset_info(self, ticker: str, exchange: str) -> AssetInfo:
        """
        Fetch asset metadata from Yahoo Finance.

        Args:
            ticker: Trading symbol
            exchange: Exchange code

        Returns:
            AssetInfo with asset metadata

        Raises:
            TickerNotFoundError: If ticker not found
            ProviderUnavailableError: If Yahoo Finance unavailable
        """
        return self._execute_with_retry(
            self._fetch_asset_info,
            ticker,
            exchange,
        )

    def _fetch_asset_info(self, ticker: str, exchange: str) -> AssetInfo:
        """Internal method to fetch asset info (called by retry wrapper)."""
        ticker = ticker.strip().upper()
        exchange = exchange.strip().upper() if exchange else ""

        yahoo_symbol = self._build_yahoo_symbol(ticker, exchange)
        logger.debug(f"Fetching asset info for {yahoo_symbol}")

        try:
            yf_ticker = yf.Ticker(yahoo_symbol)
            info = yf_ticker.info

            if not self._is_valid_ticker_info(info):
                raise TickerNotFoundError(
                    ticker=ticker,
                    exchange=exchange,
                    provider=self.name,
                )

            return self._map_to_asset_info(info, ticker, exchange)

        except TickerNotFoundError:
            raise
        except Exception as e:
            error_str = str(e).lower()
            if "not found" in error_str or "no data" in error_str:
                raise TickerNotFoundError(
                    ticker=ticker,
                    exchange=exchange,
                    provider=self.name,
                )
            if "rate limit" in error_str or "too many requests" in error_str:
                raise RateLimitError(provider=self.name)

            logger.error(f"Yahoo Finance error for {yahoo_symbol}: {e}")
            raise ProviderUnavailableError(
                provider=self.name,
                reason=str(e),
            )

    def get_asset_info_batch(
            self,
            tickers: list[tuple[str, str]]
    ) -> BatchResult:
        """
        Fetch metadata for multiple assets.

        Uses yf.Tickers() for efficient batch fetching.
        """
        return self._execute_with_retry(
            self._fetch_asset_info_batch,
            tickers,
        )

    def _fetch_asset_info_batch(
            self,
            tickers: list[tuple[str, str]]
    ) -> BatchResult:
        """Internal batch fetch implementation."""
        result = BatchResult()

        if not tickers:
            return result

        # Build Yahoo symbols
        ticker_map: dict[str, tuple[str, str]] = {}
        for ticker, exchange in tickers:
            ticker = ticker.strip().upper()
            exchange = exchange.strip().upper() if exchange else ""
            yahoo_symbol = self._build_yahoo_symbol(ticker, exchange)
            ticker_map[yahoo_symbol] = (ticker, exchange)

        # Fetch in chunks
        symbols = list(ticker_map.keys())
        for i in range(0, len(symbols), self.MAX_BATCH_SIZE):
            chunk = symbols[i:i + self.MAX_BATCH_SIZE]
            self._fetch_batch_chunk(chunk, ticker_map, result)

        return result

    def _fetch_batch_chunk(
            self,
            symbols: list[str],
            ticker_map: dict[str, tuple[str, str]],
            result: BatchResult,
    ) -> None:
        """Fetch a chunk of symbols."""
        try:
            yf_tickers = yf.Tickers(" ".join(symbols))

            for yahoo_symbol in symbols:
                ticker, exchange = ticker_map[yahoo_symbol]
                key = (ticker, exchange)

                try:
                    yf_ticker = yf_tickers.tickers.get(yahoo_symbol)
                    if yf_ticker is None:
                        result.failed[key] = TickerNotFoundError(
                            ticker=ticker,
                            exchange=exchange,
                            provider=self.name,
                        )
                        continue

                    info = yf_ticker.info
                    if not self._is_valid_ticker_info(info):
                        result.failed[key] = TickerNotFoundError(
                            ticker=ticker,
                            exchange=exchange,
                            provider=self.name,
                        )
                        continue

                    result.successful[key] = self._map_to_asset_info(
                        info, ticker, exchange
                    )

                except Exception as e:
                    result.failed[key] = e

        except Exception as e:
            logger.error(f"Batch fetch failed: {e}")
            for yahoo_symbol in symbols:
                ticker, exchange = ticker_map[yahoo_symbol]
                key = (ticker, exchange)
                if key not in result.successful:
                    result.failed[key] = ProviderUnavailableError(
                        provider=self.name,
                        reason=str(e),
                    )

    # =========================================================================
    # HISTORICAL PRICE METHODS
    # =========================================================================

    def get_historical_prices(
            self,
            ticker: str,
            exchange: str,
            start_date: date,
            end_date: date,
    ) -> HistoricalPricesResult:
        """
        Fetch historical OHLCV price data from Yahoo Finance.

        Args:
            ticker: Trading symbol (e.g., "NVDA")
            exchange: Exchange code (e.g., "NASDAQ")
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            HistoricalPricesResult with OHLCV data

        Raises:
            TickerNotFoundError: If ticker not found
            ProviderUnavailableError: If Yahoo Finance unavailable
        """
        return self._execute_with_retry(
            self._fetch_historical_prices,
            ticker,
            exchange,
            start_date,
            end_date,
        )

    def _fetch_historical_prices(
            self,
            ticker: str,
            exchange: str,
            start_date: date,
            end_date: date,
    ) -> HistoricalPricesResult:
        """Internal method to fetch historical prices."""
        ticker = ticker.strip().upper()
        exchange = exchange.strip().upper() if exchange else ""

        yahoo_symbol = self._build_yahoo_symbol(ticker, exchange)

        logger.debug(
            f"Fetching historical prices for {yahoo_symbol}: "
            f"{start_date} to {end_date}"
        )

        result = HistoricalPricesResult(
            ticker=ticker,
            exchange=exchange,
            from_date=start_date,
            to_date=end_date,
        )

        try:
            yf_ticker = yf.Ticker(yahoo_symbol)

            # Yahoo Finance end date is exclusive, so add 1 day
            yahoo_end = end_date + timedelta(days=1)

            # Fetch historical data
            df = yf_ticker.history(
                start=start_date.isoformat(),
                end=yahoo_end.isoformat(),
                interval="1d",
                auto_adjust=False,  # Get raw prices, not adjusted. Adjusted prices take dividends into account and the values are removed
            )

            if df.empty:
                # Check if ticker exists at all
                info = yf_ticker.info
                if not self._is_valid_ticker_info(info):
                    raise TickerNotFoundError(
                        ticker=ticker,
                        exchange=exchange,
                        provider=self.name,
                    )

                # Ticker exists but no data for this range
                logger.warning(
                    f"No price data for {yahoo_symbol} "
                    f"between {start_date} and {end_date}"
                )
                result.success = True  # Not an error, just no data
                return result

            # Convert DataFrame to list of OHLCVData
            prices = self._dataframe_to_ohlcv(df)
            result.prices = prices
            result.success = True

            if prices:
                result.actual_from_date = min(p.date for p in prices)
                result.actual_to_date = max(p.date for p in prices)

            logger.debug(
                f"Fetched {len(prices)} days for {yahoo_symbol}"
            )

            return result

        except TickerNotFoundError:
            raise
        except Exception as e:
            error_str = str(e).lower()

            if "not found" in error_str or "no data" in error_str:
                raise TickerNotFoundError(
                    ticker=ticker,
                    exchange=exchange,
                    provider=self.name,
                )

            if "rate limit" in error_str or "too many requests" in error_str:
                raise RateLimitError(provider=self.name)

            logger.error(f"Yahoo Finance error for {yahoo_symbol}: {e}")
            raise ProviderUnavailableError(
                provider=self.name,
                reason=str(e),
            )

    def _dataframe_to_ohlcv(self, df) -> list[OHLCVData]:
        """
        Convert a pandas DataFrame from yfinance to list of OHLCVData.

        Args:
            df: DataFrame with columns: Open, High, Low, Close, Volume, Adj Close

        Returns:
            List of OHLCVData objects
        """
        prices = []

        for idx, row in df.iterrows():
            try:
                # Extract date (idx is a Timestamp)
                price_date = idx.date() if hasattr(idx, 'date') else idx

                # Extract prices, handling NaN values
                open_price = self._to_decimal(row.get('Open'))
                high_price = self._to_decimal(row.get('High'))
                low_price = self._to_decimal(row.get('Low'))
                close_price = self._to_decimal(row.get('Close'))
                adj_close = self._to_decimal(row.get('Adj Close'))
                volume = self._to_int(row.get('Volume'))

                # Skip rows with missing close price
                if close_price is None:
                    logger.warning(f"Skipping {price_date}: missing close price")
                    continue

                # Use close price as fallback for missing OHLC
                if open_price is None:
                    open_price = close_price
                if high_price is None:
                    high_price = close_price
                if low_price is None:
                    low_price = close_price

                prices.append(OHLCVData(
                    date=price_date,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    volume=volume,
                    adjusted_close=adj_close,
                ))

            except Exception as e:
                logger.warning(f"Error parsing row {idx}: {e}")
                continue

        return prices

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        """Convert a value to Decimal, returning None for NaN/None."""
        if value is None:
            return None
        try:
            if math.isnan(float(value)):
                return None
            return Decimal(str(value)).quantize(Decimal("0.00000001"))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value: Any) -> int | None:
        """Convert a value to int, returning None for NaN/None."""
        if value is None:
            return None
        try:
            if math.isnan(float(value)):
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _build_yahoo_symbol(self, ticker: str, exchange: str) -> str:
        """
        Build Yahoo Finance symbol from ticker and exchange.

        Args:
            ticker: Trading symbol
            exchange: Our exchange code

        Returns:
            Yahoo Finance symbol (e.g., "NVDA" or "SAP.DE")
        """
        suffix = self.EXCHANGE_SUFFIXES.get(exchange, "")
        return f"{ticker}{suffix}"

    def _is_valid_ticker_info(self, info: dict | None) -> bool:
        """
        Check if Yahoo Finance info dict represents a valid ticker.

        Yahoo returns an info dict even for invalid tickers, but it lacks
        meaningful data. We check for price or name to validate.
        """
        if not info:
            return False
        return bool(
            info.get("regularMarketPrice")
            or info.get("shortName")
            or info.get("longName")
        )

    def _map_quote_type(self, quote_type: str) -> AssetClass:
        """
        Map Yahoo Finance quote type to our AssetClass.

        Args:
            quote_type: Yahoo Finance quote type string

        Returns:
            Corresponding AssetClass enum value
        """
        return self.QUOTE_TYPE_MAPPING.get(quote_type, AssetClass.OTHER)

    def _map_to_asset_info(
            self,
            info: dict,
            ticker: str,
            exchange: str,
    ) -> AssetInfo:
        """Map Yahoo Finance info dict to our AssetInfo dataclass."""
        quote_type = info.get("quoteType", "EQUITY")
        asset_class = self.QUOTE_TYPE_MAPPING.get(quote_type, AssetClass.OTHER)

        name = info.get("longName") or info.get("shortName")
        currency = (info.get("currency") or "USD").upper()
        sector = info.get("sector")
        region = info.get("country")

        return AssetInfo(
            ticker=ticker,
            exchange=exchange,
            name=name,
            asset_class=asset_class,
            currency=currency,
            sector=sector,
            region=region,
            isin=None,  # Yahoo doesn't provide ISIN
        )
