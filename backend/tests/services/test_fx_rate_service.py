# backend/tests/services/test_fx_rate_service.py
"""
Tests for the FXRateService.

This module tests:
- Rate syncing from market data provider
- Rate retrieval (exact and fallback)
- Required pairs detection
- Coverage reporting
- Error handling

Note: Tests mock the MarketDataProvider interface, not yfinance directly.
This ensures proper test isolation and makes tests provider-agnostic.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.models import (
    ExchangeRate,
    Portfolio,
    Asset,
    Transaction,
    TransactionType,
)
from app.services.exceptions import (
    FXRateNotFoundError,
)
from app.services.fx_rate_service import (
    FXRateService,
)
from app.services.market_data.base import (
    MarketDataProvider,
    HistoricalPricesResult,
    OHLCVData,
)
from tests.conftest import create_user, create_portfolio, create_asset


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_provider() -> MagicMock:
    """Create a mock MarketDataProvider for testing."""
    provider = MagicMock(spec=MarketDataProvider)
    provider.name = "mock_provider"
    return provider


@pytest.fixture
def fx_service(mock_provider) -> FXRateService:
    """Create FXRateService instance with mock provider for testing."""
    return FXRateService(provider=mock_provider, max_fallback_days=7)


@pytest.fixture
def sample_rates(db) -> list[ExchangeRate]:
    """Create sample exchange rates in database."""
    rates = [
        ExchangeRate(
            base_currency="USD",
            quote_currency="EUR",
            date=datetime(2024, 1, 15, tzinfo=timezone.utc),
            rate=Decimal("0.92000000"),
            provider="yahoo",
        ),
        ExchangeRate(
            base_currency="USD",
            quote_currency="EUR",
            date=datetime(2024, 1, 16, tzinfo=timezone.utc),
            rate=Decimal("0.92500000"),
            provider="yahoo",
        ),
        ExchangeRate(
            base_currency="USD",
            quote_currency="EUR",
            date=datetime(2024, 1, 17, tzinfo=timezone.utc),
            rate=Decimal("0.93000000"),
            provider="yahoo",
        ),
        ExchangeRate(
            base_currency="GBP",
            quote_currency="EUR",
            date=datetime(2024, 1, 15, tzinfo=timezone.utc),
            rate=Decimal("1.17000000"),
            provider="yahoo",
        ),
    ]

    for rate in rates:
        db.add(rate)
    db.commit()

    return rates


def create_transaction_helper(
        db,
        portfolio: Portfolio,
        asset: Asset,
        transaction_type: TransactionType = TransactionType.BUY,
        quantity: Decimal = Decimal("10"),
        price: Decimal = Decimal("100"),
) -> Transaction:
    """Helper to create a transaction."""
    txn = Transaction(
        portfolio_id=portfolio.id,
        asset_id=asset.id,
        transaction_type=transaction_type,
        date=datetime.now(timezone.utc),
        quantity=quantity,
        price_per_share=price,
        currency=asset.currency,
        fee=Decimal("0"),
        fee_currency=asset.currency,
        exchange_rate=Decimal("1"),
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


# =============================================================================
# INITIALIZATION TESTS
# =============================================================================

class TestFXRateServiceInit:
    """Tests for service initialization."""

    def test_init_with_defaults(self, mock_provider):
        """Service should initialize with default settings."""
        service = FXRateService(provider=mock_provider)
        assert service._max_fallback_days == FXRateService.MAX_FALLBACK_DAYS
        assert service._provider == mock_provider

    def test_init_with_custom_fallback_days(self, mock_provider):
        """Service should accept custom fallback days."""
        service = FXRateService(provider=mock_provider, max_fallback_days=14)
        assert service._max_fallback_days == 14

    def test_init_stores_provider(self, mock_provider):
        """Service should store the injected provider."""
        service = FXRateService(provider=mock_provider)
        assert service._provider is mock_provider
        assert service._provider.name == "mock_provider"


# =============================================================================
# GET RATE TESTS
# =============================================================================

class TestGetRate:
    """Tests for get_rate method."""

    def test_get_rate_exact_match(self, db, fx_service, sample_rates):
        """Should return rate for exact date."""
        result = fx_service.get_rate(db, "USD", "EUR", date(2024, 1, 15))

        assert result.rate == Decimal("0.92000000")
        assert result.is_exact_match is True
        assert result.base_currency == "USD"
        assert result.quote_currency == "EUR"

    def test_get_rate_case_insensitive(self, db, fx_service, sample_rates):
        """Should handle case-insensitive currency codes."""
        result = fx_service.get_rate(db, "usd", "eur", date(2024, 1, 15))

        assert result.rate == Decimal("0.92000000")

    def test_get_rate_same_currency(self, db, fx_service):
        """Should return 1.0 for same currency."""
        result = fx_service.get_rate(db, "EUR", "EUR", date(2024, 1, 15))

        assert result.rate == Decimal("1")
        assert result.is_exact_match is True

    def test_get_rate_with_fallback(self, db, fx_service, sample_rates):
        """Should use fallback when exact date not found."""
        # Jan 18 doesn't exist, should fall back to Jan 17
        result = fx_service.get_rate(db, "USD", "EUR", date(2024, 1, 18))

        assert result.rate == Decimal("0.93000000")
        assert result.is_exact_match is False
        assert result.actual_date == date(2024, 1, 17)

    def test_get_rate_fallback_respects_limit(self, db, mock_provider, sample_rates):
        """Should not fallback beyond max_fallback_days."""
        service = FXRateService(provider=mock_provider, max_fallback_days=1)

        # Jan 19 is 2 days after Jan 17, beyond 1-day fallback
        with pytest.raises(FXRateNotFoundError) as exc_info:
            service.get_rate(db, "USD", "EUR", date(2024, 1, 19))

        assert exc_info.value.base_currency == "USD"
        assert exc_info.value.quote_currency == "EUR"

    def test_get_rate_no_fallback_when_disabled(self, db, fx_service, sample_rates):
        """Should not use fallback when disabled."""
        with pytest.raises(FXRateNotFoundError):
            fx_service.get_rate(db, "USD", "EUR", date(2024, 1, 18), allow_fallback=False)

    def test_get_rate_not_found(self, db, fx_service):
        """Should raise FXRateNotFoundError when no rate exists."""
        with pytest.raises(FXRateNotFoundError) as exc_info:
            fx_service.get_rate(db, "USD", "EUR", date(2020, 1, 1))

        assert "USD/EUR" in str(exc_info.value)


class TestGetRateOrNone:
    """Tests for get_rate_or_none method."""

    def test_returns_rate_when_found(self, db, fx_service, sample_rates):
        """Should return rate result when found."""
        result = fx_service.get_rate_or_none(db, "USD", "EUR", date(2024, 1, 15))

        assert result is not None
        assert result.rate == Decimal("0.92000000")

    def test_returns_none_when_not_found(self, db, fx_service):
        """Should return None when rate not found."""
        result = fx_service.get_rate_or_none(db, "USD", "EUR", date(2020, 1, 1))

        assert result is None


# =============================================================================
# REQUIRED PAIRS TESTS
# =============================================================================

class TestGetRequiredPairs:
    """Tests for get_required_pairs method."""

    def test_detect_single_pair(self, db, fx_service):
        """Should detect single required FX pair."""
        user = create_user(db)
        portfolio = create_portfolio(db, user, currency="EUR")
        asset = create_asset(db, ticker="AAPL", exchange="NASDAQ", currency="USD")
        create_transaction_helper(db, portfolio, asset)

        pairs = fx_service.get_required_pairs(db, portfolio.id)

        assert len(pairs) == 1
        assert ("USD", "EUR") in pairs

    def test_detect_multiple_pairs(self, db, fx_service):
        """Should detect multiple required FX pairs."""
        user = create_user(db, email="multi@test.com")
        portfolio = create_portfolio(db, user, currency="EUR")

        # Create assets in different currencies
        asset_usd = create_asset(db, ticker="AAPL", exchange="NASDAQ", currency="USD")
        asset_gbp = create_asset(db, ticker="HSBA", exchange="LSE", currency="GBP")

        create_transaction_helper(db, portfolio, asset_usd)
        create_transaction_helper(db, portfolio, asset_gbp)

        pairs = fx_service.get_required_pairs(db, portfolio.id)

        assert len(pairs) == 2
        assert ("USD", "EUR") in pairs
        assert ("GBP", "EUR") in pairs

    def test_no_pair_for_same_currency(self, db, fx_service):
        """Should not include pair when asset currency matches portfolio."""
        user = create_user(db, email="same@test.com")
        portfolio = create_portfolio(db, user, currency="EUR")
        asset = create_asset(db, ticker="SAP", exchange="XETRA", currency="EUR")
        create_transaction_helper(db, portfolio, asset)

        pairs = fx_service.get_required_pairs(db, portfolio.id)

        assert len(pairs) == 0

    def test_empty_for_nonexistent_portfolio(self, db, fx_service):
        """Should return empty list for non-existent portfolio."""
        pairs = fx_service.get_required_pairs(db, 99999)

        assert pairs == []


# =============================================================================
# SYNC RATES TESTS (with mocked MarketDataProvider)
# =============================================================================

def create_mock_ohlcv_data(dates_and_rates: list[tuple[date, Decimal]]) -> list[OHLCVData]:
    """Helper to create mock OHLCV data from date/rate pairs."""
    return [
        OHLCVData(
            date=d,
            open=rate,
            high=rate,
            low=rate,
            close=rate,
            volume=1000,
        )
        for d, rate in dates_and_rates
    ]


class TestSyncRates:
    """Tests for sync_rates method."""

    def test_sync_rates_success(self, db, fx_service, mock_provider):
        """Should fetch and store rates successfully."""
        # Setup mock provider to return OHLCV data
        mock_prices = create_mock_ohlcv_data([
            (date(2024, 1, 15), Decimal("0.92")),
            (date(2024, 1, 16), Decimal("0.925")),
            (date(2024, 1, 17), Decimal("0.93")),
        ])
        mock_provider.get_historical_prices.return_value = HistoricalPricesResult(
            ticker="USDEUR=X",
            exchange="",
            prices=mock_prices,
            success=True,
        )

        result = fx_service.sync_rates(
            db, "USD", "EUR",
            date(2024, 1, 15), date(2024, 1, 17)
        )

        assert result.success is True
        assert result.rates_fetched == 3
        assert result.base_currency == "USD"
        assert result.quote_currency == "EUR"

        # Verify rates were stored
        stored = db.scalars(
            select(ExchangeRate).where(
                ExchangeRate.base_currency == "USD",
                ExchangeRate.quote_currency == "EUR",
            )
        ).all()
        assert len(stored) == 3

        # Verify provider was called correctly
        mock_provider.get_historical_prices.assert_called_once_with(
            ticker="USDEUR=X",
            exchange="",
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 17),
        )

    def test_sync_rates_incremental(self, db, fx_service, mock_provider, sample_rates):
        """Should only fetch missing dates when not forced."""
        # Setup mock to return only Jan 18 data
        mock_prices = create_mock_ohlcv_data([
            (date(2024, 1, 18), Decimal("0.94")),
        ])
        mock_provider.get_historical_prices.return_value = HistoricalPricesResult(
            ticker="USDEUR=X",
            exchange="",
            prices=mock_prices,
            success=True,
        )

        result = fx_service.sync_rates(
            db, "USD", "EUR",
            date(2024, 1, 15), date(2024, 1, 18),
            force=False
        )

        # Should only fetch Jan 18 (Jan 15-17 already exist)
        assert result.rates_fetched == 1

    def test_sync_rates_same_currency_skipped(self, db, fx_service, mock_provider):
        """Should skip sync for same currency."""
        result = fx_service.sync_rates(
            db, "EUR", "EUR",
            date(2024, 1, 15), date(2024, 1, 17)
        )

        assert result.rates_fetched == 0
        # Provider should not be called for same currency
        mock_provider.get_historical_prices.assert_not_called()

    def test_sync_rates_handles_provider_error(self, db, fx_service, mock_provider):
        """Should handle provider errors gracefully."""
        mock_provider.get_historical_prices.side_effect = Exception("Network error")

        result = fx_service.sync_rates(
            db, "USD", "EUR",
            date(2024, 1, 15), date(2024, 1, 17)
        )

        assert result.success is False
        assert len(result.errors) > 0

    def test_sync_rates_handles_empty_response(self, db, fx_service, mock_provider):
        """Should handle empty response from provider."""
        mock_provider.get_historical_prices.return_value = HistoricalPricesResult(
            ticker="USDEUR=X",
            exchange="",
            prices=[],
            success=True,
        )

        result = fx_service.sync_rates(
            db, "USD", "EUR",
            date(2024, 1, 15), date(2024, 1, 17)
        )

        assert result.success is False
        assert "No rates returned" in result.errors[0]

    def test_sync_rates_handles_failed_response(self, db, fx_service, mock_provider):
        """Should handle failed response from provider."""
        mock_provider.get_historical_prices.return_value = HistoricalPricesResult(
            ticker="USDEUR=X",
            exchange="",
            prices=[],
            success=False,
            error="Symbol not found",
        )

        result = fx_service.sync_rates(
            db, "USD", "EUR",
            date(2024, 1, 15), date(2024, 1, 17)
        )

        assert result.success is False


# =============================================================================
# COVERAGE TESTS
# =============================================================================

class TestGetCoverage:
    """Tests for get_coverage method."""

    def test_coverage_with_data(self, db, fx_service, sample_rates):
        """Should return coverage info for existing data."""
        coverage = fx_service.get_coverage(db, "USD", "EUR")

        assert coverage["base_currency"] == "USD"
        assert coverage["quote_currency"] == "EUR"
        assert coverage["total_days"] == 3  # 3 USD/EUR rates in sample

    def test_coverage_same_currency(self, db, fx_service):
        """Should indicate same currency needs no rates."""
        coverage = fx_service.get_coverage(db, "EUR", "EUR")

        assert coverage["total_days"] == 0
        assert "Same currency" in coverage.get("note", "")

    def test_coverage_no_data(self, db, fx_service):
        """Should return empty coverage for missing pair."""
        coverage = fx_service.get_coverage(db, "CHF", "EUR")

        assert coverage["total_days"] == 0
        assert coverage["from_date"] is None


# =============================================================================
# SYNC PORTFOLIO RATES TESTS
# =============================================================================

class TestSyncPortfolioRates:
    """Tests for sync_portfolio_rates method."""

    def test_syncs_all_required_pairs(self, db, fx_service, mock_provider):
        """Should sync rates for all required currency pairs."""
        # Setup portfolio with multiple currencies
        user = create_user(db, email="portfolio_sync@test.com")
        portfolio = create_portfolio(db, user, currency="EUR")

        asset_usd = create_asset(db, ticker="MSFT", exchange="NASDAQ", currency="USD")
        asset_gbp = create_asset(db, ticker="BP", exchange="LSE", currency="GBP")

        create_transaction_helper(db, portfolio, asset_usd)
        create_transaction_helper(db, portfolio, asset_gbp)

        # Setup mock provider to return data for any FX pair
        mock_prices = create_mock_ohlcv_data([
            (date(2024, 1, 15), Decimal("0.92")),
        ])
        mock_provider.get_historical_prices.return_value = HistoricalPricesResult(
            ticker="USDEUR=X",
            exchange="",
            prices=mock_prices,
            success=True,
        )

        results = fx_service.sync_portfolio_rates(
            db, portfolio.id,
            date(2024, 1, 15), date(2024, 1, 15)
        )

        # Should have synced 2 pairs: USD/EUR and GBP/EUR
        assert len(results) == 2

        # Verify provider was called twice (once for each pair)
        assert mock_provider.get_historical_prices.call_count == 2


# =============================================================================
# UTILITY METHOD TESTS
# =============================================================================

class TestUtilityMethods:
    """Tests for utility methods."""

    def test_build_yahoo_symbol(self):
        """Should build correct Yahoo Finance symbol."""
        symbol = FXRateService.build_yahoo_symbol("USD", "EUR")
        assert symbol == "USDEUR=X"

    def test_build_yahoo_symbol_case_insensitive(self):
        """Should uppercase currency codes."""
        symbol = FXRateService.build_yahoo_symbol("usd", "eur")
        assert symbol == "USDEUR=X"

    def test_invert_rate(self):
        """Should correctly invert exchange rate."""
        rate = Decimal("0.92")
        inverted = FXRateService.invert_rate(rate)

        # 1/0.92 ≈ 1.0869565
        assert inverted == Decimal("1.08695652")

    def test_invert_rate_zero_raises(self):
        """Should raise error for zero rate."""
        with pytest.raises(ValueError):
            FXRateService.invert_rate(Decimal("0"))

    def test_get_business_days(self):
        """Should return only weekdays."""
        # Jan 15, 2024 is Monday, Jan 21 is Sunday
        days = FXRateService._get_business_days(date(2024, 1, 15), date(2024, 1, 21))

        # Should have Mon-Fri = 5 days
        assert len(days) == 5

        # Should not include weekend
        for d in days:
            assert d.weekday() < 5  # Monday=0, Friday=4


# =============================================================================
# CONVERSION HELPER TESTS
# =============================================================================

class TestConversionHelpers:
    """Tests for currency conversion helper methods."""

    def test_convert_to_quote_currency(self, db, fx_service, sample_rates):
        """Should convert base currency to quote currency."""
        # Get USD/EUR rate (0.92)
        rate_result = fx_service.get_rate(db, "USD", "EUR", date(2024, 1, 15))

        # Convert 100 USD to EUR
        result = fx_service.convert_to_quote_currency(Decimal("100"), rate_result)

        # 100 USD × 0.92 = 92 EUR
        assert result == Decimal("92.00")

    def test_convert_to_base_currency(self, db, fx_service, sample_rates):
        """Should convert quote currency to base currency."""
        # Get USD/EUR rate (0.92)
        rate_result = fx_service.get_rate(db, "USD", "EUR", date(2024, 1, 15))

        # Convert 92 EUR to USD
        result = fx_service.convert_to_base_currency(Decimal("92"), rate_result)

        # 92 EUR ÷ 0.92 = 100 USD
        assert result == Decimal("100.00")

    def test_convert_amount_direct_rate(self, db, fx_service, sample_rates):
        """Should convert using direct rate when available."""
        # Convert 100 USD to EUR (we have USD/EUR rate)
        result, rate = fx_service.convert_amount(
            db, Decimal("100"), "USD", "EUR", date(2024, 1, 15)
        )

        assert result == Decimal("92.00")
        assert rate.base_currency == "USD"
        assert rate.quote_currency == "EUR"

    def test_convert_amount_inverse_rate(self, db, fx_service, sample_rates):
        """Should convert using inverse rate when direct not available."""
        # Convert 92 EUR to USD (we have USD/EUR, not EUR/USD)
        result, rate = fx_service.convert_amount(
            db, Decimal("92"), "EUR", "USD", date(2024, 1, 15)
        )

        # Should get ~100 USD (92 ÷ 0.92)
        assert result == Decimal("100.00")
        # Rate result should be "normalized" to EUR/USD direction
        assert rate.base_currency == "EUR"
        assert rate.quote_currency == "USD"

    def test_convert_amount_same_currency(self, db, fx_service):
        """Should return same amount for same currency."""
        result, rate = fx_service.convert_amount(
            db, Decimal("100"), "EUR", "EUR", date(2024, 1, 15)
        )

        assert result == Decimal("100")
        assert rate.rate == Decimal("1")

    def test_convert_amount_not_found(self, db, fx_service):
        """Should raise error when no rate in either direction."""
        with pytest.raises(FXRateNotFoundError):
            fx_service.convert_amount(
                db, Decimal("100"), "CHF", "JPY", date(2024, 1, 15)
            )
