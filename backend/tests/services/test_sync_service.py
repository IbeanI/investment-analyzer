# backend/tests/services/test_sync_service.py
"""
Tests for the MarketDataSyncService.

This module tests:
- Portfolio analysis
- Price syncing with mocked Yahoo provider
- Staleness detection
- Partial success handling
- Status management
"""

from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.models import (
    Transaction,
    TransactionType,
    MarketData,
    SyncStatus,
    SyncStatusEnum,
)
from app.services.fx_rate_service import FXRateService, FXSyncResult
from app.services.market_data.base import (
    OHLCVData,
    HistoricalPricesResult,
)
from app.services.market_data.sync_service import (
    MarketDataSyncService,
)
from tests.conftest import create_user, create_portfolio, create_asset


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_fx_service():
    """Create a mock FX service."""
    service = MagicMock(spec=FXRateService)
    service.sync_portfolio_rates.return_value = []
    service.get_coverage.return_value = {
        "from_date": date(2024, 1, 1),
        "to_date": date(2024, 12, 31),
        "total_days": 250,
    }
    return service


@pytest.fixture
def mock_provider_and_service(mock_fx_service):
    """
    Create both mock provider AND sync service together.

    This ensures the test gets the SAME mock_provider instance
    that the sync_service uses.
    """
    mock_provider = MagicMock()
    mock_provider.name = "mock"

    sync_service = MarketDataSyncService(
        provider=mock_provider,
        fx_service=mock_fx_service,
        staleness_threshold_hours=24,
    )

    return mock_provider, sync_service


@pytest.fixture
def sync_service(mock_provider_and_service):
    """Get sync service from the combined fixture."""
    _, service = mock_provider_and_service
    return service


@pytest.fixture
def portfolio_with_transactions(db):
    """Create a portfolio with transactions for testing."""
    user = create_user(db, email="sync_test@example.com")
    portfolio = create_portfolio(db, user, name="Test Portfolio", currency="EUR")

    # Create assets
    asset_usd = create_asset(
        db, ticker="AAPL", exchange="NASDAQ",
        currency="USD", name="Apple Inc."
    )
    asset_eur = create_asset(
        db, ticker="SAP", exchange="XETRA",
        currency="EUR", name="SAP SE"
    )

    # Create transactions
    txn1 = Transaction(
        portfolio_id=portfolio.id,
        asset_id=asset_usd.id,
        transaction_type=TransactionType.BUY,
        date=datetime(2024, 1, 15, tzinfo=timezone.utc),
        quantity=Decimal("10"),
        price_per_share=Decimal("185.00"),
        currency="USD",
        fee=Decimal("0"),
        fee_currency="USD",
        exchange_rate=Decimal("1.08"),
    )

    txn2 = Transaction(
        portfolio_id=portfolio.id,
        asset_id=asset_eur.id,
        transaction_type=TransactionType.BUY,
        date=datetime(2024, 3, 1, tzinfo=timezone.utc),
        quantity=Decimal("5"),
        price_per_share=Decimal("175.00"),
        currency="EUR",
        fee=Decimal("0"),
        fee_currency="EUR",
        exchange_rate=Decimal("1"),
    )

    db.add_all([txn1, txn2])
    db.commit()

    return {
        "portfolio": portfolio,
        "assets": [asset_usd, asset_eur],
        "transactions": [txn1, txn2],
    }


def create_ohlcv_data(
        start_date: date,
        num_days: int = 5,
        base_price: float = 100.0,
) -> list[OHLCVData]:
    """Create sample OHLCV data for testing."""
    prices = []
    current_date = start_date
    price = base_price

    for i in range(num_days):
        # Skip weekends
        while current_date.weekday() >= 5:
            current_date += timedelta(days=1)

        prices.append(OHLCVData(
            date=current_date,
            open=Decimal(str(price)),
            high=Decimal(str(price * 1.02)),
            low=Decimal(str(price * 0.98)),
            close=Decimal(str(price * 1.01)),
            volume=1000000,
            adjusted_close=Decimal(str(price * 1.01)),
        ))

        price *= 1.005  # Small daily change
        current_date += timedelta(days=1)

    return prices


# =============================================================================
# INITIALIZATION TESTS
# =============================================================================

class TestSyncServiceInit:
    """Tests for service initialization."""

    def test_init_with_defaults(self):
        """Service should initialize with default dependencies."""
        service = MarketDataSyncService()
        assert service._provider.name == "yahoo"
        assert service._staleness_threshold_hours == 24

    def test_init_with_custom_threshold(self, mock_fx_service):
        """Service should accept custom staleness threshold."""
        mock_provider = MagicMock()
        mock_provider.name = "mock"

        service = MarketDataSyncService(
            provider=mock_provider,
            fx_service=mock_fx_service,
            staleness_threshold_hours=48,
        )
        assert service._staleness_threshold_hours == 48


# =============================================================================
# PORTFOLIO ANALYSIS TESTS
# =============================================================================

class TestAnalyzePortfolio:
    """Tests for analyze_portfolio method."""

    def test_analyze_empty_portfolio(self, db, sync_service):
        """Should handle portfolio with no transactions."""
        user = create_user(db, email="empty@example.com")
        portfolio = create_portfolio(db, user, name="Empty", currency="EUR")

        analysis = sync_service.analyze_portfolio(db, portfolio.id)

        assert analysis.portfolio_id == portfolio.id
        assert analysis.portfolio_currency == "EUR"
        assert len(analysis.assets) == 0
        assert analysis.earliest_date is None

    def test_analyze_portfolio_with_transactions(
            self, db, sync_service, portfolio_with_transactions
    ):
        """Should correctly analyze portfolio assets and dates."""
        portfolio = portfolio_with_transactions["portfolio"]

        analysis = sync_service.analyze_portfolio(db, portfolio.id)

        assert analysis.portfolio_id == portfolio.id
        assert analysis.portfolio_currency == "EUR"
        assert len(analysis.assets) == 2

        # Check assets
        tickers = {a.ticker for a in analysis.assets}
        assert "AAPL" in tickers
        assert "SAP" in tickers

        # Check date range
        assert analysis.earliest_date == date(2024, 1, 15)
        assert analysis.latest_date == date.today()

        # Check FX pairs (USD→EUR needed, EUR→EUR not needed)
        assert ("USD", "EUR") in analysis.fx_pairs_needed
        assert len(analysis.fx_pairs_needed) == 1

    def test_analyze_nonexistent_portfolio(self, db, sync_service):
        """Should handle non-existent portfolio."""
        analysis = sync_service.analyze_portfolio(db, 99999)

        assert analysis.portfolio_id == 99999
        assert len(analysis.assets) == 0


# =============================================================================
# STALENESS TESTS
# =============================================================================

class TestIsDataStale:
    """Tests for is_data_stale method."""

    def test_never_synced(self, db, sync_service, portfolio_with_transactions):
        """Should report stale for never-synced portfolio."""
        portfolio = portfolio_with_transactions["portfolio"]

        is_stale, reason = sync_service.is_data_stale(db, portfolio.id)

        assert is_stale is True
        assert reason == "never_synced"

    def test_recently_synced(self, db, sync_service, portfolio_with_transactions):
        """Should report not stale for recently synced portfolio."""
        portfolio = portfolio_with_transactions["portfolio"]

        # Create sync status
        status = SyncStatus(
            portfolio_id=portfolio.id,
            status=SyncStatusEnum.COMPLETED,
            last_sync_started=datetime.now(timezone.utc) - timedelta(hours=2),
            last_sync_completed=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        db.add(status)
        db.commit()

        is_stale, reason = sync_service.is_data_stale(db, portfolio.id)

        assert is_stale is False
        assert "synced_2_hours_ago" in reason

    def test_stale_after_threshold(self, db, sync_service, portfolio_with_transactions):
        """Should report stale when threshold exceeded."""
        portfolio = portfolio_with_transactions["portfolio"]

        # Create old sync status
        status = SyncStatus(
            portfolio_id=portfolio.id,
            status=SyncStatusEnum.COMPLETED,
            last_sync_started=datetime.now(timezone.utc) - timedelta(hours=48),
            last_sync_completed=datetime.now(timezone.utc) - timedelta(hours=48),
        )
        db.add(status)
        db.commit()

        is_stale, reason = sync_service.is_data_stale(db, portfolio.id)

        assert is_stale is True
        assert "48_hours_ago" in reason

    def test_failed_sync_is_stale(self, db, sync_service, portfolio_with_transactions):
        """Should report stale when last sync failed."""
        portfolio = portfolio_with_transactions["portfolio"]

        status = SyncStatus(
            portfolio_id=portfolio.id,
            status=SyncStatusEnum.FAILED,
            last_sync_started=datetime.now(timezone.utc) - timedelta(hours=1),
            last_error="Network error",
        )
        db.add(status)
        db.commit()

        is_stale, reason = sync_service.is_data_stale(db, portfolio.id)

        assert is_stale is True
        assert reason == "last_sync_failed"

    def test_custom_threshold(self, db, sync_service, portfolio_with_transactions):
        """Should use custom threshold when provided."""
        portfolio = portfolio_with_transactions["portfolio"]

        status = SyncStatus(
            portfolio_id=portfolio.id,
            status=SyncStatusEnum.COMPLETED,
            last_sync_started=datetime.now(timezone.utc) - timedelta(hours=10),
            last_sync_completed=datetime.now(timezone.utc) - timedelta(hours=10),
        )
        db.add(status)
        db.commit()

        # With default 24h threshold, should not be stale
        is_stale, _ = sync_service.is_data_stale(db, portfolio.id)
        assert is_stale is False

        # With 8h threshold, should be stale
        is_stale, _ = sync_service.is_data_stale(db, portfolio.id, threshold_hours=8)
        assert is_stale is True


# =============================================================================
# SYNC PORTFOLIO TESTS
# =============================================================================

class TestSyncPortfolio:
    """Tests for sync_portfolio method."""

    def test_sync_empty_portfolio(self, db, sync_service):
        """Should handle empty portfolio gracefully."""
        user = create_user(db, email="sync_empty@example.com")
        portfolio = create_portfolio(db, user, name="Empty", currency="EUR")

        result = sync_service.sync_portfolio(db, portfolio.id)

        assert result.status == "completed"
        assert result.assets_synced == 0
        assert result.prices_fetched == 0

    def test_sync_successful(
            self, db, mock_provider_and_service, portfolio_with_transactions
    ):
        """Should sync all assets successfully."""
        # Get the SAME mock_provider that sync_service uses
        mock_provider, sync_service = mock_provider_and_service
        portfolio = portfolio_with_transactions["portfolio"]

        # Configure mock provider to return prices
        def mock_get_prices(ticker, exchange, start_date, end_date):
            return HistoricalPricesResult(
                ticker=ticker,
                exchange=exchange,
                prices=create_ohlcv_data(start_date, num_days=10),
                success=True,
                from_date=start_date,
                to_date=end_date,
            )

        mock_provider.get_historical_prices.side_effect = mock_get_prices

        result = sync_service.sync_portfolio(db, portfolio.id)

        assert result.status == "completed"
        assert result.assets_synced == 2
        assert result.assets_failed == 0
        assert result.prices_fetched > 0
        assert len(result.warnings) == 0

        # Verify sync status updated
        status = sync_service.get_sync_status(db, portfolio.id)
        assert status.status == SyncStatusEnum.COMPLETED
        assert status.last_sync_completed is not None

    def test_sync_partial_failure(
            self, db, mock_provider_and_service, portfolio_with_transactions
    ):
        """Should report partial success when some assets fail."""
        # Get the SAME mock_provider that sync_service uses
        mock_provider, sync_service = mock_provider_and_service
        portfolio = portfolio_with_transactions["portfolio"]

        # First asset succeeds, second fails
        call_count = [0]

        def mock_get_prices(ticker, exchange, start_date, end_date):
            call_count[0] += 1
            if call_count[0] == 1:
                return HistoricalPricesResult(
                    ticker=ticker,
                    exchange=exchange,
                    prices=create_ohlcv_data(start_date, num_days=5),
                    success=True,
                )
            else:
                return HistoricalPricesResult(
                    ticker=ticker,
                    exchange=exchange,
                    success=False,
                    error="Network error",
                )

        mock_provider.get_historical_prices.side_effect = mock_get_prices

        result = sync_service.sync_portfolio(db, portfolio.id)

        assert result.status == "partial"
        assert result.assets_synced == 1
        assert result.assets_failed == 1
        assert len(result.warnings) > 0

        # Verify sync status
        status = sync_service.get_sync_status(db, portfolio.id)
        assert status.status == SyncStatusEnum.PARTIAL

    def test_sync_complete_failure(
            self, db, mock_provider_and_service, portfolio_with_transactions
    ):
        """Should report failed when all assets fail."""
        mock_provider, sync_service = mock_provider_and_service
        portfolio = portfolio_with_transactions["portfolio"]

        # All assets fail
        mock_provider.get_historical_prices.return_value = HistoricalPricesResult(
            ticker="TEST",
            exchange="TEST",
            success=False,
            error="Network error",
        )

        result = sync_service.sync_portfolio(db, portfolio.id)

        assert result.status == "failed"
        assert result.assets_synced == 0
        assert result.assets_failed == 2

        # Verify sync status
        status = sync_service.get_sync_status(db, portfolio.id)
        assert status.status == SyncStatusEnum.FAILED

    def test_sync_with_fx_rates(
            self, db, mock_provider_and_service, mock_fx_service, portfolio_with_transactions
    ):
        """Should call FX service for required currency pairs."""
        mock_provider, sync_service = mock_provider_and_service
        portfolio = portfolio_with_transactions["portfolio"]

        mock_provider.get_historical_prices.return_value = HistoricalPricesResult(
            ticker="TEST",
            exchange="TEST",
            prices=create_ohlcv_data(date(2024, 1, 1), num_days=5),
            success=True,
        )

        mock_fx_service.sync_portfolio_rates.return_value = [
            FXSyncResult(
                base_currency="USD",
                quote_currency="EUR",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 12, 31),
                rates_fetched=250,
            )
        ]

        result = sync_service.sync_portfolio(db, portfolio.id)

        # Verify FX service was called
        mock_fx_service.sync_portfolio_rates.assert_called_once()
        assert result.fx_pairs_synced == 1

    def test_sync_incremental(
            self, db, mock_provider_and_service, portfolio_with_transactions
    ):
        """Should only fetch missing dates on incremental sync."""
        mock_provider, sync_service = mock_provider_and_service
        portfolio = portfolio_with_transactions["portfolio"]
        assets = portfolio_with_transactions["assets"]

        # Add some existing price data
        existing_price = MarketData(
            asset_id=assets[0].id,
            date=date(2024, 1, 15),
            open_price=Decimal("185.00"),
            high_price=Decimal("186.00"),
            low_price=Decimal("184.00"),
            close_price=Decimal("185.50"),
            volume=1000000,
            provider="yahoo",
        )
        db.add(existing_price)
        db.commit()

        mock_provider.get_historical_prices.return_value = HistoricalPricesResult(
            ticker="TEST",
            exchange="TEST",
            prices=create_ohlcv_data(date(2024, 1, 16), num_days=5),
            success=True,
        )

        result = sync_service.sync_portfolio(db, portfolio.id, force=False)

        assert result.status in ["completed", "partial"]
        # Provider should have been called with dates after existing data


# =============================================================================
# PRICE STORAGE TESTS
# =============================================================================

class TestPriceStorage:
    """Tests for price storage (upsert behavior)."""

    def test_prices_stored_correctly(
            self, db, mock_provider_and_service, portfolio_with_transactions
    ):
        """Should store OHLCV prices in database."""
        mock_provider, sync_service = mock_provider_and_service
        portfolio = portfolio_with_transactions["portfolio"]
        assets = portfolio_with_transactions["assets"]

        test_prices = [
            OHLCVData(
                date=date(2024, 6, 1),
                open=Decimal("190.00"),
                high=Decimal("195.00"),
                low=Decimal("188.00"),
                close=Decimal("193.00"),
                volume=5000000,
                adjusted_close=Decimal("193.00"),
            )
        ]

        mock_provider.get_historical_prices.return_value = HistoricalPricesResult(
            ticker="AAPL",
            exchange="NASDAQ",
            prices=test_prices,
            success=True,
        )

        sync_service.sync_portfolio(db, portfolio.id)

        # Verify price stored
        stored = db.scalar(
            select(MarketData).where(
                MarketData.asset_id == assets[0].id,
                MarketData.date == date(2024, 6, 1),
            )
        )

        assert stored is not None
        assert stored.open_price == Decimal("190.00")
        assert stored.high_price == Decimal("195.00")
        assert stored.low_price == Decimal("188.00")
        assert stored.close_price == Decimal("193.00")
        assert stored.volume == 5000000


# =============================================================================
# COVERAGE SUMMARY TESTS
# =============================================================================

class TestCoverageSummary:
    """Tests for coverage summary generation."""

    def test_coverage_summary_structure(
            self, db, mock_provider_and_service, mock_fx_service, portfolio_with_transactions
    ):
        """Should generate correct coverage summary structure."""
        mock_provider, sync_service = mock_provider_and_service
        portfolio = portfolio_with_transactions["portfolio"]

        mock_provider.get_historical_prices.return_value = HistoricalPricesResult(
            ticker="TEST",
            exchange="TEST",
            prices=create_ohlcv_data(date(2024, 1, 1), num_days=5),
            success=True,
        )

        result = sync_service.sync_portfolio(db, portfolio.id)

        summary = result.coverage_summary

        assert "sync_date" in summary
        assert "date_range" in summary
        assert "assets" in summary
        assert "fx_pairs" in summary

        assert summary["assets"]["total"] == 2
        assert len(summary["assets"]["details"]) == 2


# =============================================================================
# CONCURRENT SYNC PREVENTION TESTS
# =============================================================================

class TestConcurrentSyncPrevention:
    """Tests for preventing duplicate concurrent syncs (race condition fix)."""

    def test_sync_returns_already_running_when_in_progress(
            self, db, mock_provider_and_service, portfolio_with_transactions
    ):
        """Should return already_running status when sync is in progress."""
        mock_provider, sync_service = mock_provider_and_service
        portfolio = portfolio_with_transactions["portfolio"]

        # Manually set status to IN_PROGRESS to simulate concurrent sync
        from app.models import SyncStatus, SyncStatusEnum
        from datetime import datetime, timezone

        existing_status = SyncStatus(
            portfolio_id=portfolio.id,
            status=SyncStatusEnum.IN_PROGRESS,
            last_sync_started=datetime.now(timezone.utc),
            coverage_summary={},
        )
        db.add(existing_status)
        db.commit()

        # Now try to sync - should be blocked
        result = sync_service.sync_portfolio(db, portfolio.id)

        assert result.status == "already_running"
        assert len(result.warnings) > 0
        assert "already in progress" in result.warnings[0].lower()

    def test_sync_acquires_job_when_not_in_progress(
            self, db, mock_provider_and_service, portfolio_with_transactions
    ):
        """Should acquire job and sync when no sync is in progress."""
        mock_provider, sync_service = mock_provider_and_service
        portfolio = portfolio_with_transactions["portfolio"]

        # Set status to COMPLETED (not in progress)
        from app.models import SyncStatus, SyncStatusEnum
        from datetime import datetime, timezone, timedelta

        existing_status = SyncStatus(
            portfolio_id=portfolio.id,
            status=SyncStatusEnum.COMPLETED,
            last_sync_started=datetime.now(timezone.utc) - timedelta(hours=2),
            last_sync_completed=datetime.now(timezone.utc) - timedelta(hours=2),
            coverage_summary={},
        )
        db.add(existing_status)
        db.commit()

        mock_provider.get_historical_prices.return_value = HistoricalPricesResult(
            ticker="TEST",
            exchange="TEST",
            prices=create_ohlcv_data(date(2024, 1, 1), num_days=5),
            success=True,
        )

        # Should be able to sync
        result = sync_service.sync_portfolio(db, portfolio.id)

        assert result.status in ["completed", "partial"]
        assert result.status != "already_running"

    def test_sync_acquires_job_when_never_synced(
            self, db, mock_provider_and_service, portfolio_with_transactions
    ):
        """Should acquire job and sync when portfolio has never been synced."""
        mock_provider, sync_service = mock_provider_and_service
        portfolio = portfolio_with_transactions["portfolio"]

        # No sync status exists (never synced)
        mock_provider.get_historical_prices.return_value = HistoricalPricesResult(
            ticker="TEST",
            exchange="TEST",
            prices=create_ohlcv_data(date(2024, 1, 1), num_days=5),
            success=True,
        )

        result = sync_service.sync_portfolio(db, portfolio.id)

        assert result.status in ["completed", "partial"]
        assert result.status != "already_running"

    def test_sync_acquires_job_after_failed_sync(
            self, db, mock_provider_and_service, portfolio_with_transactions
    ):
        """Should acquire job and sync after a previously failed sync."""
        mock_provider, sync_service = mock_provider_and_service
        portfolio = portfolio_with_transactions["portfolio"]

        # Set status to FAILED
        from app.models import SyncStatus, SyncStatusEnum
        from datetime import datetime, timezone

        existing_status = SyncStatus(
            portfolio_id=portfolio.id,
            status=SyncStatusEnum.FAILED,
            last_sync_started=datetime.now(timezone.utc),
            last_error="Previous sync failed",
            coverage_summary={},
        )
        db.add(existing_status)
        db.commit()

        mock_provider.get_historical_prices.return_value = HistoricalPricesResult(
            ticker="TEST",
            exchange="TEST",
            prices=create_ohlcv_data(date(2024, 1, 1), num_days=5),
            success=True,
        )

        # Should be able to sync after failure
        result = sync_service.sync_portfolio(db, portfolio.id)

        assert result.status in ["completed", "partial"]
        assert result.status != "already_running"
