# backend/tests/services/test_yahoo_provider.py
"""
Tests for the YahooFinanceProvider.

This module tests:
- Exchange code to Yahoo suffix mapping
- Quote type to AssetClass mapping
- Symbol building logic
- Ticker info validation
- Error handling and classification
- Batch fetching behavior

Note: These tests mock the yfinance library to avoid actual API calls.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.models import AssetClass
from app.services.exceptions import (
    TickerNotFoundError,
    ProviderUnavailableError,
    RateLimitError,
)
from app.services.market_data.yahoo import YahooFinanceProvider


# =============================================================================
# PROVIDER INITIALIZATION
# =============================================================================

class TestYahooProviderInit:
    """Tests for provider initialization."""

    def test_provider_name(self):
        """Provider name should be 'yahoo'."""
        provider = YahooFinanceProvider()
        assert provider.name == "yahoo"

    def test_default_timeout(self):
        """Default timeout should be 10 seconds."""
        provider = YahooFinanceProvider()
        assert provider._timeout == 10

    def test_custom_timeout(self):
        """Should accept custom timeout."""
        provider = YahooFinanceProvider(timeout=30)
        assert provider._timeout == 30


# =============================================================================
# EXCHANGE MAPPING TESTS
# =============================================================================

class TestExchangeMapping:
    """Tests for exchange code to Yahoo suffix mapping."""

    @pytest.mark.parametrize("exchange,expected_suffix", [
        # US exchanges (no suffix)
        ("NASDAQ", ""),
        ("NYSE", ""),
        ("AMEX", ""),
        ("NYSEARCA", ""),
        ("BATS", ""),
        # German exchanges
        ("XETRA", ".DE"),
        ("FRA", ".F"),
        ("FRANKFURT", ".F"),
        ("TGATE", ".DE"),
        # UK
        ("LSE", ".L"),
        ("LONDON", ".L"),
        # France
        ("EURONEXT", ".PA"),
        ("SBF", ".PA"),
        ("PARIS", ".PA"),
        # Netherlands
        ("AEB", ".AS"),
        ("AMS", ".AS"),
        ("AMSTERDAM", ".AS"),
        # Japan
        ("TSE", ".T"),
        ("TYO", ".T"),
        ("TOKYO", ".T"),
        # Hong Kong
        ("HKEX", ".HK"),
        ("HKG", ".HK"),
        # Switzerland
        ("SWX", ".SW"),
        ("SWISS", ".SW"),
        # Australia
        ("ASX", ".AX"),
        # Canada
        ("TSX", ".TO"),
        ("TORONTO", ".TO"),
    ])
    def test_exchange_suffix_mapping(self, exchange, expected_suffix):
        """Should map exchange codes to correct Yahoo suffixes."""
        provider = YahooFinanceProvider()
        symbol = provider._build_yahoo_symbol("TEST", exchange)

        if expected_suffix:
            assert symbol == f"TEST{expected_suffix}"
        else:
            assert symbol == "TEST"

    def test_unknown_exchange_no_suffix(self):
        """Unknown exchanges should get no suffix."""
        provider = YahooFinanceProvider()
        symbol = provider._build_yahoo_symbol("TEST", "UNKNOWN_EXCHANGE")
        assert symbol == "TEST"

    def test_build_symbol_examples(self):
        """Test specific real-world examples."""
        provider = YahooFinanceProvider()

        # US stock
        assert provider._build_yahoo_symbol("NVDA", "NASDAQ") == "NVDA"

        # German stock
        assert provider._build_yahoo_symbol("BMW", "XETRA") == "BMW.DE"

        # UK ETF
        assert provider._build_yahoo_symbol("VUAA", "LSE") == "VUAA.L"

        # Japanese stock
        assert provider._build_yahoo_symbol("7203", "TSE") == "7203.T"


# =============================================================================
# QUOTE TYPE MAPPING TESTS
# =============================================================================

class TestQuoteTypeMapping:
    """Tests for Yahoo quote type to AssetClass mapping."""

    @pytest.mark.parametrize("quote_type,expected_class", [
        ("EQUITY", AssetClass.STOCK),
        ("ETF", AssetClass.ETF),
        ("MUTUALFUND", AssetClass.ETF),
        ("INDEX", AssetClass.INDEX),
        ("CRYPTOCURRENCY", AssetClass.CRYPTO),
        ("CURRENCY", AssetClass.CASH),
        ("BOND", AssetClass.BOND),
        ("OPTION", AssetClass.OPTION),
        ("FUTURE", AssetClass.OTHER),
    ])
    def test_quote_type_mapping(self, quote_type, expected_class):
        """Should map Yahoo quote types to correct AssetClass."""
        provider = YahooFinanceProvider()
        result = provider._map_quote_type(quote_type)
        assert result == expected_class

    def test_unknown_quote_type_returns_other(self):
        """Unknown quote types should map to OTHER."""
        provider = YahooFinanceProvider()
        result = provider._map_quote_type("UNKNOWN_TYPE")
        assert result == AssetClass.OTHER


# =============================================================================
# TICKER INFO VALIDATION TESTS
# =============================================================================

class TestTickerInfoValidation:
    """Tests for _is_valid_ticker_info method."""

    def test_valid_info_with_price(self):
        """Info with regularMarketPrice should be valid (truthy)."""
        provider = YahooFinanceProvider()
        info = {"regularMarketPrice": 100.50}
        assert provider._is_valid_ticker_info(info)  # Truthy

    def test_valid_info_with_name(self):
        """Info with shortName should be valid (truthy)."""
        provider = YahooFinanceProvider()
        info = {"shortName": "Test Company"}
        assert provider._is_valid_ticker_info(info)  # Returns the truthy string

    def test_valid_info_with_long_name(self):
        """Info with longName should be valid (truthy)."""
        provider = YahooFinanceProvider()
        info = {"longName": "Test Company Inc."}
        assert provider._is_valid_ticker_info(info)  # Returns the truthy string

    def test_invalid_empty_info(self):
        """Empty dict should be invalid (falsy)."""
        provider = YahooFinanceProvider()
        assert not provider._is_valid_ticker_info({})

    def test_invalid_none_info(self):
        """None should be invalid (falsy)."""
        provider = YahooFinanceProvider()
        assert not provider._is_valid_ticker_info(None)

    def test_invalid_info_with_no_meaningful_data(self):
        """Info without price or name should be invalid (falsy)."""
        provider = YahooFinanceProvider()
        info = {"symbol": "TEST", "market": "US"}
        assert not provider._is_valid_ticker_info(info)


# =============================================================================
# ASSET INFO MAPPING TESTS
# =============================================================================

class TestAssetInfoMapping:
    """Tests for _map_to_asset_info method."""

    def test_map_complete_data(self):
        """Should correctly map all fields from Yahoo data."""
        provider = YahooFinanceProvider()

        yahoo_data = {
            "quoteType": "EQUITY",
            "longName": "NVIDIA Corporation",
            "shortName": "NVIDIA",
            "currency": "USD",
            "sector": "Technology",
            "country": "United States",
        }

        result = provider._map_to_asset_info(yahoo_data, "NVDA", "NASDAQ")

        assert result.ticker == "NVDA"
        assert result.exchange == "NASDAQ"
        assert result.name == "NVIDIA Corporation"  # Prefers longName
        assert result.asset_class == AssetClass.STOCK
        assert result.currency == "USD"
        assert result.sector == "Technology"
        assert result.region == "United States"
        assert result.isin is None  # Yahoo doesn't provide ISIN

    def test_map_uses_short_name_fallback(self):
        """Should use shortName when longName is not available."""
        provider = YahooFinanceProvider()

        yahoo_data = {
            "quoteType": "ETF",
            "shortName": "Vanguard S&P 500 ETF",
            "currency": "USD",
        }

        result = provider._map_to_asset_info(yahoo_data, "VOO", "NYSEARCA")

        assert result.name == "Vanguard S&P 500 ETF"

    def test_map_normalizes_currency(self):
        """Should uppercase currency code."""
        provider = YahooFinanceProvider()

        yahoo_data = {
            "quoteType": "EQUITY",
            "shortName": "Test",
            "currency": "eur",  # lowercase
        }

        result = provider._map_to_asset_info(yahoo_data, "TEST", "XETRA")

        assert result.currency == "EUR"

    def test_map_defaults_to_usd(self):
        """Should default to USD when currency not provided."""
        provider = YahooFinanceProvider()

        yahoo_data = {
            "quoteType": "EQUITY",
            "shortName": "Test",
        }

        result = provider._map_to_asset_info(yahoo_data, "TEST", "NASDAQ")

        assert result.currency == "USD"

    def test_map_handles_missing_optional_fields(self):
        """Should handle missing sector and region."""
        provider = YahooFinanceProvider()

        yahoo_data = {
            "quoteType": "ETF",
            "shortName": "Test ETF",
            "currency": "USD",
            # No sector or country
        }

        result = provider._map_to_asset_info(yahoo_data, "TEST", "NASDAQ")

        assert result.sector is None
        assert result.region is None


# =============================================================================
# SINGLE FETCH TESTS (with mocked yfinance)
# =============================================================================

class TestGetAssetInfo:
    """Tests for get_asset_info method with mocked yfinance."""

    @patch('app.services.market_data.yahoo.yf')
    def test_successful_fetch(self, mock_yf):
        """Should return AssetInfo on successful fetch."""
        # Setup mock
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "quoteType": "EQUITY",
            "longName": "Apple Inc.",
            "currency": "USD",
            "regularMarketPrice": 150.0,
        }
        mock_yf.Ticker.return_value = mock_ticker

        provider = YahooFinanceProvider()
        result = provider.get_asset_info("AAPL", "NASDAQ")

        assert result.ticker == "AAPL"
        assert result.exchange == "NASDAQ"
        assert result.name == "Apple Inc."
        mock_yf.Ticker.assert_called_once_with("AAPL")

    @patch('app.services.market_data.yahoo.yf')
    def test_fetch_normalizes_input(self, mock_yf):
        """Should normalize ticker and exchange before fetch."""
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "quoteType": "EQUITY",
            "shortName": "Test",
            "currency": "USD",
            "regularMarketPrice": 100.0,
        }
        mock_yf.Ticker.return_value = mock_ticker

        provider = YahooFinanceProvider()
        result = provider.get_asset_info("  aapl  ", "  nasdaq  ")

        assert result.ticker == "AAPL"
        assert result.exchange == "NASDAQ"

    @patch('app.services.market_data.yahoo.yf')
    def test_fetch_ticker_not_found(self, mock_yf):
        """Should raise TickerNotFoundError when ticker info is invalid."""
        mock_ticker = MagicMock()
        mock_ticker.info = {}  # Empty = invalid
        mock_yf.Ticker.return_value = mock_ticker

        provider = YahooFinanceProvider()

        with pytest.raises(TickerNotFoundError) as exc_info:
            provider.get_asset_info("INVALID", "NYSE")

        assert exc_info.value.ticker == "INVALID"
        assert exc_info.value.exchange == "NYSE"
        assert exc_info.value.provider == "yahoo"

    @patch('app.services.market_data.yahoo.yf')
    def test_fetch_rate_limit_error(self, mock_yf):
        """Should raise RateLimitError on rate limit."""
        mock_yf.Ticker.side_effect = Exception("Too many requests")

        provider = YahooFinanceProvider()

        with pytest.raises(RateLimitError) as exc_info:
            provider.get_asset_info("AAPL", "NASDAQ")

        assert exc_info.value.provider == "yahoo"

    @patch('app.services.market_data.yahoo.yf')
    def test_fetch_network_error(self, mock_yf):
        """Should raise ProviderUnavailableError on network error."""
        mock_yf.Ticker.side_effect = Exception("Connection timeout")

        provider = YahooFinanceProvider()

        with pytest.raises(ProviderUnavailableError) as exc_info:
            provider.get_asset_info("AAPL", "NASDAQ")

        assert exc_info.value.provider == "yahoo"


# =============================================================================
# BATCH FETCH TESTS (with mocked yfinance)
# =============================================================================

class TestGetAssetInfoBatch:
    """Tests for get_asset_info_batch method with mocked yfinance."""

    @patch('app.services.market_data.yahoo.yf')
    def test_batch_fetch_all_success(self, mock_yf):
        """Should return all successful results in batch."""
        # Setup mock Tickers
        mock_tickers = MagicMock()
        mock_tickers.tickers = {
            "AAPL": MagicMock(info={
                "quoteType": "EQUITY",
                "shortName": "Apple Inc.",
                "currency": "USD",
                "regularMarketPrice": 150.0,
            }),
            "NVDA": MagicMock(info={
                "quoteType": "EQUITY",
                "shortName": "NVIDIA Corp",
                "currency": "USD",
                "regularMarketPrice": 400.0,
            }),
        }
        mock_yf.Tickers.return_value = mock_tickers

        provider = YahooFinanceProvider()
        result = provider.get_asset_info_batch([
            ("AAPL", "NASDAQ"),
            ("NVDA", "NASDAQ"),
        ])

        assert result.success_count == 2
        assert result.failure_count == 0
        assert ("AAPL", "NASDAQ") in result.successful
        assert ("NVDA", "NASDAQ") in result.successful

    @patch('app.services.market_data.yahoo.yf')
    def test_batch_fetch_partial_success(self, mock_yf):
        """Should handle partial success in batch."""
        mock_tickers = MagicMock()
        mock_tickers.tickers = {
            "AAPL": MagicMock(info={
                "quoteType": "EQUITY",
                "shortName": "Apple Inc.",
                "currency": "USD",
                "regularMarketPrice": 150.0,
            }),
            "INVALID": MagicMock(info={}),  # Invalid/empty
        }
        mock_yf.Tickers.return_value = mock_tickers

        provider = YahooFinanceProvider()
        result = provider.get_asset_info_batch([
            ("AAPL", "NASDAQ"),
            ("INVALID", "NYSE"),
        ])

        assert result.success_count == 1
        assert result.failure_count == 1
        assert ("AAPL", "NASDAQ") in result.successful
        assert ("INVALID", "NYSE") in result.failed

    @patch('app.services.market_data.yahoo.yf')
    def test_batch_fetch_empty_list(self, mock_yf):
        """Should handle empty request list."""
        provider = YahooFinanceProvider()
        result = provider.get_asset_info_batch([])

        assert result.success_count == 0
        assert result.failure_count == 0
        mock_yf.Tickers.assert_not_called()

    @patch('app.services.market_data.yahoo.yf')
    def test_batch_fetch_deduplicates(self, mock_yf):
        """Should deduplicate repeated tickers."""
        mock_tickers = MagicMock()
        mock_tickers.tickers = {
            "AAPL": MagicMock(info={
                "quoteType": "EQUITY",
                "shortName": "Apple",
                "currency": "USD",
                "regularMarketPrice": 150.0,
            }),
        }
        mock_yf.Tickers.return_value = mock_tickers

        provider = YahooFinanceProvider()
        result = provider.get_asset_info_batch([
            ("AAPL", "NASDAQ"),
            ("aapl", "nasdaq"),  # Duplicate (case-insensitive)
            ("AAPL", "NASDAQ"),  # Exact duplicate
        ])

        # Should only process once
        assert result.success_count == 1


# =============================================================================
# HEALTH CHECK TESTS
# =============================================================================

class TestIsAvailable:
    """Tests for is_available health check."""

    @patch('app.services.market_data.yahoo.yf')
    def test_available_when_aapl_responds(self, mock_yf):
        """Should return True when AAPL check succeeds."""
        mock_ticker = MagicMock()
        mock_ticker.info = {"symbol": "AAPL"}
        mock_yf.Ticker.return_value = mock_ticker

        provider = YahooFinanceProvider()
        assert provider.is_available() is True
