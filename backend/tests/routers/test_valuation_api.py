# backend/tests/routers/test_valuation_api.py
"""
API layer tests for valuation endpoints.

These tests verify the HTTP layer using FastAPI's TestClient:
- Correct status codes (200, 400, 404)
- Response JSON structure matches Pydantic schemas
- Query parameter handling
- Error responses

This is the TOP of the test pyramid - fewest tests, but validates
the complete HTTP request/response cycle.

Test Methodology:
    1. Override database dependency with test database
    2. Seed test data
    3. Make HTTP requests via TestClient
    4. Assert status codes and response structure
"""

import os
from datetime import date, datetime
from decimal import Decimal

import pytest

# Set required environment variables BEFORE importing app modules
# This prevents settings validation errors during import
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_NAME", "Test App")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import get_db
from app.models import (
    Base,
    User,
    Portfolio,
    Asset,
    AssetClass,
    Transaction,
    TransactionType,
    MarketData,
    ExchangeRate,
)


# =============================================================================
# TEST DATABASE SETUP
# =============================================================================

@pytest.fixture(scope="function")
def test_engine():
    """Create an in-memory SQLite database engine for API tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def test_db(test_engine) -> Session:
    """Create a database session for API tests."""
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="function")
def client(test_db: Session) -> TestClient:
    """
    Create TestClient with database dependency override.

    This ensures all API calls use our test database.
    """

    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def seed_user(db: Session, email: str = "api_test@example.com") -> User:
    """Create a test user."""
    user = User(email=email, hashed_password="hashed")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def seed_portfolio(
        db: Session,
        user: User,
        name: str = "API Test Portfolio",
        currency: str = "USD",
) -> Portfolio:
    """Create a test portfolio."""
    portfolio = Portfolio(user_id=user.id, name=name, currency=currency)
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return portfolio


def seed_asset(
        db: Session,
        ticker: str,
        exchange: str,
        currency: str,
        name: str | None = None,
) -> Asset:
    """Create a test asset."""
    asset = Asset(
        ticker=ticker,
        exchange=exchange,
        name=name or f"{ticker} Inc.",
        currency=currency,
        asset_class=AssetClass.STOCK,
        is_active=True,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def seed_transaction(
        db: Session,
        portfolio: Portfolio,
        asset: Asset,
        transaction_type: TransactionType,
        transaction_date: date,
        quantity: Decimal,
        price: Decimal,
        currency: str,
) -> Transaction:
    """Create a test transaction."""
    txn = Transaction(
        portfolio_id=portfolio.id,
        asset_id=asset.id,
        transaction_type=transaction_type,
        date=datetime.combine(transaction_date, datetime.min.time()),
        quantity=quantity,
        price_per_share=price,
        currency=currency,
        fee=Decimal("0"),
        fee_currency=currency,
        exchange_rate=Decimal("1"),
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def seed_market_data(
        db: Session,
        asset: Asset,
        price_date: date,
        price: Decimal,
) -> MarketData:
    """Create market data for an asset."""
    md = MarketData(
        asset_id=asset.id,
        date=price_date,
        open_price=price,
        high_price=price,
        low_price=price,
        close_price=price,
        adjusted_close=price,
        volume=1000000,
        provider="test",
        is_synthetic=False,
    )
    db.add(md)
    db.commit()
    db.refresh(md)
    return md


def seed_exchange_rate(
        db: Session,
        base: str,
        quote: str,
        rate_date: date,
        rate: Decimal,
) -> ExchangeRate:
    """Create an exchange rate."""
    er = ExchangeRate(
        base_currency=base,
        quote_currency=quote,
        date=rate_date,
        rate=rate,
        provider="test",
    )
    db.add(er)
    db.commit()
    db.refresh(er)
    return er


# =============================================================================
# TEST: GET /portfolios/{id}/valuation
# =============================================================================

class TestGetValuationEndpoint:
    """Tests for GET /portfolios/{portfolio_id}/valuation endpoint."""

    def test_valuation_returns_200_with_valid_data(
            self, client: TestClient, test_db: Session
    ):
        """Valid portfolio with holdings should return 200 and correct structure."""
        # Seed data
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user, currency="USD")
        asset = seed_asset(test_db, "AAPL", "NASDAQ", "USD")

        seed_transaction(
            test_db, portfolio, asset,
            TransactionType.BUY,
            date(2024, 1, 15),
            Decimal("50"),
            Decimal("180"),
            "USD",
        )
        seed_market_data(test_db, asset, date(2024, 6, 15), Decimal("190"))

        # Make request
        response = client.get(
            f"/portfolios/{portfolio.id}/valuation",
            params={"date": "2024-06-15"}
        )

        # Assert status
        assert response.status_code == 200

        # Assert structure
        data = response.json()
        assert data["portfolio_id"] == portfolio.id
        assert data["portfolio_currency"] == "USD"
        assert data["valuation_date"] == "2024-06-15"

        # Summary exists
        assert "summary" in data
        assert "total_cost_basis" in data["summary"]
        assert "total_value" in data["summary"]
        assert "total_unrealized_pnl" in data["summary"]

        # Holdings exist
        assert "holdings" in data
        assert len(data["holdings"]) == 1

        holding = data["holdings"][0]
        assert holding["ticker"] == "AAPL"
        assert Decimal(holding["quantity"]) == Decimal("50")
        assert "cost_basis" in holding
        assert "current_value" in holding
        assert "pnl" in holding

    def test_valuation_returns_404_for_nonexistent_portfolio(
            self, client: TestClient
    ):
        """Non-existent portfolio should return 404."""
        response = client.get("/portfolios/99999/valuation")

        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "NotFoundError"
        assert "not found" in data["message"].lower()

    def test_valuation_defaults_to_today_without_date_param(
            self, client: TestClient, test_db: Session
    ):
        """Omitting date parameter should default to today."""
        user = seed_user(test_db, email="today@test.com")
        portfolio = seed_portfolio(test_db, user)

        response = client.get(f"/portfolios/{portfolio.id}/valuation")

        assert response.status_code == 200
        data = response.json()
        # Should have a valuation_date (today)
        assert "valuation_date" in data

    def test_valuation_empty_portfolio_returns_zeros(
            self, client: TestClient, test_db: Session
    ):
        """Portfolio with no transactions should return zero values."""
        user = seed_user(test_db, email="empty@test.com")
        portfolio = seed_portfolio(test_db, user)

        response = client.get(
            f"/portfolios/{portfolio.id}/valuation",
            params={"date": "2024-06-15"}
        )

        assert response.status_code == 200
        data = response.json()

        assert data["holdings"] == []
        assert data["summary"]["total_cost_basis"] == "0"

    def test_valuation_tracks_cash_false_without_deposits(
            self, client: TestClient, test_db: Session
    ):
        """Portfolio with only BUY should have tracks_cash=false."""
        user = seed_user(test_db, email="nocash@test.com")
        portfolio = seed_portfolio(test_db, user, currency="USD")
        asset = seed_asset(test_db, "MSFT", "NASDAQ", "USD")

        seed_transaction(
            test_db, portfolio, asset,
            TransactionType.BUY,
            date(2024, 1, 15),
            Decimal("10"),
            Decimal("400"),
            "USD",
        )
        seed_market_data(test_db, asset, date(2024, 6, 15), Decimal("420"))

        response = client.get(
            f"/portfolios/{portfolio.id}/valuation",
            params={"date": "2024-06-15"}
        )

        assert response.status_code == 200
        data = response.json()

        assert data["tracks_cash"] is False
        assert data["cash_balances"] == []


# =============================================================================
# TEST: GET /portfolios/{id}/valuation/history
# =============================================================================

class TestGetValuationHistoryEndpoint:
    """Tests for GET /portfolios/{portfolio_id}/valuation/history endpoint."""

    def test_history_returns_200_with_valid_data(
            self, client: TestClient, test_db: Session
    ):
        """Valid date range should return 200 and time series data."""
        user = seed_user(test_db, email="history@test.com")
        portfolio = seed_portfolio(test_db, user, currency="USD")
        asset = seed_asset(test_db, "GOOG", "NASDAQ", "USD")

        seed_transaction(
            test_db, portfolio, asset,
            TransactionType.BUY,
            date(2024, 1, 1),
            Decimal("20"),
            Decimal("140"),
            "USD",
        )

        # Seed prices for date range
        for day in range(1, 8):
            seed_market_data(test_db, asset, date(2024, 1, day), Decimal("145"))

        response = client.get(
            f"/portfolios/{portfolio.id}/valuation/history",
            params={
                "from_date": "2024-01-01",
                "to_date": "2024-01-07",
                "interval": "daily",
            }
        )

        assert response.status_code == 200

        data = response.json()
        assert data["portfolio_id"] == portfolio.id
        assert data["from_date"] == "2024-01-01"
        assert data["to_date"] == "2024-01-07"
        assert data["interval"] == "daily"

        # Should have data points
        assert "data" in data
        assert len(data["data"]) == 7  # 7 days

        # Each point should have required fields
        point = data["data"][0]
        assert "date" in point
        assert "value" in point
        assert "cost_basis" in point
        assert "total_pnl" in point

    def test_history_returns_404_for_nonexistent_portfolio(
            self, client: TestClient
    ):
        """Non-existent portfolio should return 404."""
        response = client.get(
            "/portfolios/99999/valuation/history",
            params={
                "from_date": "2024-01-01",
                "to_date": "2024-01-31",
            }
        )

        assert response.status_code == 404

    def test_history_returns_400_for_invalid_date_range(
            self, client: TestClient, test_db: Session
    ):
        """from_date after to_date should return 400."""
        user = seed_user(test_db, email="badrange@test.com")
        portfolio = seed_portfolio(test_db, user)

        response = client.get(
            f"/portfolios/{portfolio.id}/valuation/history",
            params={
                "from_date": "2024-12-31",  # After to_date
                "to_date": "2024-01-01",
            }
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "BadRequestError"
        assert "before" in data["message"].lower()

    def test_history_validates_interval_parameter(
            self, client: TestClient, test_db: Session
    ):
        """Invalid interval should return 422 validation error."""
        user = seed_user(test_db, email="badinterval@test.com")
        portfolio = seed_portfolio(test_db, user)

        response = client.get(
            f"/portfolios/{portfolio.id}/valuation/history",
            params={
                "from_date": "2024-01-01",
                "to_date": "2024-01-31",
                "interval": "invalid_interval",  # Bad value
            }
        )

        assert response.status_code == 422  # Validation error

    def test_history_supports_weekly_interval(
            self, client: TestClient, test_db: Session
    ):
        """Weekly interval should return Friday snapshots."""
        user = seed_user(test_db, email="weekly@test.com")
        portfolio = seed_portfolio(test_db, user, currency="USD")
        asset = seed_asset(test_db, "AMZN", "NASDAQ", "USD")

        seed_transaction(
            test_db, portfolio, asset,
            TransactionType.BUY,
            date(2024, 1, 1),
            Decimal("10"),
            Decimal("150"),
            "USD",
        )

        # Seed prices for January (all days to ensure coverage)
        for day in range(1, 32):
            seed_market_data(test_db, asset, date(2024, 1, day), Decimal("155"))

        response = client.get(
            f"/portfolios/{portfolio.id}/valuation/history",
            params={
                "from_date": "2024-01-01",
                "to_date": "2024-01-31",
                "interval": "weekly",
            }
        )

        assert response.status_code == 200
        data = response.json()

        # Weekly should have fewer points than daily
        assert data["interval"] == "weekly"
        assert len(data["data"]) < 31  # Less than daily


# =============================================================================
# TEST: RESPONSE STRUCTURE VALIDATION
# =============================================================================

class TestResponseStructure:
    """Tests to ensure response matches Pydantic schema structure."""

    def test_holding_valuation_structure(
            self, client: TestClient, test_db: Session
    ):
        """Holding valuation should have complete nested structure."""
        user = seed_user(test_db, email="structure@test.com")
        portfolio = seed_portfolio(test_db, user, currency="USD")
        asset = seed_asset(test_db, "NVDA", "NASDAQ", "USD", "NVIDIA Corp")

        seed_transaction(
            test_db, portfolio, asset,
            TransactionType.BUY,
            date(2024, 1, 15),
            Decimal("100"),
            Decimal("500"),
            "USD",
        )
        seed_market_data(test_db, asset, date(2024, 6, 15), Decimal("550"))

        response = client.get(
            f"/portfolios/{portfolio.id}/valuation",
            params={"date": "2024-06-15"}
        )

        assert response.status_code == 200
        holding = response.json()["holdings"][0]

        # Asset identification
        assert "asset_id" in holding
        assert "ticker" in holding
        assert "exchange" in holding
        assert "asset_name" in holding
        assert "asset_currency" in holding

        # Cost basis structure
        cost = holding["cost_basis"]
        assert "local_currency" in cost
        assert "local_amount" in cost
        assert "portfolio_currency" in cost
        assert "portfolio_amount" in cost
        assert "avg_cost_per_share" in cost

        # Current value structure
        value = holding["current_value"]
        assert "price_per_share" in value
        assert "price_date" in value
        assert "local_amount" in value
        assert "portfolio_amount" in value
        assert "fx_rate_used" in value

        # P&L structure
        pnl = holding["pnl"]
        assert "unrealized_amount" in pnl
        assert "unrealized_percentage" in pnl
        assert "realized_amount" in pnl
        assert "realized_percentage" in pnl
        assert "total_amount" in pnl

    def test_summary_structure(
            self, client: TestClient, test_db: Session
    ):
        """Portfolio summary should have all required fields."""
        user = seed_user(test_db, email="summary@test.com")
        portfolio = seed_portfolio(test_db, user)

        response = client.get(
            f"/portfolios/{portfolio.id}/valuation",
            params={"date": "2024-06-15"}
        )

        assert response.status_code == 200
        summary = response.json()["summary"]

        assert "total_cost_basis" in summary
        assert "total_value" in summary
        assert "total_cash" in summary
        assert "total_equity" in summary
        assert "total_unrealized_pnl" in summary
        assert "total_realized_pnl" in summary
        assert "total_pnl" in summary
        assert "total_pnl_percentage" in summary
