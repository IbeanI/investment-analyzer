# backend/tests/services/valuation/test_calculators.py
"""
Unit tests for valuation calculators.

These tests verify the pure calculation logic WITHOUT database dependencies.
We use simple mock objects to simulate Transaction and Asset models.

Test Coverage:
- HoldingsCalculator: Position aggregation, quantity tracking
- CostBasisCalculator: Weighted Average Cost (WAC) formula
- RealizedPnLCalculator: Profit/loss on sales
- CashCalculator: Smart cash detection, cash flow tracking
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from app.models import TransactionType
from app.services.valuation.calculators import (
    HoldingsCalculator,
    CostBasisCalculator,
    RealizedPnLCalculator,
    CashCalculator,
)
from app.services.valuation.types import HoldingPosition


# =============================================================================
# MOCK OBJECTS (No database needed)
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
def aapl_asset() -> MockAsset:
    """Apple stock asset."""
    return MockAsset(
        id=1,
        ticker="AAPL",
        exchange="NASDAQ",
        name="Apple Inc.",
        currency="USD",
    )


@pytest.fixture
def msft_asset() -> MockAsset:
    """Microsoft stock asset."""
    return MockAsset(
        id=2,
        ticker="MSFT",
        exchange="NASDAQ",
        name="Microsoft Corporation",
        currency="USD",
    )


@pytest.fixture
def euro_asset() -> MockAsset:
    """European asset in EUR."""
    return MockAsset(
        id=3,
        ticker="SAP",
        exchange="XETRA",
        name="SAP SE",
        currency="EUR",
    )


# =============================================================================
# HOLDINGS CALCULATOR TESTS
# =============================================================================

class TestHoldingsCalculator:
    """Tests for HoldingsCalculator."""

    def test_single_buy_creates_position(self, aapl_asset):
        """A single BUY should create a position with correct quantity."""
        calc = HoldingsCalculator()

        transactions = [
            MockTransaction(
                transaction_type=TransactionType.BUY,
                quantity=Decimal("10"),
                price_per_share=Decimal("150.00"),
                fee=Decimal("5.00"),
                currency="USD",
                exchange_rate=Decimal("1.0"),  # USD portfolio
                asset_id=1,
                date=date(2024, 1, 15),
            )
        ]

        transactions_by_asset = {1: transactions}
        assets = {1: aapl_asset}

        positions = calc.calculate(
            transactions_by_asset=transactions_by_asset,
            assets=assets,
            portfolio_currency="USD",
        )

        assert len(positions) == 1
        pos = positions[0]
        assert pos.asset_id == 1
        assert pos.quantity == Decimal("10")
        assert pos.total_bought_qty == Decimal("10")
        # Cost = 10 × $150 + $5 fee = $1505
        assert pos.total_bought_cost_local == Decimal("1505.00")

    def test_multiple_buys_aggregate_quantity(self, aapl_asset):
        """Multiple BUYs should aggregate to total quantity."""
        calc = HoldingsCalculator()

        transactions = [
            MockTransaction(
                transaction_type=TransactionType.BUY,
                quantity=Decimal("10"),
                price_per_share=Decimal("100.00"),
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=Decimal("1.0"),
                asset_id=1,
                date=date(2024, 1, 15),
            ),
            MockTransaction(
                transaction_type=TransactionType.BUY,
                quantity=Decimal("10"),
                price_per_share=Decimal("200.00"),
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=Decimal("1.0"),
                asset_id=1,
                date=date(2024, 2, 15),
            ),
        ]

        transactions_by_asset = {1: transactions}
        assets = {1: aapl_asset}

        positions = calc.calculate(
            transactions_by_asset=transactions_by_asset,
            assets=assets,
            portfolio_currency="USD",
        )

        assert len(positions) == 1
        pos = positions[0]
        assert pos.quantity == Decimal("20")
        assert pos.total_bought_qty == Decimal("20")
        # Cost = (10 × $100) + (10 × $200) = $3000
        assert pos.total_bought_cost_local == Decimal("3000.00")

    def test_buy_and_partial_sell_reduces_quantity(self, aapl_asset):
        """BUY + partial SELL should reduce quantity but track sold amount."""
        calc = HoldingsCalculator()

        transactions = [
            MockTransaction(
                transaction_type=TransactionType.BUY,
                quantity=Decimal("100"),
                price_per_share=Decimal("150.00"),
                fee=Decimal("10.00"),
                currency="USD",
                exchange_rate=Decimal("1.0"),
                asset_id=1,
                date=date(2024, 1, 15),
            ),
            MockTransaction(
                transaction_type=TransactionType.SELL,
                quantity=Decimal("30"),
                price_per_share=Decimal("180.00"),
                fee=Decimal("10.00"),
                currency="USD",
                exchange_rate=Decimal("1.0"),
                asset_id=1,
                date=date(2024, 6, 15),
            ),
        ]

        transactions_by_asset = {1: transactions}
        assets = {1: aapl_asset}

        positions = calc.calculate(
            transactions_by_asset=transactions_by_asset,
            assets=assets,
            portfolio_currency="USD",
        )

        assert len(positions) == 1
        pos = positions[0]
        assert pos.quantity == Decimal("70")  # 100 - 30
        assert pos.total_bought_qty == Decimal("100")
        assert pos.total_sold_qty == Decimal("30")
        # Proceeds = 30 × $180 - $10 fee = $5390
        assert pos.total_sold_proceeds_portfolio == Decimal("5390.00")

    def test_full_sell_includes_position_for_realized_pnl(self, aapl_asset):
        """
        Position with quantity=0 should be INCLUDED for realized P&L calculation.

        This changed from the old behavior where closed positions were excluded.
        Now we include them so we can track realized P&L from fully closed positions.
        """
        calc = HoldingsCalculator()

        transactions = [
            MockTransaction(
                transaction_type=TransactionType.BUY,
                quantity=Decimal("50"),
                price_per_share=Decimal("100.00"),
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=Decimal("1.0"),
                asset_id=1,
                date=date(2024, 1, 15),
            ),
            MockTransaction(
                transaction_type=TransactionType.SELL,
                quantity=Decimal("50"),
                price_per_share=Decimal("120.00"),
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=Decimal("1.0"),
                asset_id=1,
                date=date(2024, 6, 15),
            ),
        ]

        transactions_by_asset = {1: transactions}
        assets = {1: aapl_asset}

        positions = calc.calculate(
            transactions_by_asset=transactions_by_asset,
            assets=assets,
            portfolio_currency="USD",
        )

        # Position fully sold - NOW included for realized P&L calculation
        assert len(positions) == 1
        pos = positions[0]
        assert pos.quantity == Decimal("0")  # Closed position
        assert pos.total_sold_qty == Decimal("50")
        # Proceeds = 50 × $120 = $6000
        assert pos.total_sold_proceeds_portfolio == Decimal("6000.0")

    def test_fx_conversion_on_buy(self, euro_asset):
        """BUY in foreign currency should convert cost to portfolio currency."""
        calc = HoldingsCalculator()

        # EUR portfolio buying EUR asset - exchange_rate = 1
        # But let's test USD portfolio buying EUR asset
        # exchange_rate = 1.10 means 1 USD = 1.10 EUR
        # So cost_EUR / 1.10 = cost_USD
        transactions = [
            MockTransaction(
                transaction_type=TransactionType.BUY,
                quantity=Decimal("10"),
                price_per_share=Decimal("100.00"),  # EUR
                fee=Decimal("10.00"),  # EUR
                currency="EUR",
                exchange_rate=Decimal("1.10"),  # 1 USD = 1.10 EUR
                asset_id=3,
                date=date(2024, 1, 15),
            ),
        ]

        transactions_by_asset = {3: transactions}
        assets = {3: euro_asset}

        positions = calc.calculate(
            transactions_by_asset=transactions_by_asset,
            assets=assets,
            portfolio_currency="USD",  # Portfolio in USD
        )

        pos = positions[0]
        # Local cost = 10 × €100 + €10 = €1010
        assert pos.total_bought_cost_local == Decimal("1010.00")
        # Portfolio cost = €1010 / 1.10 = $918.18 (approximately)
        expected_portfolio_cost = Decimal("1010.00") / Decimal("1.10")
        assert pos.total_bought_cost_portfolio == expected_portfolio_cost


# =============================================================================
# COST BASIS CALCULATOR TESTS
# =============================================================================

class TestCostBasisCalculator:
    """Tests for CostBasisCalculator using Weighted Average Cost (WAC)."""

    def test_single_buy_cost_basis(self, aapl_asset):
        """Single BUY should have cost basis = total cost."""
        calc = CostBasisCalculator()

        position = HoldingPosition(
            asset_id=1,
            asset=aapl_asset,
            quantity=Decimal("10"),
            total_bought_qty=Decimal("10"),
            total_bought_cost_local=Decimal("1505.00"),  # 10 × $150 + $5 fee
            total_bought_cost_portfolio=Decimal("1505.00"),
            total_sold_qty=Decimal("0"),
            total_sold_proceeds_portfolio=Decimal("0"),
        )

        result = calc.calculate(position, portfolio_currency="USD")

        assert result.portfolio_amount == Decimal("1505.00")
        assert result.local_amount == Decimal("1505.00")
        # Avg cost = $1505 / 10 = $150.50
        assert result.avg_cost_per_share == Decimal("150.50000000")

    def test_weighted_average_cost_formula(self, aapl_asset):
        """
        WAC Formula Test:
        Buy 10 @ $100 = $1000
        Buy 10 @ $200 = $2000
        Total: 20 shares, $3000
        WAC = $3000 / 20 = $150 per share
        """
        calc = CostBasisCalculator()

        position = HoldingPosition(
            asset_id=1,
            asset=aapl_asset,
            quantity=Decimal("20"),
            total_bought_qty=Decimal("20"),
            total_bought_cost_local=Decimal("3000.00"),
            total_bought_cost_portfolio=Decimal("3000.00"),
            total_sold_qty=Decimal("0"),
            total_sold_proceeds_portfolio=Decimal("0"),
        )

        result = calc.calculate(position, portfolio_currency="USD")

        assert result.portfolio_amount == Decimal("3000.00")
        assert result.avg_cost_per_share == Decimal("150.00000000")

    def test_cost_basis_after_partial_sell(self, aapl_asset):
        """
        After partial SELL, cost basis should be proportionally reduced.

        Original: 20 shares @ $150 avg = $3000 cost
        Sell 5 shares
        Remaining: 15 shares @ $150 avg = $2250 cost basis
        """
        calc = CostBasisCalculator()

        position = HoldingPosition(
            asset_id=1,
            asset=aapl_asset,
            quantity=Decimal("15"),  # 20 bought - 5 sold
            total_bought_qty=Decimal("20"),
            total_bought_cost_local=Decimal("3000.00"),
            total_bought_cost_portfolio=Decimal("3000.00"),
            total_sold_qty=Decimal("5"),
            total_sold_proceeds_portfolio=Decimal("900.00"),  # Sold at profit
        )

        result = calc.calculate(position, portfolio_currency="USD")

        # Cost basis = remaining_qty × avg_cost = 15 × $150 = $2250
        assert result.portfolio_amount == Decimal("2250.00")
        assert result.avg_cost_per_share == Decimal("150.00000000")

    def test_cost_basis_with_fx(self, euro_asset):
        """Cost basis should track both local and portfolio currency."""
        calc = CostBasisCalculator()

        position = HoldingPosition(
            asset_id=3,
            asset=euro_asset,
            quantity=Decimal("10"),
            total_bought_qty=Decimal("10"),
            total_bought_cost_local=Decimal("1000.00"),  # EUR
            total_bought_cost_portfolio=Decimal("1100.00"),  # USD (at rate 0.91)
            total_sold_qty=Decimal("0"),
            total_sold_proceeds_portfolio=Decimal("0"),
        )

        result = calc.calculate(position, portfolio_currency="USD")

        assert result.local_currency == "EUR"
        assert result.local_amount == Decimal("1000.00")
        assert result.portfolio_currency == "USD"
        assert result.portfolio_amount == Decimal("1100.00")
        assert result.avg_cost_per_share == Decimal("100.00000000")  # EUR


# =============================================================================
# REALIZED P&L CALCULATOR TESTS
# =============================================================================

class TestRealizedPnLCalculator:
    """Tests for RealizedPnLCalculator."""

    def test_no_sales_zero_realized(self, aapl_asset):
        """No sales should result in zero realized P&L."""
        calc = RealizedPnLCalculator()

        position = HoldingPosition(
            asset_id=1,
            asset=aapl_asset,
            quantity=Decimal("10"),
            total_bought_qty=Decimal("10"),
            total_bought_cost_local=Decimal("1500.00"),
            total_bought_cost_portfolio=Decimal("1500.00"),
            total_sold_qty=Decimal("0"),
            total_sold_proceeds_portfolio=Decimal("0"),
        )

        amount, percentage = calc.calculate(position)

        assert amount == Decimal("0")
        assert percentage is None  # No sales = undefined percentage

    def test_profitable_sale(self, aapl_asset):
        """
        Profitable Sale Test:
        Bought 10 @ $100 = $1000 cost
        Sold 5 @ $150 = $750 proceeds
        Cost of sold = 5 × $100 = $500
        Realized P&L = $750 - $500 = $250 (profit)
        Percentage = ($250 / $500) × 100 = 50%
        """
        calc = RealizedPnLCalculator()

        position = HoldingPosition(
            asset_id=1,
            asset=aapl_asset,
            quantity=Decimal("5"),  # 10 - 5
            total_bought_qty=Decimal("10"),
            total_bought_cost_local=Decimal("1000.00"),
            total_bought_cost_portfolio=Decimal("1000.00"),
            total_sold_qty=Decimal("5"),
            total_sold_proceeds_portfolio=Decimal("750.00"),
        )

        amount, percentage = calc.calculate(position)

        assert amount == Decimal("250.00")  # Profit
        assert percentage == Decimal("50.00")  # 50%

    def test_loss_sale(self, aapl_asset):
        """
        Loss Sale Test:
        Bought 10 @ $100 = $1000 cost
        Sold 5 @ $80 = $400 proceeds
        Cost of sold = 5 × $100 = $500
        Realized P&L = $400 - $500 = -$100 (loss)
        Percentage = (-$100 / $500) × 100 = -20%
        """
        calc = RealizedPnLCalculator()

        position = HoldingPosition(
            asset_id=1,
            asset=aapl_asset,
            quantity=Decimal("5"),
            total_bought_qty=Decimal("10"),
            total_bought_cost_local=Decimal("1000.00"),
            total_bought_cost_portfolio=Decimal("1000.00"),
            total_sold_qty=Decimal("5"),
            total_sold_proceeds_portfolio=Decimal("400.00"),
        )

        amount, percentage = calc.calculate(position)

        assert amount == Decimal("-100.00")  # Loss
        assert percentage == Decimal("-20.00")  # -20%

    def test_full_sell_realized_pnl(self, aapl_asset):
        """
        Full Sale Test (position closed):
        Bought 20 @ $100 = $2000 cost
        Sold 20 @ $120 = $2400 proceeds
        Realized P&L = $2400 - $2000 = $400
        """
        calc = RealizedPnLCalculator()

        position = HoldingPosition(
            asset_id=1,
            asset=aapl_asset,
            quantity=Decimal("0"),  # Fully sold
            total_bought_qty=Decimal("20"),
            total_bought_cost_local=Decimal("2000.00"),
            total_bought_cost_portfolio=Decimal("2000.00"),
            total_sold_qty=Decimal("20"),
            total_sold_proceeds_portfolio=Decimal("2400.00"),
        )

        amount, percentage = calc.calculate(position)

        assert amount == Decimal("400.00")
        assert percentage == Decimal("20.00")


# =============================================================================
# CASH CALCULATOR TESTS
# =============================================================================

class TestCashCalculator:
    """Tests for CashCalculator with Smart Cash Detection."""

    def test_smart_cash_no_deposits_not_tracked(self):
        """Portfolio with only BUY/SELL should NOT track cash.

        Note: The 'smart cash' detection is done via has_cash_transactions().
        The calculate() method always calculates - caller must check first.
        """
        transactions = [
            MockTransaction(
                transaction_type=TransactionType.BUY,
                quantity=Decimal("10"),
                price_per_share=Decimal("100.00"),
                fee=Decimal("5.00"),
                currency="USD",
                exchange_rate=None,
                asset_id=1,
                date=date(2024, 1, 15),
            ),
        ]

        # Smart detection: no DEPOSIT = don't track cash
        assert CashCalculator.has_cash_transactions(transactions) is False

        # If we DID call calculate(), it would show negative cash
        # (which is why we check has_cash_transactions first)
        calc = CashCalculator()
        result = calc.calculate(transactions, portfolio_currency="USD")
        assert result["USD"] == Decimal("-1005.00")  # Cost of BUY

    def test_smart_cash_with_deposit_enables_tracking(self):
        """Portfolio with DEPOSIT should track cash."""
        calc = CashCalculator()

        transactions = [
            MockTransaction(
                transaction_type=TransactionType.DEPOSIT,
                quantity=Decimal("10000"),
                price_per_share=Decimal("1"),
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=None,
                asset_id=None,
                date=date(2024, 1, 1),
            ),
        ]

        result = calc.calculate(transactions, portfolio_currency="USD")

        assert result is not None
        assert result["USD"] == Decimal("10000.00")

    def test_deposit_buy_calculates_remaining_cash(self):
        """
        Cash Flow Test:
        DEPOSIT $10,000
        BUY $9,000 of stock (including fees)
        Remaining cash = $1,000
        """
        calc = CashCalculator()

        transactions = [
            MockTransaction(
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
                transaction_type=TransactionType.BUY,
                quantity=Decimal("60"),
                price_per_share=Decimal("150.00"),  # $9000
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=None,
                asset_id=1,
                date=date(2024, 1, 15),
            ),
        ]

        result = calc.calculate(transactions, portfolio_currency="USD")

        assert result["USD"] == Decimal("1000.00")

    def test_sell_adds_cash(self):
        """SELL should add cash (proceeds minus fees)."""
        calc = CashCalculator()

        transactions = [
            MockTransaction(
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
                transaction_type=TransactionType.BUY,
                quantity=Decimal("50"),
                price_per_share=Decimal("100.00"),  # $5000
                fee=Decimal("10.00"),  # Total: $5010
                currency="USD",
                exchange_rate=None,
                asset_id=1,
                date=date(2024, 1, 15),
            ),
            MockTransaction(
                transaction_type=TransactionType.SELL,
                quantity=Decimal("20"),
                price_per_share=Decimal("120.00"),  # $2400
                fee=Decimal("10.00"),  # Net: $2390
                currency="USD",
                exchange_rate=None,
                asset_id=1,
                date=date(2024, 6, 15),
            ),
        ]

        result = calc.calculate(transactions, portfolio_currency="USD")

        # $10000 - $5010 + $2390 = $7380
        assert result["USD"] == Decimal("7380.00")

    def test_withdrawal_removes_cash(self):
        """WITHDRAWAL should remove cash (amount plus fees)."""
        calc = CashCalculator()

        transactions = [
            MockTransaction(
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
                transaction_type=TransactionType.WITHDRAWAL,
                quantity=Decimal("2000"),
                price_per_share=Decimal("1"),
                fee=Decimal("25.00"),  # Wire fee
                currency="USD",
                exchange_rate=None,
                asset_id=None,
                date=date(2024, 6, 1),
            ),
        ]

        result = calc.calculate(transactions, portfolio_currency="USD")

        # $10000 - ($2000 + $25 fee) = $7975
        assert result["USD"] == Decimal("7975.00")

    def test_multi_currency_cash(self):
        """Cash should be tracked per currency."""
        calc = CashCalculator()

        transactions = [
            MockTransaction(
                transaction_type=TransactionType.DEPOSIT,
                quantity=Decimal("10000"),
                price_per_share=Decimal("1"),
                fee=Decimal("0"),
                currency="EUR",
                exchange_rate=None,
                asset_id=None,
                date=date(2024, 1, 1),
            ),
            MockTransaction(
                transaction_type=TransactionType.DEPOSIT,
                quantity=Decimal("5000"),
                price_per_share=Decimal("1"),
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=None,
                asset_id=None,
                date=date(2024, 1, 2),
            ),
            MockTransaction(
                transaction_type=TransactionType.BUY,
                quantity=Decimal("50"),
                price_per_share=Decimal("100.00"),
                fee=Decimal("0"),
                currency="EUR",  # Buying with EUR
                exchange_rate=None,
                asset_id=1,
                date=date(2024, 1, 15),
            ),
        ]

        result = calc.calculate(transactions, portfolio_currency="EUR")

        assert result["EUR"] == Decimal("5000.00")  # 10000 - 5000
        assert result["USD"] == Decimal("5000.00")  # Untouched

    def test_has_cash_transactions_detection(self):
        """Test static method for smart cash detection."""
        calc = CashCalculator()

        # No deposits
        buy_only = [
            MockTransaction(
                transaction_type=TransactionType.BUY,
                quantity=Decimal("10"),
                price_per_share=Decimal("100"),
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=None,
                asset_id=1,
                date=date(2024, 1, 1),
            ),
        ]
        assert CashCalculator.has_cash_transactions(buy_only) is False

        # With deposit
        with_deposit = buy_only + [
            MockTransaction(
                transaction_type=TransactionType.DEPOSIT,
                quantity=Decimal("1000"),
                price_per_share=Decimal("1"),
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=None,
                asset_id=None,
                date=date(2024, 1, 1),
            ),
        ]
        assert CashCalculator.has_cash_transactions(with_deposit) is True

        # With withdrawal
        with_withdrawal = buy_only + [
            MockTransaction(
                transaction_type=TransactionType.WITHDRAWAL,
                quantity=Decimal("500"),
                price_per_share=Decimal("1"),
                fee=Decimal("0"),
                currency="USD",
                exchange_rate=None,
                asset_id=None,
                date=date(2024, 2, 1),
            ),
        ]
        assert CashCalculator.has_cash_transactions(with_withdrawal) is True

    def test_calculate_with_state_mutation(self):
        """Test rolling state update method."""
        calc = CashCalculator()
        cash_state = {}

        # Apply DEPOSIT
        deposit = MockTransaction(
            transaction_type=TransactionType.DEPOSIT,
            quantity=Decimal("10000"),
            price_per_share=Decimal("1"),
            fee=Decimal("0"),
            currency="USD",
            exchange_rate=None,
            asset_id=None,
            date=date(2024, 1, 1),
        )
        calc.calculate_with_state(cash_state, deposit)
        assert cash_state["USD"] == Decimal("10000")

        # Apply BUY
        buy = MockTransaction(
            transaction_type=TransactionType.BUY,
            quantity=Decimal("50"),
            price_per_share=Decimal("100"),
            fee=Decimal("10"),
            currency="USD",
            exchange_rate=None,
            asset_id=1,
            date=date(2024, 1, 15),
        )
        calc.calculate_with_state(cash_state, buy)
        # 10000 - (50 × 100 + 10) = 10000 - 5010 = 4990
        assert cash_state["USD"] == Decimal("4990")

        # Apply SELL
        sell = MockTransaction(
            transaction_type=TransactionType.SELL,
            quantity=Decimal("20"),
            price_per_share=Decimal("120"),
            fee=Decimal("10"),
            currency="USD",
            exchange_rate=None,
            asset_id=1,
            date=date(2024, 6, 15),
        )
        calc.calculate_with_state(cash_state, sell)
        # 4990 + (20 × 120 - 10) = 4990 + 2390 = 7380
        assert cash_state["USD"] == Decimal("7380")
