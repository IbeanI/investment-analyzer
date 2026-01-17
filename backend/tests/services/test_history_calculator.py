# backend/tests/services/valuation/test_history_calculator.py
"""
Unit tests for HistoryCalculator.

These tests verify the O(N+D) Rolling State algorithm that processes
transactions chronologically and snapshots portfolio state at each date.

Key Properties Tested:
1. Transactions are applied in date order
2. State accumulates correctly across dates
3. Each snapshot reflects cumulative state up to that date
4. Holdings change mid-range (buys/sells affect subsequent snapshots)
5. Cash is tracked correctly through time (if enabled)

Note: These are unit tests using mocked database queries.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.models import TransactionType
from app.services.valuation.calculators import (
    HoldingsCalculator,
    CostBasisCalculator,
    RealizedPnLCalculator,
)
from app.services.valuation.history_calculator import HistoryCalculator


# =============================================================================
# MOCK OBJECTS
# =============================================================================

@dataclass
class MockAsset:
    """Mock Asset for unit testing."""
    id: int
    ticker: str
    exchange: str
    name: str
    currency: str


@dataclass
class MockTransaction:
    """Mock Transaction for unit testing."""
    id: int
    transaction_type: TransactionType
    quantity: Decimal
    price_per_share: Decimal
    fee: Decimal
    currency: str
    exchange_rate: Decimal | None
    asset_id: int | None
    date: date


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def holdings_calc():
    """Create HoldingsCalculator for testing."""
    return HoldingsCalculator()


@pytest.fixture
def cost_calc():
    """Create CostBasisCalculator for testing."""
    return CostBasisCalculator()


@pytest.fixture
def realized_pnl_calc():
    """Create RealizedPnLCalculator for testing."""
    return RealizedPnLCalculator()


@pytest.fixture
def mock_fx_service():
    """Create mock FX service."""
    return MagicMock()


@pytest.fixture
def history_calc(holdings_calc, cost_calc, realized_pnl_calc, mock_fx_service):
    """Create HistoryCalculator with real calculator dependencies."""
    return HistoryCalculator(
        holdings_calc=holdings_calc,
        cost_calc=cost_calc,
        realized_pnl_calc=realized_pnl_calc,
        fx_service=mock_fx_service,
    )


@pytest.fixture
def aapl_asset():
    """Apple stock asset."""
    return MockAsset(
        id=1,
        ticker="AAPL",
        exchange="NASDAQ",
        name="Apple Inc.",
        currency="USD",
    )


# =============================================================================
# DATE GENERATION TESTS
# =============================================================================

class TestDateGeneration:
    """Tests for interval-based date generation."""

    def test_daily_dates(self, history_calc):
        """Daily interval should generate every calendar day."""
        dates = history_calc._generate_dates(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            interval="daily",
        )

        assert len(dates) == 7
        assert dates[0] == date(2024, 1, 1)
        assert dates[-1] == date(2024, 1, 7)

    def test_weekly_dates(self, history_calc):
        """Weekly interval should generate Friday dates plus end date."""
        dates = history_calc._generate_dates(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            interval="weekly",
        )

        # January 2024 Fridays: 5th, 12th, 19th, 26th
        # Plus: end date (31st) is included for charting completeness
        assert len(dates) == 5

        # First 4 are Fridays
        for d in dates[:4]:
            assert d.weekday() == 4  # Friday

        # Last is the end date
        assert dates[-1] == date(2024, 1, 31)

    def test_monthly_dates(self, history_calc):
        """Monthly interval should generate last day of each month."""
        dates = history_calc._generate_dates(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
            interval="monthly",
        )

        assert len(dates) == 6
        # Check last days
        assert dates[0] == date(2024, 1, 31)
        assert dates[1] == date(2024, 2, 29)  # Leap year
        assert dates[2] == date(2024, 3, 31)
        assert dates[3] == date(2024, 4, 30)
        assert dates[4] == date(2024, 5, 31)
        assert dates[5] == date(2024, 6, 30)

    def test_single_day_range(self, history_calc):
        """Single day range should work for all intervals."""
        single_date = date(2024, 1, 15)

        daily = history_calc._generate_dates(single_date, single_date, "daily")
        assert len(daily) == 1
        assert daily[0] == single_date


# =============================================================================
# ROLLING STATE ALGORITHM TESTS
# =============================================================================

class TestRollingStateAlgorithm:
    """
    Tests for the O(N+D) rolling state algorithm.

    The algorithm should:
    1. Process transactions in date order
    2. Apply each transaction exactly once
    3. Accumulate state across dates
    4. Snapshot correctly at each target date
    """

    def test_transactions_applied_in_order(self, history_calc, aapl_asset):
        """Transactions should be applied chronologically."""
        # Setup transactions in date order
        transactions = [
            MockTransaction(
                id=1,
                transaction_type=TransactionType.BUY,
                quantity=Decimal("10"),
                price_per_share=Decimal("100"),
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=Decimal("1"),
                asset_id=1,
                date=date(2024, 1, 10),
            ),
            MockTransaction(
                id=2,
                transaction_type=TransactionType.BUY,
                quantity=Decimal("10"),
                price_per_share=Decimal("110"),
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=Decimal("1"),
                asset_id=1,
                date=date(2024, 1, 20),
            ),
        ]

        assets = {1: aapl_asset}
        target_dates = [date(2024, 1, 15), date(2024, 1, 25)]

        # Mock price lookup - constant price for simplicity
        price_map = {
            (1, date(2024, 1, 15)): Decimal("105"),
            (1, date(2024, 1, 25)): Decimal("115"),
        }

        # Run rolling state calculation
        data_points = history_calc._calculate_history_rolling(
            transactions=transactions,
            assets=assets,
            portfolio_currency="USD",
            target_dates=target_dates,
            price_map=price_map,
            fx_map={},
            tracks_cash=False,
        )

        # Jan 15: Only first BUY (10 shares @ $100)
        # Cost = $1000, Value = 10 × $105 = $1050
        assert data_points[0].cost_basis == Decimal("1000.00")
        assert data_points[0].value == Decimal("1050.00")

        # Jan 25: Both BUYs (20 shares total)
        # Cost = $1000 + $1100 = $2100, Value = 20 × $115 = $2300
        assert data_points[1].cost_basis == Decimal("2100.00")
        assert data_points[1].value == Decimal("2300.00")

    def test_holdings_change_mid_range(self, history_calc, aapl_asset):
        """
        Holdings should update when transactions occur.

        Timeline:
        - Jan 1: Buy 50 shares
        - Jan 15: Snapshot (50 shares)
        - Jan 20: Sell 20 shares
        - Jan 31: Snapshot (30 shares)
        """
        transactions = [
            MockTransaction(
                id=1,
                transaction_type=TransactionType.BUY,
                quantity=Decimal("50"),
                price_per_share=Decimal("100"),
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=Decimal("1"),
                asset_id=1,
                date=date(2024, 1, 1),
            ),
            MockTransaction(
                id=2,
                transaction_type=TransactionType.SELL,
                quantity=Decimal("20"),
                price_per_share=Decimal("120"),
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=Decimal("1"),
                asset_id=1,
                date=date(2024, 1, 20),
            ),
        ]

        assets = {1: aapl_asset}
        target_dates = [date(2024, 1, 15), date(2024, 1, 31)]

        price_map = {
            (1, date(2024, 1, 15)): Decimal("110"),
            (1, date(2024, 1, 31)): Decimal("115"),
        }

        data_points = history_calc._calculate_history_rolling(
            transactions=transactions,
            assets=assets,
            portfolio_currency="USD",
            target_dates=target_dates,
            price_map=price_map,
            fx_map={},
            tracks_cash=False,
        )

        # Jan 15: 50 shares (before sell)
        # Value = 50 × $110 = $5500
        assert data_points[0].value == Decimal("5500.00")

        # Jan 31: 30 shares (after sell)
        # Value = 30 × $115 = $3450
        assert data_points[1].value == Decimal("3450.00")

        # Realized P&L should appear after the sale
        # Sold 20 @ $120 = $2400, Cost = 20 × $100 = $2000
        # Realized = $400
        assert data_points[0].realized_pnl == Decimal("0")  # No sale yet
        assert data_points[1].realized_pnl == Decimal("400.00")  # After sale

    def test_empty_transactions_returns_empty_data(self, history_calc):
        """No transactions should return empty data points."""
        data_points = history_calc._calculate_history_rolling(
            transactions=[],
            assets={},
            portfolio_currency="USD",
            target_dates=[date(2024, 1, 15)],
            price_map={},
            fx_map={},
            tracks_cash=False,
        )

        # Should have one data point with zeros
        assert len(data_points) == 1
        assert data_points[0].value == Decimal("0")
        assert data_points[0].cost_basis == Decimal("0")

    def test_transaction_on_snapshot_date(self, history_calc, aapl_asset):
        """Transaction ON the snapshot date should be included."""
        transactions = [
            MockTransaction(
                id=1,
                transaction_type=TransactionType.BUY,
                quantity=Decimal("100"),
                price_per_share=Decimal("50"),
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=Decimal("1"),
                asset_id=1,
                date=date(2024, 1, 15),  # Same as snapshot date
            ),
        ]

        assets = {1: aapl_asset}
        target_dates = [date(2024, 1, 15)]

        price_map = {
            (1, date(2024, 1, 15)): Decimal("50"),
        }

        data_points = history_calc._calculate_history_rolling(
            transactions=transactions,
            assets=assets,
            portfolio_currency="USD",
            target_dates=target_dates,
            price_map=price_map,
            fx_map={},
            tracks_cash=False,
        )

        # Transaction should be included
        assert data_points[0].cost_basis == Decimal("5000.00")
        assert data_points[0].value == Decimal("5000.00")


# =============================================================================
# CASH TRACKING IN HISTORY TESTS
# =============================================================================

class TestCashTrackingInHistory:
    """Tests for cash balance tracking through time."""

    def test_cash_tracked_when_deposits_exist(self, history_calc, aapl_asset):
        """Cash should be tracked when DEPOSIT transactions exist."""
        transactions = [
            MockTransaction(
                id=1,
                transaction_type=TransactionType.DEPOSIT,
                quantity=Decimal("10000"),
                price_per_share=Decimal("1"),
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=None,
                asset_id=None,
                date=date(2024, 1, 1),
            ),
            MockTransaction(
                id=2,
                transaction_type=TransactionType.BUY,
                quantity=Decimal("50"),
                price_per_share=Decimal("100"),
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=Decimal("1"),
                asset_id=1,
                date=date(2024, 1, 10),
            ),
        ]

        assets = {1: aapl_asset}
        target_dates = [date(2024, 1, 5), date(2024, 1, 15)]

        price_map = {
            (1, date(2024, 1, 5)): Decimal("100"),  # Won't be used (no holdings yet)
            (1, date(2024, 1, 15)): Decimal("110"),
        }

        data_points = history_calc._calculate_history_rolling(
            transactions=transactions,
            assets=assets,
            portfolio_currency="USD",
            target_dates=target_dates,
            price_map=price_map,
            fx_map={},
            tracks_cash=True,
        )

        # Jan 5: $10000 cash, no holdings
        assert data_points[0].cash == Decimal("10000.00")
        assert data_points[0].value == Decimal("0")
        assert data_points[0].equity == Decimal("10000.00")

        # Jan 15: $5000 cash ($10000 - $5000 buy), 50 shares @ $110 = $5500
        assert data_points[1].cash == Decimal("5000.00")
        assert data_points[1].value == Decimal("5500.00")
        assert data_points[1].equity == Decimal("10500.00")

    def test_cash_not_tracked_when_no_deposits(self, history_calc, aapl_asset):
        """Cash should be None when no DEPOSIT transactions."""
        transactions = [
            MockTransaction(
                id=1,
                transaction_type=TransactionType.BUY,
                quantity=Decimal("50"),
                price_per_share=Decimal("100"),
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=Decimal("1"),
                asset_id=1,
                date=date(2024, 1, 10),
            ),
        ]

        assets = {1: aapl_asset}
        target_dates = [date(2024, 1, 15)]

        price_map = {
            (1, date(2024, 1, 15)): Decimal("110"),
        }

        data_points = history_calc._calculate_history_rolling(
            transactions=transactions,
            assets=assets,
            portfolio_currency="USD",
            target_dates=target_dates,
            price_map=price_map,
            fx_map={},
            tracks_cash=False,  # No cash tracking
        )

        # Cash should be None, equity = value
        assert data_points[0].cash is None
        assert data_points[0].value == Decimal("5500.00")
        assert data_points[0].equity == Decimal("5500.00")


# =============================================================================
# PRICE FALLBACK TESTS
# =============================================================================

class TestPriceFallback:
    """Tests for price fallback logic (weekends/holidays)."""

    def test_price_fallback_within_limit(self, history_calc):
        """Price lookup should fall back to previous days within limit."""
        # Price only on Jan 10
        price_map = {
            (1, date(2024, 1, 10)): Decimal("150.00"),
        }

        # Lookup for Jan 12 (Saturday) should fall back to Jan 10
        price = history_calc._lookup_price_with_fallback(
            price_map, asset_id=1, target_date=date(2024, 1, 12)
        )

        assert price == Decimal("150.00")

    def test_price_fallback_beyond_limit_returns_none(self, history_calc):
        """Price lookup beyond fallback limit should return None."""
        # Price only on Jan 1
        price_map = {
            (1, date(2024, 1, 1)): Decimal("150.00"),
        }

        # Lookup for Jan 15 (14 days later) should fail
        price = history_calc._lookup_price_with_fallback(
            price_map, asset_id=1, target_date=date(2024, 1, 15)
        )

        assert price is None

    def test_exact_date_match_no_fallback(self, history_calc):
        """Exact date match should not use fallback."""
        price_map = {
            (1, date(2024, 1, 15)): Decimal("155.00"),
            (1, date(2024, 1, 14)): Decimal("150.00"),  # Previous day
        }

        price = history_calc._lookup_price_with_fallback(
            price_map, asset_id=1, target_date=date(2024, 1, 15)
        )

        assert price == Decimal("155.00")  # Not the fallback


# =============================================================================
# PERFORMANCE / COMPLEXITY TESTS
# =============================================================================

class TestAlgorithmComplexity:
    """
    Tests to verify O(N+D) complexity of rolling state algorithm.

    The naive approach filters all N transactions for each of D dates = O(N×D).
    The rolling state approach processes each transaction exactly once = O(N+D).
    """

    def test_each_transaction_processed_once(self, history_calc, aapl_asset):
        """
        Verify each transaction is processed exactly once.

        We can't easily test this without instrumentation, but we can
        verify the algorithm produces correct cumulative results.
        """
        # Create 100 sequential buys
        transactions = []
        for i in range(100):
            transactions.append(
                MockTransaction(
                    id=i + 1,
                    transaction_type=TransactionType.BUY,
                    quantity=Decimal("1"),
                    price_per_share=Decimal("100"),
                    fee=Decimal("0"),
                    currency="USD",
                    exchange_rate=Decimal("1"),
                    asset_id=1,
                    date=date(2024, 1, 1) + __import__('datetime').timedelta(days=i),
                )
            )

        assets = {1: aapl_asset}

        # 10 target dates spread across the range
        target_dates = [
            date(2024, 1, 10),
            date(2024, 1, 20),
            date(2024, 1, 30),
            date(2024, 2, 9),
            date(2024, 2, 19),
            date(2024, 2, 29),
            date(2024, 3, 10),
            date(2024, 3, 20),
            date(2024, 3, 30),
            date(2024, 4, 9),
        ]

        # Prices at each date
        price_map = {
            (1, d): Decimal("100") for d in target_dates
        }

        data_points = history_calc._calculate_history_rolling(
            transactions=transactions,
            assets=assets,
            portfolio_currency="USD",
            target_dates=target_dates,
            price_map=price_map,
            fx_map={},
            tracks_cash=False,
        )

        # Verify cumulative results
        # Jan 10: 10 shares (days 1-10)
        assert data_points[0].cost_basis == Decimal("1000.00")

        # Jan 20: 20 shares
        assert data_points[1].cost_basis == Decimal("2000.00")

        # Jan 30: 30 shares
        assert data_points[2].cost_basis == Decimal("3000.00")

        # The pattern continues...
        # Final (Apr 9 = day 100): 100 shares
        assert data_points[-1].cost_basis == Decimal("10000.00")
