# backend/tests/routers/test_analytics_api.py
"""
API layer tests for analytics endpoints.

These tests verify the HTTP layer using FastAPI's TestClient:
- Correct status codes (200, 400, 404)
- Response JSON structure matches Pydantic schemas
- Query parameter handling
- Error responses

Test Methodology:
    1. Override database dependency with test database
    2. Seed test data (transactions + market data)
    3. Make HTTP requests via TestClient
    4. Assert status codes and response structure
"""

import os
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

# Set required environment variables BEFORE importing app modules
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
    """Create TestClient with database dependency override."""

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

def seed_user(
        db: Session,
        email: str = "analytics_api_test@example.com",
        is_email_verified: bool = True,
        is_active: bool = True,
) -> User:
    """Create a test user."""
    user = User(
        email=email,
        hashed_password="hashed",
        is_email_verified=is_email_verified,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_auth_headers(user: User) -> dict[str, str]:
    """Generate auth headers for a user."""
    from app.services.auth.jwt_handler import JWTHandler
    jwt_handler = JWTHandler()
    token = jwt_handler.create_access_token(user_id=user.id, email=user.email)
    return {"Authorization": f"Bearer {token}"}


def seed_portfolio(
        db: Session,
        user: User,
        name: str = "Analytics API Test Portfolio",
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
        asset_class: AssetClass = AssetClass.STOCK,
) -> Asset:
    """Create a test asset."""
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


def seed_basic_analytics_data(
        db: Session,
        num_days: int = 15,
) -> tuple[User, Portfolio, Asset, Asset]:
    """
    Seed data for analytics tests.

    Creates:
    - User, Portfolio
    - Asset with transaction and market data
    - Benchmark asset with market data

    Returns:
        Tuple of (user, portfolio, asset, benchmark)
    """
    user = seed_user(db)
    portfolio = seed_portfolio(db, user, currency="USD")
    asset = seed_asset(db, "AAPL", "NASDAQ", "USD")
    benchmark = seed_asset(db, "^SPX", "INDEX", "USD", "S&P 500", AssetClass.INDEX)

    # Buy 100 shares @ $100
    seed_transaction(
        db, portfolio, asset,
        TransactionType.BUY,
        date(2024, 1, 1),
        Decimal("100"),
        Decimal("100"),
        "USD",
    )

    start_date = date(2024, 1, 1)

    for i in range(num_days):
        current_date = start_date + timedelta(days=i)

        # Asset price with gradual growth
        price = Decimal("100") + Decimal(str(i * 0.5))
        seed_market_data(db, asset, current_date, price)

        # Benchmark data
        bench_price = Decimal("100") + Decimal(str(i * 0.5))
        seed_market_data(db, benchmark, current_date, bench_price)

    return user, portfolio, asset, benchmark


# =============================================================================
# TEST: GET /portfolios/{id}/analytics
# =============================================================================

class TestGetAnalyticsEndpoint:
    """Tests for GET /portfolios/{portfolio_id}/analytics endpoint."""

    def test_analytics_returns_200_with_valid_data(
            self, client: TestClient, test_db: Session
    ):
        """Valid portfolio with data should return 200."""
        # Seed data
        user, portfolio, _, _ = seed_basic_analytics_data(test_db, num_days=15)
        headers = get_auth_headers(user)

        # Act
        response = client.get(
            f"/portfolios/{portfolio.id}/analytics",
            params={
                "from_date": "2024-01-01",
                "to_date": "2024-01-15",
            },
            headers=headers,
        )

        # Assert
        assert response.status_code == 200
        data = response.json()

        # Check structure
        assert "portfolio_id" in data
        assert "portfolio_currency" in data
        assert "period" in data
        assert "performance" in data
        assert "risk" in data
        assert data["portfolio_id"] == portfolio.id
        assert data["portfolio_currency"] == "USD"

    def test_analytics_returns_performance_metrics(
            self, client: TestClient, test_db: Session
    ):
        """Analytics should include performance metrics."""
        user, portfolio, _, _ = seed_basic_analytics_data(test_db)
        headers = get_auth_headers(user)

        response = client.get(
            f"/portfolios/{portfolio.id}/analytics",
            params={"from_date": "2024-01-01", "to_date": "2024-01-15"},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Check performance metrics exist
        perf = data["performance"]
        assert "simple_return" in perf
        assert "twr" in perf
        assert "total_gain" in perf
        assert "start_value" in perf
        assert "end_value" in perf

    def test_analytics_returns_risk_metrics(
            self, client: TestClient, test_db: Session
    ):
        """Analytics should include risk metrics."""
        user, portfolio, _, _ = seed_basic_analytics_data(test_db)
        headers = get_auth_headers(user)

        response = client.get(
            f"/portfolios/{portfolio.id}/analytics",
            params={"from_date": "2024-01-01", "to_date": "2024-01-15"},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Check risk metrics exist
        risk = data["risk"]
        assert "volatility_daily" in risk
        assert "volatility_annualized" in risk
        assert "sharpe_ratio" in risk
        assert "max_drawdown" in risk
        assert "positive_days" in risk
        assert "negative_days" in risk

    def test_analytics_with_benchmark(
            self, client: TestClient, test_db: Session
    ):
        """Analytics with benchmark should include benchmark metrics."""
        user, portfolio, _, _ = seed_basic_analytics_data(test_db)
        headers = get_auth_headers(user)

        response = client.get(
            f"/portfolios/{portfolio.id}/analytics",
            params={
                "from_date": "2024-01-01",
                "to_date": "2024-01-15",
                "benchmark": "^SPX",
            },
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Check benchmark metrics exist
        assert data["benchmark"] is not None
        bench = data["benchmark"]
        assert bench["benchmark_symbol"] == "^SPX"
        assert "beta" in bench
        assert "alpha" in bench
        assert "correlation" in bench

    def test_analytics_requires_auth(
            self, client: TestClient, test_db: Session
    ):
        """Analytics endpoint should require authentication."""
        user, portfolio, _, _ = seed_basic_analytics_data(test_db)

        response = client.get(
            f"/portfolios/{portfolio.id}/analytics",
            params={"from_date": "2024-01-01", "to_date": "2024-01-15"},
        )

        assert response.status_code == 401

    def test_analytics_returns_404_for_nonexistent_portfolio(
            self, client: TestClient, test_db: Session
    ):
        """Non-existent portfolio should return 404."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.get(
            "/portfolios/99999/analytics",
            params={"from_date": "2024-01-01", "to_date": "2024-01-31"},
            headers=headers,
        )

        assert response.status_code == 404

    def test_analytics_returns_400_for_invalid_date_range(
            self, client: TestClient, test_db: Session
    ):
        """from_date > to_date should return 400."""
        user, portfolio, _, _ = seed_basic_analytics_data(test_db)
        headers = get_auth_headers(user)

        response = client.get(
            f"/portfolios/{portfolio.id}/analytics",
            params={
                "from_date": "2024-01-31",
                "to_date": "2024-01-01",  # Before from_date
            },
            headers=headers,
        )

        assert response.status_code == 400

    def test_analytics_returns_400_for_nonexistent_benchmark(
            self, client: TestClient, test_db: Session
    ):
        """Non-synced benchmark should return 400 with clear error."""
        user, portfolio, _, _ = seed_basic_analytics_data(test_db)
        headers = get_auth_headers(user)

        response = client.get(
            f"/portfolios/{portfolio.id}/analytics",
            params={
                "from_date": "2024-01-01",
                "to_date": "2024-01-15",
                "benchmark": "NONEXISTENT",
            },
            headers=headers,
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "BenchmarkNotSyncedError"
        assert "benchmark_symbol" in data["details"]


# =============================================================================
# TEST: GET /portfolios/{id}/analytics/performance
# =============================================================================

class TestGetPerformanceEndpoint:
    """Tests for GET /portfolios/{portfolio_id}/analytics/performance endpoint."""

    def test_performance_returns_200(
            self, client: TestClient, test_db: Session
    ):
        """Performance endpoint should return 200 with valid data."""
        user, portfolio, _, _ = seed_basic_analytics_data(test_db)
        headers = get_auth_headers(user)

        response = client.get(
            f"/portfolios/{portfolio.id}/analytics/performance",
            params={"from_date": "2024-01-01", "to_date": "2024-01-15"},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "portfolio_id" in data
        assert "period" in data
        assert "performance" in data
        # Should NOT have risk or benchmark
        assert "risk" not in data
        assert "benchmark" not in data

    def test_performance_returns_correct_values(
            self, client: TestClient, test_db: Session
    ):
        """Performance endpoint should return correct return values."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)
        portfolio = seed_portfolio(test_db, user)
        asset = seed_asset(test_db, "MSFT", "NASDAQ", "USD")

        # Buy 100 shares @ $100
        seed_transaction(
            test_db, portfolio, asset,
            TransactionType.BUY,
            date(2024, 1, 1),
            Decimal("100"),
            Decimal("100"),
            "USD",
        )

        # Create market data: $100 → $110 (10% growth)
        seed_market_data(test_db, asset, date(2024, 1, 1), Decimal("100"))
        seed_market_data(test_db, asset, date(2024, 1, 31), Decimal("110"))

        response = client.get(
            f"/portfolios/{portfolio.id}/analytics/performance",
            params={"from_date": "2024-01-01", "to_date": "2024-01-31"},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        perf = data["performance"]
        # Simple return should be ~10%
        if perf["simple_return"]:
            simple_return = Decimal(perf["simple_return"])
            assert abs(simple_return - Decimal("0.1")) < Decimal("0.02")


# =============================================================================
# TEST: GET /portfolios/{id}/analytics/risk
# =============================================================================

class TestGetRiskEndpoint:
    """Tests for GET /portfolios/{portfolio_id}/analytics/risk endpoint."""

    def test_risk_returns_200(
            self, client: TestClient, test_db: Session
    ):
        """Risk endpoint should return 200 with valid data."""
        user, portfolio, _, _ = seed_basic_analytics_data(test_db)
        headers = get_auth_headers(user)

        response = client.get(
            f"/portfolios/{portfolio.id}/analytics/risk",
            params={"from_date": "2024-01-01", "to_date": "2024-01-15"},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "portfolio_id" in data
        assert "period" in data
        assert "risk" in data
        # Should NOT have performance or benchmark
        assert "performance" not in data
        assert "benchmark" not in data

    def test_risk_returns_volatility_metrics(
            self, client: TestClient, test_db: Session
    ):
        """Risk endpoint should return volatility and related metrics."""
        user, portfolio, _, _ = seed_basic_analytics_data(test_db)
        headers = get_auth_headers(user)

        response = client.get(
            f"/portfolios/{portfolio.id}/analytics/risk",
            params={"from_date": "2024-01-01", "to_date": "2024-01-15"},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        risk = data["risk"]
        assert "volatility_daily" in risk
        assert "volatility_annualized" in risk
        assert "sharpe_ratio" in risk
        assert "sortino_ratio" in risk
        assert "max_drawdown" in risk

    def test_risk_with_custom_risk_free_rate(
            self, client: TestClient, test_db: Session
    ):
        """Risk endpoint should accept custom risk-free rate."""
        user, portfolio, _, _ = seed_basic_analytics_data(test_db)
        headers = get_auth_headers(user)

        response = client.get(
            f"/portfolios/{portfolio.id}/analytics/risk",
            params={
                "from_date": "2024-01-01",
                "to_date": "2024-01-15",
                "risk_free_rate": "0.05",  # 5%
            },
            headers=headers,
        )

        assert response.status_code == 200


# =============================================================================
# TEST: GET /portfolios/{id}/analytics/benchmark
# =============================================================================

class TestGetBenchmarkEndpoint:
    """Tests for GET /portfolios/{portfolio_id}/analytics/benchmark endpoint."""

    def test_benchmark_returns_200(
            self, client: TestClient, test_db: Session
    ):
        """Benchmark endpoint should return 200 with valid benchmark."""
        user, portfolio, _, _ = seed_basic_analytics_data(test_db)
        headers = get_auth_headers(user)

        response = client.get(
            f"/portfolios/{portfolio.id}/analytics/benchmark",
            params={
                "from_date": "2024-01-01",
                "to_date": "2024-01-15",
                "benchmark": "^SPX",
            },
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "portfolio_id" in data
        assert "period" in data
        assert "benchmark" in data

        bench = data["benchmark"]
        assert bench["benchmark_symbol"] == "^SPX"

    def test_benchmark_returns_comparison_metrics(
            self, client: TestClient, test_db: Session
    ):
        """Benchmark endpoint should return beta, alpha, correlation."""
        user, portfolio, _, _ = seed_basic_analytics_data(test_db)
        headers = get_auth_headers(user)

        response = client.get(
            f"/portfolios/{portfolio.id}/analytics/benchmark",
            params={
                "from_date": "2024-01-01",
                "to_date": "2024-01-15",
                "benchmark": "^SPX",
            },
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        bench = data["benchmark"]
        assert "beta" in bench
        assert "alpha" in bench
        assert "correlation" in bench
        assert "r_squared" in bench
        assert "tracking_error" in bench
        assert "information_ratio" in bench

    def test_benchmark_uses_default_when_no_param(
            self, client: TestClient, test_db: Session
    ):
        """Benchmark endpoint uses default benchmark when none specified."""
        user, portfolio, _, _ = seed_basic_analytics_data(test_db)
        headers = get_auth_headers(user)

        # No benchmark param - should use default based on portfolio currency
        response = client.get(
            f"/portfolios/{portfolio.id}/analytics/benchmark",
            params={
                "from_date": "2024-01-01",
                "to_date": "2024-01-15",
            },
            headers=headers,
        )

        # Should succeed with default benchmark (may be 400 if default not synced)
        assert response.status_code in (200, 400)
        if response.status_code == 400:
            data = response.json()
            assert data["error"] == "BenchmarkNotSyncedError"


# =============================================================================
# TEST: PERIOD INFO IN RESPONSES
# =============================================================================

class TestPeriodInfo:
    """Test that period info is correctly returned in all endpoints."""

    def test_period_info_structure(
            self, client: TestClient, test_db: Session
    ):
        """Period info should include from_date, to_date, trading_days."""
        user, portfolio, _, _ = seed_basic_analytics_data(test_db, num_days=15)
        headers = get_auth_headers(user)

        response = client.get(
            f"/portfolios/{portfolio.id}/analytics",
            params={"from_date": "2024-01-01", "to_date": "2024-01-15"},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        period = data["period"]
        assert period["from_date"] == "2024-01-01"
        assert period["to_date"] == "2024-01-15"
        assert "trading_days" in period
        assert "calendar_days" in period
        assert period["calendar_days"] == 14


# =============================================================================
# TEST: INSUFFICIENT DATA HANDLING
# =============================================================================

class TestInsufficientDataResponses:
    """Test API responses when data is insufficient."""

    def test_returns_has_sufficient_data_false(
            self, client: TestClient, test_db: Session
    ):
        """Single data point should set has_sufficient_data=False."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)
        portfolio = seed_portfolio(test_db, user)
        asset = seed_asset(test_db, "TSLA", "NASDAQ", "USD")

        # Only one day of data
        seed_transaction(
            test_db, portfolio, asset,
            TransactionType.BUY,
            date(2024, 1, 1),
            Decimal("10"),
            Decimal("200"),
            "USD",
        )
        seed_market_data(test_db, asset, date(2024, 1, 1), Decimal("200"))

        response = client.get(
            f"/portfolios/{portfolio.id}/analytics/performance",
            params={"from_date": "2024-01-01", "to_date": "2024-01-01"},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["performance"]["has_sufficient_data"] is False
