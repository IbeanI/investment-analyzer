# backend/tests/services/valuation/test_valuation_integration.py
"""
Integration tests for ValuationService.

These tests verify the complete valuation pipeline with real database operations.
They ensure that if data exists in the database, the financial output is
mathematically correct.

Test Methodology:
    1. Seed database with controlled data (Users, Portfolios, Assets, Transactions)
    2. Seed market data (MarketData, ExchangeRate)
    3. Call ValuationService methods
    4. Assert results match manual calculations

Test Scenarios:
    1. Golden Path (Full Lifecycle): Deposit → Buy → Verify totals
    2. Asset-Only Mode: BUY only → tracks_cash=False
    3. Realized P&L: Buy → Partial Sell → Verify realized gains
    4. Resilience: Missing prices → graceful degradation
    5. History Time-Series: Rolling state with position changes
    6. Multi-Currency: GBP portfolio with USD/EUR assets

Design Principles:
    - Each test is independent and isolated
    - Factory functions for DRY setup
    - AAA pattern (Arrange, Act, Assert)
    - Manual calculations documented in comments
    - No external API calls (mocked providers)
"""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.models import (
    User,
    Portfolio,
    Asset,
    AssetClass,
    Transaction,
    TransactionType,
    MarketData,
    ExchangeRate,
)
from app.services.fx_rate_service import FXRateService
from app.services.valuation import ValuationService


# =============================================================================
# FACTORY FUNCTIONS (DRY Setup)
# =============================================================================

def create_user(db: Session, email: str = "test@example.com") -> User:
    """Factory: Create a test user."""
    user = User(email=email, hashed_password="hashed_password")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_portfolio(
        db: Session,
        user: User,
        name: str = "Test Portfolio",
        currency: str = "EUR",
) -> Portfolio:
    """Factory: Create a test portfolio."""
    portfolio = Portfolio(user_id=user.id, name=name, currency=currency)
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return portfolio


def create_asset(
        db: Session,
        ticker: str,
        exchange: str,
        currency: str,
        name: str | None = None,
        asset_class: AssetClass = AssetClass.STOCK,
) -> Asset:
    """Factory: Create a test asset."""
    asset = Asset(
        ticker=ticker,
        exchange=exchange,
        name=name or f"{ticker} Inc.",
        currency=currency,
        asset_class=asset_class,
        is_active=True,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def create_transaction(
        db: Session,
        portfolio: Portfolio,
        asset: Asset | None,
        transaction_type: TransactionType,
        transaction_date: date,
        quantity: Decimal,
        price_per_share: Decimal,
        currency: str,
        fee: Decimal = Decimal("0"),
        exchange_rate: Decimal | None = Decimal("1"),
) -> Transaction:
    """
    Factory: Create a test transaction.

    Note: For DEPOSIT/WITHDRAWAL transactions, asset should be None.
    The Transaction model should support nullable asset_id for these types.
    If the model doesn't allow nullable asset_id, tests will fail with a
    clear error indicating the model needs updating.
    """
    txn = Transaction(
        portfolio_id=portfolio.id,
        asset_id=asset.id if asset else None,
        transaction_type=transaction_type,
        date=datetime.combine(transaction_date, datetime.min.time()),
        quantity=quantity,
        price_per_share=price_per_share,
        currency=currency,
        fee=fee,
        fee_currency=currency,
        exchange_rate=exchange_rate,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def create_market_data(
        db: Session,
        asset: Asset,
        price_date: date,
        close_price: Decimal,
) -> MarketData:
    """Factory: Create market data (price) for an asset."""
    md = MarketData(
        asset_id=asset.id,
        date=price_date,
        open_price=close_price,
        high_price=close_price,
        low_price=close_price,
        close_price=close_price,
        adjusted_close=close_price,
        volume=1000000,
        provider="test",
        is_synthetic=False,
    )
    db.add(md)
    db.commit()
    db.refresh(md)
    return md


def create_exchange_rate(
        db: Session,
        base_currency: str,
        quote_currency: str,
        rate_date: date,
        rate: Decimal,
) -> ExchangeRate:
    """Factory: Create an exchange rate."""
    er = ExchangeRate(
        base_currency=base_currency,
        quote_currency=quote_currency,
        date=rate_date,
        rate=rate,
        provider="test",
    )
    db.add(er)
    db.commit()
    db.refresh(er)
    return er


def create_mock_fx_service() -> MagicMock:
    """Create a mock FX service that reads from the database."""
    mock_fx = MagicMock(spec=FXRateService)
    return mock_fx


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def valuation_service(db: Session) -> ValuationService:
    """
    Create ValuationService with a real FXRateService.

    The FXRateService will read from our seeded ExchangeRate table.
    We use a mock provider since we won't be syncing external data.
    """
    mock_provider = MagicMock()
    mock_provider.name = "test"
    fx_service = FXRateService(provider=mock_provider, max_fallback_days=5)
    return ValuationService(fx_service=fx_service)


# =============================================================================
# TEST 1: GOLDEN PATH (Full Lifecycle)
# =============================================================================

class TestGoldenPath:
    """
    Test the complete happy path: Buy → Valuation with FX conversion.

    Scenario:
        - Portfolio in EUR
        - Buy 50 shares of AAPL @ $180 USD (cost: $9,000)
        - Exchange rate at transaction: 1 EUR = 1.0869 USD
        - Current price: $190 USD
        - Current FX rate: 1 USD = 0.90 EUR

    Expected Results:
        - Cost Basis: $9,000 / 1.0869 = €8,280 (using txn rate)
        - Current Value: 50 × $190 × 0.90 = €8,550
        - Unrealized P&L: €8,550 - €8,280 = €270

    Note: This test does NOT use DEPOSIT transactions because the current
    Transaction model requires asset_id to be NOT NULL. Once asset_id is
    made nullable (see MODEL_CHANGE_REQUIRED.md), cash tracking tests can
    be added.
    """

    def test_full_lifecycle_valuation(self, db: Session, valuation_service: ValuationService):
        """Buy + Price + FX → Correct valuation."""
        # =====================================================================
        # ARRANGE: Seed the database
        # =====================================================================
        user = create_user(db)
        portfolio = create_portfolio(db, user, currency="EUR")
        aapl = create_asset(db, ticker="AAPL", exchange="NASDAQ", currency="USD")

        valuation_date = date(2024, 6, 15)

        # Buy 50 AAPL @ $180 = $9,000 USD
        # Transaction exchange_rate: 1 EUR = 1.0869565217 USD
        # So cost in EUR = $9,000 / 1.0869565217 = €8,280
        create_transaction(
            db=db,
            portfolio=portfolio,
            asset=aapl,
            transaction_type=TransactionType.BUY,
            transaction_date=date(2024, 1, 15),
            quantity=Decimal("50"),
            price_per_share=Decimal("180"),
            currency="USD",
            fee=Decimal("0"),
            exchange_rate=Decimal("1.0869565217"),  # 1 EUR = 1.0869 USD
        )

        # Seed price: $190 on valuation date
        create_market_data(db, aapl, valuation_date, Decimal("190.00"))

        # Seed FX rate: 1 USD = 0.90 EUR on valuation date
        create_exchange_rate(db, "USD", "EUR", valuation_date, Decimal("0.90"))

        # =====================================================================
        # ACT: Call the service
        # =====================================================================
        result = valuation_service.get_valuation(
            db=db,
            portfolio_id=portfolio.id,
            valuation_date=valuation_date,
        )

        # =====================================================================
        # ASSERT: Verify results
        # =====================================================================

        # Basic structure
        assert result.portfolio_id == portfolio.id
        assert result.portfolio_currency == "EUR"
        assert result.valuation_date == valuation_date

        # No DEPOSIT = no cash tracking
        assert result.tracks_cash is False

        # Holdings
        assert len(result.holdings) == 1
        holding = result.holdings[0]
        assert holding.ticker == "AAPL"
        assert holding.quantity == Decimal("50")

        # Cost Basis: $9,000 / 1.0869565217 = €8,280
        expected_cost_portfolio = Decimal("9000") / Decimal("1.0869565217")
        assert holding.cost_basis.portfolio_amount == pytest.approx(
            expected_cost_portfolio, rel=Decimal("0.01")
        )

        # Current Value: 50 × $190 × 0.90 = €8,550
        expected_value = Decimal("50") * Decimal("190") * Decimal("0.90")
        assert holding.current_value.portfolio_amount == expected_value

        # Unrealized P&L: €8,550 - €8,280 = €270
        expected_unrealized = expected_value - expected_cost_portfolio
        assert holding.pnl.unrealized_amount == pytest.approx(
            expected_unrealized, rel=Decimal("0.01")
        )

        # Total Value = Total Equity (no cash)
        assert result.total_value == expected_value
        assert result.total_equity == expected_value


# =============================================================================
# TEST 2: ASSET-ONLY MODE (No Deposits)
# =============================================================================

class TestAssetOnlyMode:
    """
    Test portfolio with only BUY transactions (no DEPOSIT/WITHDRAWAL).

    Scenario:
        - Portfolio in USD
        - Only BUY transactions (no DEPOSIT)
        - Should NOT track cash (tracks_cash=False)
        - total_equity should equal total_value (no negative cash shown)
    """

    def test_no_deposits_disables_cash_tracking(
            self, db: Session, valuation_service: ValuationService
    ):
        """BUY-only portfolio should have tracks_cash=False."""
        # =====================================================================
        # ARRANGE
        # =====================================================================
        user = create_user(db, email="asset_only@test.com")
        portfolio = create_portfolio(db, user, currency="USD")
        nvda = create_asset(db, ticker="NVDA", exchange="NASDAQ", currency="USD")

        valuation_date = date(2024, 6, 15)

        # Only BUY (no DEPOSIT)
        create_transaction(
            db=db,
            portfolio=portfolio,
            asset=nvda,
            transaction_type=TransactionType.BUY,
            transaction_date=date(2024, 1, 15),
            quantity=Decimal("10"),
            price_per_share=Decimal("500"),
            currency="USD",
            exchange_rate=Decimal("1"),
        )

        # Seed price
        create_market_data(db, nvda, valuation_date, Decimal("550.00"))

        # =====================================================================
        # ACT
        # =====================================================================
        result = valuation_service.get_valuation(
            db=db,
            portfolio_id=portfolio.id,
            valuation_date=valuation_date,
        )

        # =====================================================================
        # ASSERT
        # =====================================================================

        # Smart Cash Detection: No DEPOSIT = no cash tracking
        assert result.tracks_cash is False
        assert len(result.cash_balances) == 0
        assert result.total_cash is None

        # Holdings should be valued correctly
        assert len(result.holdings) == 1
        assert result.holdings[0].quantity == Decimal("10")

        # Cost: 10 × $500 = $5,000
        assert result.holdings[0].cost_basis.portfolio_amount == Decimal("5000")

        # Value: 10 × $550 = $5,500
        assert result.holdings[0].current_value.portfolio_amount == Decimal("5500")

        # Total Equity = Total Value (no cash component)
        assert result.total_value == Decimal("5500")
        assert result.total_equity == result.total_value


# =============================================================================
# TEST 3: REALIZED P&L (Selling)
# =============================================================================

class TestRealizedPnL:
    """
    Test realized P&L calculation when selling shares.

    Scenario:
        - Buy 100 shares @ $100 = $10,000 cost
        - Sell 40 shares @ $125 = $5,000 proceeds
        - Cost of sold shares (WAC): 40 × $100 = $4,000
        - Realized P&L: $5,000 - $4,000 = $1,000 profit
        - Remaining: 60 shares, cost basis $6,000

    Note: This test does NOT use DEPOSIT transactions. Once the model
    supports nullable asset_id, cash tracking assertions can be added.
    """

    def test_partial_sell_realized_pnl(
            self, db: Session, valuation_service: ValuationService
    ):
        """Partial sale should calculate correct realized P&L."""
        # =====================================================================
        # ARRANGE
        # =====================================================================
        user = create_user(db, email="realized_pnl@test.com")
        portfolio = create_portfolio(db, user, currency="USD")
        msft = create_asset(db, ticker="MSFT", exchange="NASDAQ", currency="USD")

        valuation_date = date(2024, 6, 15)

        # Buy 100 shares @ $100 = $10,000
        create_transaction(
            db=db,
            portfolio=portfolio,
            asset=msft,
            transaction_type=TransactionType.BUY,
            transaction_date=date(2024, 2, 1),
            quantity=Decimal("100"),
            price_per_share=Decimal("100"),
            currency="USD",
            exchange_rate=Decimal("1"),
        )

        # Sell 40 shares @ $125 = $5,000 proceeds
        create_transaction(
            db=db,
            portfolio=portfolio,
            asset=msft,
            transaction_type=TransactionType.SELL,
            transaction_date=date(2024, 5, 1),
            quantity=Decimal("40"),
            price_per_share=Decimal("125"),
            currency="USD",
            exchange_rate=Decimal("1"),
        )

        # Current price: $130
        create_market_data(db, msft, valuation_date, Decimal("130.00"))

        # =====================================================================
        # ACT
        # =====================================================================
        result = valuation_service.get_valuation(
            db=db,
            portfolio_id=portfolio.id,
            valuation_date=valuation_date,
        )

        # =====================================================================
        # ASSERT
        # =====================================================================

        # No DEPOSIT = no cash tracking
        assert result.tracks_cash is False

        # Holdings: 60 remaining shares (100 - 40)
        assert len(result.holdings) == 1
        holding = result.holdings[0]
        assert holding.quantity == Decimal("60")

        # Cost Basis for remaining 60 shares: 60 × $100 = $6,000
        assert holding.cost_basis.portfolio_amount == Decimal("6000")

        # Current Value: 60 × $130 = $7,800
        assert holding.current_value.portfolio_amount == Decimal("7800")

        # Realized P&L: $5,000 proceeds - $4,000 cost = $1,000
        assert holding.pnl.realized_amount == Decimal("1000")

        # Unrealized P&L: $7,800 - $6,000 = $1,800
        assert holding.pnl.unrealized_amount == Decimal("1800")

        # Total Realized P&L at portfolio level
        assert result.total_realized_pnl == Decimal("1000")


# =============================================================================
# TEST 4: RESILIENCE (Missing Data)
# =============================================================================

class TestResilience:
    """
    Test graceful degradation when price data is missing.

    Scenario:
        - Buy asset but do NOT seed prices
        - Service should return valid structure (no crash)
        - has_complete_data = False
        - Warnings should indicate missing prices
    """

    def test_missing_prices_graceful_degradation(
            self, db: Session, valuation_service: ValuationService
    ):
        """Missing prices should not crash; should return warnings."""
        # =====================================================================
        # ARRANGE
        # =====================================================================
        user = create_user(db, email="resilience@test.com")
        portfolio = create_portfolio(db, user, currency="USD")
        tsla = create_asset(db, ticker="TSLA", exchange="NASDAQ", currency="USD")

        valuation_date = date(2024, 6, 15)

        # Buy TSLA but do NOT seed any prices
        create_transaction(
            db=db,
            portfolio=portfolio,
            asset=tsla,
            transaction_type=TransactionType.BUY,
            transaction_date=date(2024, 1, 15),
            quantity=Decimal("20"),
            price_per_share=Decimal("200"),
            currency="USD",
            exchange_rate=Decimal("1"),
        )

        # No MarketData seeded!

        # =====================================================================
        # ACT
        # =====================================================================
        result = valuation_service.get_valuation(
            db=db,
            portfolio_id=portfolio.id,
            valuation_date=valuation_date,
        )

        # =====================================================================
        # ASSERT
        # =====================================================================

        # Service should not crash
        assert result is not None
        assert result.portfolio_id == portfolio.id

        # Data quality flag
        assert result.has_complete_data is False

        # Holdings should exist but have missing value
        assert len(result.holdings) == 1
        holding = result.holdings[0]

        # Cost basis is known (from transactions)
        assert holding.cost_basis.portfolio_amount == Decimal("4000")  # 20 × $200

        # Current value is None (no price data)
        assert holding.current_value.portfolio_amount is None
        assert holding.current_value.price is None

        # P&L cannot be calculated
        assert holding.pnl.unrealized_amount is None

        # Holding-level warning
        assert holding.has_complete_data is False
        assert len(holding.warnings) > 0

        # Portfolio-level totals may be None
        assert result.total_value is None or result.total_unrealized_pnl is None


# =============================================================================
# TEST 5: HISTORY TIME-SERIES (Rolling State)
# =============================================================================

class TestHistoryTimeSeries:
    """
    Test the rolling state algorithm for history calculation.

    Scenario:
        - Day 1: Buy 100 shares
        - Day 5: Sell 50 shares
        - Request history Day 1-10
        - Verify holdings drop from 100 to 50 at the correct point
    """

    def test_history_rolling_state(
            self, db: Session, valuation_service: ValuationService
    ):
        """History should reflect position changes over time."""
        # =====================================================================
        # ARRANGE
        # =====================================================================
        user = create_user(db, email="history@test.com")
        portfolio = create_portfolio(db, user, currency="USD")
        goog = create_asset(db, ticker="GOOG", exchange="NASDAQ", currency="USD")

        # Day 1: Buy 100 shares @ $100
        create_transaction(
            db=db,
            portfolio=portfolio,
            asset=goog,
            transaction_type=TransactionType.BUY,
            transaction_date=date(2024, 1, 1),
            quantity=Decimal("100"),
            price_per_share=Decimal("100"),
            currency="USD",
            exchange_rate=Decimal("1"),
        )

        # Day 5: Sell 50 shares @ $110
        create_transaction(
            db=db,
            portfolio=portfolio,
            asset=goog,
            transaction_type=TransactionType.SELL,
            transaction_date=date(2024, 1, 5),
            quantity=Decimal("50"),
            price_per_share=Decimal("110"),
            currency="USD",
            exchange_rate=Decimal("1"),
        )

        # Seed prices for each day (simplified: constant $105)
        for day in range(1, 11):
            d = date(2024, 1, day)
            create_market_data(db, goog, d, Decimal("105"))

        # =====================================================================
        # ACT
        # =====================================================================
        result = valuation_service.get_history(
            db=db,
            portfolio_id=portfolio.id,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 10),
            interval="daily",
        )

        # =====================================================================
        # ASSERT
        # =====================================================================

        assert result.portfolio_id == portfolio.id
        assert len(result.data) == 10  # 10 days

        # Day 1-4: 100 shares × $105 = $10,500 value
        for i in range(4):
            point = result.data[i]
            assert point.value == Decimal("10500"), f"Day {i + 1} value mismatch"
            assert point.cost_basis == Decimal("10000"), f"Day {i + 1} cost mismatch"

        # Day 5+: 50 shares × $105 = $5,250 value
        # Cost basis: 50 × $100 = $5,000
        # Realized P&L: 50 × ($110 - $100) = $500
        for i in range(4, 10):
            point = result.data[i]
            assert point.value == Decimal("5250"), f"Day {i + 1} value mismatch"
            assert point.cost_basis == Decimal("5000"), f"Day {i + 1} cost mismatch"
            assert point.realized_pnl == Decimal("500"), f"Day {i + 1} realized P&L mismatch"


# =============================================================================
# TEST 6: MULTI-CURRENCY LOGIC
# =============================================================================

class TestMultiCurrencyLogic:
    """
    Test FX conversion with multiple currencies.

    Scenario:
        - Portfolio in GBP
        - Asset 1: AAPL in USD
        - Asset 2: SAP in EUR
        - Verify all totals aggregate correctly into GBP
    """

    def test_multi_currency_aggregation(
            self, db: Session, valuation_service: ValuationService
    ):
        """Multi-currency portfolio should convert all values to base currency."""
        # =====================================================================
        # ARRANGE
        # =====================================================================
        user = create_user(db, email="multi_currency@test.com")
        portfolio = create_portfolio(db, user, currency="GBP")

        aapl = create_asset(db, ticker="AAPL", exchange="NASDAQ", currency="USD")
        sap = create_asset(db, ticker="SAP", exchange="XETRA", currency="EUR")

        valuation_date = date(2024, 6, 15)

        # Buy AAPL: 10 shares @ $200 = $2,000
        # Exchange rate at txn: 1 GBP = 1.25 USD → Cost in GBP = $2,000 / 1.25 = £1,600
        create_transaction(
            db=db,
            portfolio=portfolio,
            asset=aapl,
            transaction_type=TransactionType.BUY,
            transaction_date=date(2024, 1, 15),
            quantity=Decimal("10"),
            price_per_share=Decimal("200"),
            currency="USD",
            fee=Decimal("0"),
            exchange_rate=Decimal("1.25"),  # 1 GBP = 1.25 USD
        )

        # Buy SAP: 20 shares @ €100 = €2,000
        # Exchange rate at txn: 1 GBP = 1.15 EUR → Cost in GBP = €2,000 / 1.15 = £1,739.13
        create_transaction(
            db=db,
            portfolio=portfolio,
            asset=sap,
            transaction_type=TransactionType.BUY,
            transaction_date=date(2024, 2, 15),
            quantity=Decimal("20"),
            price_per_share=Decimal("100"),
            currency="EUR",
            fee=Decimal("0"),
            exchange_rate=Decimal("1.15"),  # 1 GBP = 1.15 EUR
        )

        # Seed prices
        create_market_data(db, aapl, valuation_date, Decimal("220.00"))  # $220
        create_market_data(db, sap, valuation_date, Decimal("110.00"))  # €110

        # Seed FX rates for valuation date
        # 1 USD = 0.78 GBP
        create_exchange_rate(db, "USD", "GBP", valuation_date, Decimal("0.78"))
        # 1 EUR = 0.85 GBP
        create_exchange_rate(db, "EUR", "GBP", valuation_date, Decimal("0.85"))

        # =====================================================================
        # ACT
        # =====================================================================
        result = valuation_service.get_valuation(
            db=db,
            portfolio_id=portfolio.id,
            valuation_date=valuation_date,
        )

        # =====================================================================
        # ASSERT
        # =====================================================================

        assert result.portfolio_currency == "GBP"
        assert len(result.holdings) == 2

        # Find AAPL holding
        aapl_holding = next(h for h in result.holdings if h.ticker == "AAPL")

        # AAPL Cost: $2,000 / 1.25 = £1,600
        assert aapl_holding.cost_basis.portfolio_amount == Decimal("1600")

        # AAPL Value: 10 × $220 × 0.78 = £1,716
        expected_aapl_value = Decimal("10") * Decimal("220") * Decimal("0.78")
        assert aapl_holding.current_value.portfolio_amount == expected_aapl_value

        # Find SAP holding
        sap_holding = next(h for h in result.holdings if h.ticker == "SAP")

        # SAP Cost: €2,000 / 1.15 = £1,739.13
        expected_sap_cost = Decimal("2000") / Decimal("1.15")
        assert sap_holding.cost_basis.portfolio_amount == pytest.approx(
            expected_sap_cost, rel=Decimal("0.01")
        )

        # SAP Value: 20 × €110 × 0.85 = £1,870
        expected_sap_value = Decimal("20") * Decimal("110") * Decimal("0.85")
        assert sap_holding.current_value.portfolio_amount == expected_sap_value

        # Total Value in GBP: £1,716 + £1,870 = £3,586
        expected_total_value = expected_aapl_value + expected_sap_value
        assert result.total_value == expected_total_value

        # Total Cost Basis: £1,600 + £1,739.13 = £3,339.13
        expected_total_cost = Decimal("1600") + expected_sap_cost
        assert result.total_cost_basis == pytest.approx(
            expected_total_cost, rel=Decimal("0.01")
        )

        # Unrealized P&L: £3,586 - £3,339.13 = £246.87
        expected_pnl = expected_total_value - expected_total_cost
        assert result.total_unrealized_pnl == pytest.approx(
            expected_pnl, rel=Decimal("0.01")
        )
