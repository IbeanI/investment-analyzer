# backend/tests/services/test_yahoo_historical_prices.py
"""
Tests for YahooFinanceProvider historical price fetching.

This module tests:
- get_historical_prices() method
- OHLCV data parsing
- Error handling for invalid tickers
- Date range handling
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from app.services.exceptions import (
    TickerNotFoundError,
    ProviderUnavailableError,
)
from app.services.market_data.base import OHLCVData, HistoricalPricesResult
from app.services.market_data.yahoo import YahooFinanceProvider


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def provider():
    """Create YahooFinanceProvider instance."""
    return YahooFinanceProvider(timeout=10)


@pytest.fixture
def sample_dataframe():
    """Create sample DataFrame like yfinance returns."""
    dates = pd.date_range(start='2024-01-15', periods=5, freq='B')  # Business days
    return pd.DataFrame({
        'Open': [185.0, 186.0, 184.5, 187.0, 188.0],
        'High': [187.0, 188.0, 186.0, 189.0, 190.0],
        'Low': [184.0, 185.0, 183.5, 186.0, 187.0],
        'Close': [186.0, 185.5, 185.0, 188.0, 189.5],
        'Volume': [1000000, 1100000, 900000, 1200000, 1150000],
        'Adj Close': [186.0, 185.5, 185.0, 188.0, 189.5],
    }, index=dates)


# =============================================================================
# OHLCV DATA TESTS
# =============================================================================

class TestOHLCVData:
    """Tests for OHLCVData dataclass."""

    def test_valid_ohlcv(self):
        """Should create valid OHLCV data."""
        ohlcv = OHLCVData(
            date=date(2024, 1, 15),
            open=Decimal("185.00"),
            high=Decimal("187.00"),
            low=Decimal("184.00"),
            close=Decimal("186.00"),
            volume=1000000,
        )

        assert ohlcv.close == Decimal("186.00")
        assert ohlcv.volume == 1000000

    def test_invalid_close_price(self):
        """Should reject zero or negative close price."""
        with pytest.raises(ValueError, match="close price must be positive"):
            OHLCVData(
                date=date(2024, 1, 15),
                open=Decimal("185.00"),
                high=Decimal("187.00"),
                low=Decimal("184.00"),
                close=Decimal("0"),
            )

    def test_invalid_high_low(self):
        """Should reject high < low."""
        with pytest.raises(ValueError, match="high.*cannot be less than low"):
            OHLCVData(
                date=date(2024, 1, 15),
                open=Decimal("185.00"),
                high=Decimal("180.00"),  # Less than low
                low=Decimal("184.00"),
                close=Decimal("186.00"),
            )


# =============================================================================
# DATAFRAME PARSING TESTS
# =============================================================================

class TestDataframeParsing:
    """Tests for DataFrame to OHLCV conversion."""

    def test_parse_valid_dataframe(self, provider, sample_dataframe):
        """Should correctly parse valid DataFrame."""
        prices = provider._dataframe_to_ohlcv(sample_dataframe)

        assert len(prices) == 5
        assert prices[0].date == date(2024, 1, 15)
        assert prices[0].open == Decimal("185.00000000")
        assert prices[0].close == Decimal("186.00000000")
        assert prices[0].volume == 1000000

    def test_parse_dataframe_with_nan(self, provider):
        """Should handle NaN values in DataFrame."""
        dates = pd.date_range(start='2024-01-15', periods=3, freq='B')
        df = pd.DataFrame({
            'Open': [185.0, np.nan, 187.0],
            'High': [187.0, 188.0, 189.0],
            'Low': [184.0, 185.0, 186.0],
            'Close': [186.0, 187.5, 188.0],
            'Volume': [1000000, np.nan, 1200000],
            'Adj Close': [186.0, 187.5, 188.0],
        }, index=dates)

        prices = provider._dataframe_to_ohlcv(df)

        assert len(prices) == 3
        # NaN open should fall back to close
        assert prices[1].open == prices[1].close
        # NaN volume should be None
        assert prices[1].volume is None

    def test_parse_dataframe_missing_close(self, provider):
        """Should skip rows with missing close price."""
        dates = pd.date_range(start='2024-01-15', periods=3, freq='B')
        df = pd.DataFrame({
            'Open': [185.0, 186.0, 187.0],
            'High': [187.0, 188.0, 189.0],
            'Low': [184.0, 185.0, 186.0],
            'Close': [186.0, np.nan, 188.0],  # Missing close
            'Volume': [1000000, 1100000, 1200000],
            'Adj Close': [186.0, np.nan, 188.0],
        }, index=dates)

        prices = provider._dataframe_to_ohlcv(df)

        # Should skip the row with missing close
        assert len(prices) == 2


# =============================================================================
# HISTORICAL PRICES TESTS (with mocked yfinance)
# =============================================================================

class TestGetHistoricalPrices:
    """Tests for get_historical_prices method."""

    @patch('app.services.market_data.yahoo.yf')
    def test_successful_fetch(self, mock_yf, provider, sample_dataframe):
        """Should return prices on successful fetch."""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = sample_dataframe
        mock_ticker.info = {"regularMarketPrice": 189.0}
        mock_yf.Ticker.return_value = mock_ticker

        result = provider.get_historical_prices(
            "AAPL", "NASDAQ",
            date(2024, 1, 15), date(2024, 1, 19)
        )

        assert result.success is True
        assert result.ticker == "AAPL"
        assert result.exchange == "NASDAQ"
        assert len(result.prices) == 5
        assert result.days_fetched == 5

    @patch('app.services.market_data.yahoo.yf')
    def test_empty_dataframe_valid_ticker(self, mock_yf, provider):
        """Should handle empty DataFrame for valid ticker (no data in range)."""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_ticker.info = {"regularMarketPrice": 189.0, "shortName": "Apple"}
        mock_yf.Ticker.return_value = mock_ticker

        result = provider.get_historical_prices(
            "AAPL", "NASDAQ",
            date(2020, 1, 1), date(2020, 1, 5)
        )

        # Should succeed but with no prices
        assert result.success is True
        assert len(result.prices) == 0

    @patch('app.services.market_data.yahoo.yf')
    def test_invalid_ticker(self, mock_yf, provider):
        """Should raise TickerNotFoundError for invalid ticker."""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_ticker.info = {}  # Empty info = invalid ticker
        mock_yf.Ticker.return_value = mock_ticker

        with pytest.raises(TickerNotFoundError) as exc_info:
            provider.get_historical_prices(
                "INVALID", "NYSE",
                date(2024, 1, 1), date(2024, 1, 5)
            )

        assert exc_info.value.ticker == "INVALID"
        assert exc_info.value.exchange == "NYSE"

    @patch('app.services.market_data.yahoo.yf')
    def test_network_error(self, mock_yf, provider):
        """Should raise ProviderUnavailableError on network error."""
        mock_yf.Ticker.side_effect = Exception("Connection timeout")

        with pytest.raises(ProviderUnavailableError) as exc_info:
            provider.get_historical_prices(
                "AAPL", "NASDAQ",
                date(2024, 1, 1), date(2024, 1, 5)
            )

        assert exc_info.value.provider == "yahoo"

    @patch('app.services.market_data.yahoo.yf')
    def test_exchange_suffix_applied(self, mock_yf, provider, sample_dataframe):
        """Should apply correct exchange suffix."""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = sample_dataframe
        mock_ticker.info = {"regularMarketPrice": 175.0}
        mock_yf.Ticker.return_value = mock_ticker

        provider.get_historical_prices(
            "SAP", "XETRA",
            date(2024, 1, 15), date(2024, 1, 19)
        )

        # Should have called with SAP.DE (XETRA suffix)
        mock_yf.Ticker.assert_called_with("SAP.DE")

    @patch('app.services.market_data.yahoo.yf')
    def test_date_range_inclusive(self, mock_yf, provider, sample_dataframe):
        """Should request inclusive date range from Yahoo."""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = sample_dataframe
        mock_ticker.info = {"regularMarketPrice": 189.0}
        mock_yf.Ticker.return_value = mock_ticker

        provider.get_historical_prices(
            "AAPL", "NASDAQ",
            date(2024, 1, 15), date(2024, 1, 19)
        )

        # Yahoo end date should be +1 day for inclusive range
        call_args = mock_ticker.history.call_args
        assert call_args.kwargs['end'] == "2024-01-20"


# =============================================================================
# HISTORICAL PRICES RESULT TESTS
# =============================================================================

class TestHistoricalPricesResult:
    """Tests for HistoricalPricesResult dataclass."""

    def test_days_fetched(self):
        """Should correctly count days fetched."""
        prices = [
            OHLCVData(date=date(2024, 1, 15), open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("100")),
            OHLCVData(date=date(2024, 1, 16), open=Decimal("100"), high=Decimal("102"), low=Decimal("99"), close=Decimal("101")),
        ]

        result = HistoricalPricesResult(
            ticker="AAPL",
            exchange="NASDAQ",
            prices=prices,
            success=True,
        )

        assert result.days_fetched == 2

    def test_actual_dates_set_automatically(self):
        """Should set actual date range from prices."""
        prices = [
            OHLCVData(date=date(2024, 1, 15), open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("100")),
            OHLCVData(date=date(2024, 1, 18), open=Decimal("100"), high=Decimal("102"), low=Decimal("99"), close=Decimal("101")),
        ]

        result = HistoricalPricesResult(
            ticker="AAPL",
            exchange="NASDAQ",
            prices=prices,
            success=True,
        )

        assert result.actual_from_date == date(2024, 1, 15)
        assert result.actual_to_date == date(2024, 1, 18)

    def test_failed_result(self):
        """Should handle failed result correctly."""
        result = HistoricalPricesResult(
            ticker="INVALID",
            exchange="NYSE",
            success=False,
            error="Ticker not found",
        )

        assert result.success is False
        assert result.days_fetched == 0
        assert result.error == "Ticker not found"
