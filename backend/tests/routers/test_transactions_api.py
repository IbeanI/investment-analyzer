# tests/routers/test_transactions_api.py
"""
Integration tests for Transaction API endpoints.

These tests verify full HTTP request/response cycles for:
- POST /transactions/ (Create with asset resolution)
- GET /transactions/ (List with filters and pagination)
- GET /transactions/{id} (Read)
- PATCH /transactions/{id} (Update)
- DELETE /transactions/{id} (Delete)
- GET /transactions/portfolio/{id} (Portfolio transactions)
- POST /transactions/batch (Batch create)

Tests validate:
- Asset resolution (existing assets linked, new assets created)
- Correct status codes
- Response structure matches schemas
- Pagination metadata
- Error responses (404, 400, 422)
"""

import os
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

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
)


# =============================================================================
# TEST DATABASE SETUP
# =============================================================================

@pytest.fixture(scope="function")
def test_engine():
    """Create an in-memory SQLite database engine."""
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
    """Create a database session for tests."""
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

def seed_user(db: Session, email: str = "test@example.com") -> User:
    """Create a test user."""
    user = User(email=email, hashed_password="hashed")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def seed_portfolio(
        db: Session,
        user: User,
        name: str = "Test Portfolio",
        currency: str = "EUR",
) -> Portfolio:
    """Create a test portfolio."""
    portfolio = Portfolio(user_id=user.id, name=name, currency=currency)
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return portfolio


def seed_asset(
        db: Session,
        ticker: str = "AAPL",
        exchange: str = "NASDAQ",
        currency: str = "USD",
        name: str = "Apple Inc.",
) -> Asset:
    """Create a test asset."""
    asset = Asset(
        ticker=ticker,
        exchange=exchange,
        name=name,
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
        transaction_type: TransactionType = TransactionType.BUY,
        quantity: Decimal = Decimal("10"),
        price: Decimal = Decimal("100"),
        currency: str = "USD",
) -> Transaction:
    """Create a test transaction."""
    txn = Transaction(
        portfolio_id=portfolio.id,
        asset_id=asset.id,
        transaction_type=transaction_type,
        date=datetime.now(timezone.utc),
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


# =============================================================================
# TEST: POST /transactions/ (Create)
# =============================================================================

class TestCreateTransaction:
    """Tests for POST /transactions/ endpoint."""

    def test_create_transaction_with_existing_asset(
            self, client: TestClient, test_db: Session
    ):
        """Should create transaction linking to existing asset."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user, currency="USD")
        asset = seed_asset(test_db, "AAPL", "NASDAQ", "USD")

        response = client.post(
            "/transactions/",
            json={
                "portfolio_id": portfolio.id,
                "ticker": "AAPL",
                "exchange": "NASDAQ",
                "transaction_type": "BUY",
                "date": "2024-06-15T10:00:00Z",
                "quantity": "50",
                "price_per_share": "180.50",
                "currency": "USD",
            }
        )

        assert response.status_code == 201
        data = response.json()

        assert data["portfolio_id"] == portfolio.id
        assert data["asset_id"] == asset.id
        assert data["transaction_type"] == "BUY"
        assert Decimal(data["quantity"]) == Decimal("50")
        assert Decimal(data["price_per_share"]) == Decimal("180.50")

        # Should include nested asset
        assert data["asset"]["ticker"] == "AAPL"
        assert data["asset"]["exchange"] == "NASDAQ"

    def test_create_transaction_normalizes_ticker(
            self, client: TestClient, test_db: Session
    ):
        """Should normalize ticker to uppercase."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user, currency="USD")
        seed_asset(test_db, "MSFT", "NASDAQ", "USD")

        response = client.post(
            "/transactions/",
            json={
                "portfolio_id": portfolio.id,
                "ticker": "msft",  # lowercase
                "exchange": "nasdaq",  # lowercase
                "transaction_type": "BUY",
                "date": "2024-06-15T10:00:00Z",
                "quantity": "10",
                "price_per_share": "400",
                "currency": "USD",
            }
        )

        assert response.status_code == 201
        # Asset should be found despite lowercase input
        assert response.json()["asset"]["ticker"] == "MSFT"

    def test_create_transaction_portfolio_not_found(self, client: TestClient):
        """Should return 404 if portfolio doesn't exist."""
        response = client.post(
            "/transactions/",
            json={
                "portfolio_id": 99999,
                "ticker": "AAPL",
                "exchange": "NASDAQ",
                "transaction_type": "BUY",
                "date": "2024-06-15T10:00:00Z",
                "quantity": "10",
                "price_per_share": "180",
                "currency": "USD",
            }
        )

        assert response.status_code == 404
        assert "portfolio" in response.json()["message"].lower()

    def test_create_transaction_validation_quantity(
            self, client: TestClient, test_db: Session
    ):
        """Should reject zero or negative quantity."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)

        response = client.post(
            "/transactions/",
            json={
                "portfolio_id": portfolio.id,
                "ticker": "AAPL",
                "exchange": "NASDAQ",
                "transaction_type": "BUY",
                "date": "2024-06-15T10:00:00Z",
                "quantity": "0",  # Invalid
                "price_per_share": "180",
                "currency": "USD",
            }
        )

        assert response.status_code == 422

    def test_create_transaction_future_date_rejected(
            self, client: TestClient, test_db: Session
    ):
        """Should reject transaction with future date."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)

        response = client.post(
            "/transactions/",
            json={
                "portfolio_id": portfolio.id,
                "ticker": "AAPL",
                "exchange": "NASDAQ",
                "transaction_type": "BUY",
                "date": "2099-12-31T10:00:00Z",  # Future
                "quantity": "10",
                "price_per_share": "180",
                "currency": "USD",
            }
        )

        assert response.status_code == 422

    def test_create_sell_transaction(self, client: TestClient, test_db: Session):
        """Should create SELL transaction."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user, currency="USD")
        seed_asset(test_db, "GOOGL", "NASDAQ", "USD")

        response = client.post(
            "/transactions/",
            json={
                "portfolio_id": portfolio.id,
                "ticker": "GOOGL",
                "exchange": "NASDAQ",
                "transaction_type": "SELL",
                "date": "2024-06-15T10:00:00Z",
                "quantity": "5",
                "price_per_share": "175",
                "currency": "USD",
            }
        )

        assert response.status_code == 201
        assert response.json()["transaction_type"] == "SELL"

    def test_create_transaction_with_fee(self, client: TestClient, test_db: Session):
        """Should create transaction with fee."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user, currency="USD")
        seed_asset(test_db, "NVDA", "NASDAQ", "USD")

        response = client.post(
            "/transactions/",
            json={
                "portfolio_id": portfolio.id,
                "ticker": "NVDA",
                "exchange": "NASDAQ",
                "transaction_type": "BUY",
                "date": "2024-06-15T10:00:00Z",
                "quantity": "10",
                "price_per_share": "1000",
                "currency": "USD",
                "fee": "9.99",
                "fee_currency": "USD",
            }
        )

        assert response.status_code == 201
        assert Decimal(response.json()["fee"]) == Decimal("9.99")


# =============================================================================
# TEST: GET /transactions/ (List)
# =============================================================================

class TestListTransactions:
    """Tests for GET /transactions/ endpoint."""

    def test_list_transactions_empty(self, client: TestClient):
        """Should return empty list with pagination."""
        response = client.get("/transactions/")

        assert response.status_code == 200
        data = response.json()

        assert data["items"] == []
        assert data["pagination"]["total"] == 0

    def test_list_transactions_returns_items(
            self, client: TestClient, test_db: Session
    ):
        """Should return list of transactions with assets."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        asset = seed_asset(test_db)
        seed_transaction(test_db, portfolio, asset)
        seed_transaction(test_db, portfolio, asset, TransactionType.SELL)

        response = client.get("/transactions/")

        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) == 2
        assert data["pagination"]["total"] == 2

        # Should include nested asset
        for item in data["items"]:
            assert "asset" in item
            assert item["asset"]["ticker"] == asset.ticker

    def test_list_transactions_filter_by_portfolio(
            self, client: TestClient, test_db: Session
    ):
        """Should filter by portfolio_id."""
        user = seed_user(test_db)
        portfolio1 = seed_portfolio(test_db, user, "P1")
        portfolio2 = seed_portfolio(test_db, user, "P2")
        asset = seed_asset(test_db)

        seed_transaction(test_db, portfolio1, asset)
        seed_transaction(test_db, portfolio2, asset)

        response = client.get(
            "/transactions/",
            params={"portfolio_id": portfolio1.id}
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) == 1
        assert data["items"][0]["portfolio_id"] == portfolio1.id

    def test_list_transactions_filter_by_type(
            self, client: TestClient, test_db: Session
    ):
        """Should filter by transaction_type."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        asset = seed_asset(test_db)

        seed_transaction(test_db, portfolio, asset, TransactionType.BUY)
        seed_transaction(test_db, portfolio, asset, TransactionType.SELL)

        response = client.get(
            "/transactions/",
            params={"transaction_type": "BUY"}
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) == 1
        assert data["items"][0]["transaction_type"] == "BUY"

    def test_list_transactions_filter_by_ticker(
            self, client: TestClient, test_db: Session
    ):
        """Should filter by ticker."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        asset1 = seed_asset(test_db, "AAPL", "NASDAQ", "USD")
        asset2 = seed_asset(test_db, "MSFT", "NASDAQ", "USD")

        seed_transaction(test_db, portfolio, asset1)
        seed_transaction(test_db, portfolio, asset2)

        response = client.get("/transactions/", params={"ticker": "AAPL"})

        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) == 1
        assert data["items"][0]["asset"]["ticker"] == "AAPL"

    def test_list_transactions_pagination(self, client: TestClient, test_db: Session):
        """Should paginate results correctly."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        asset = seed_asset(test_db)

        # Create 15 transactions
        for _ in range(15):
            seed_transaction(test_db, portfolio, asset)

        # First page
        response = client.get("/transactions/", params={"skip": 0, "limit": 10})
        data = response.json()

        assert len(data["items"]) == 10
        assert data["pagination"]["total"] == 15
        assert data["pagination"]["has_next"] is True
        assert data["pagination"]["has_previous"] is False

        # Second page
        response = client.get("/transactions/", params={"skip": 10, "limit": 10})
        data = response.json()

        assert len(data["items"]) == 5
        assert data["pagination"]["has_next"] is False
        assert data["pagination"]["has_previous"] is True


# =============================================================================
# TEST: GET /transactions/{id} (Read)
# =============================================================================

class TestGetTransaction:
    """Tests for GET /transactions/{id} endpoint."""

    def test_get_transaction_success(self, client: TestClient, test_db: Session):
        """Should return transaction with nested asset."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        asset = seed_asset(test_db, "TSLA", "NASDAQ", "USD")
        txn = seed_transaction(test_db, portfolio, asset)

        response = client.get(f"/transactions/{txn.id}")

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == txn.id
        assert data["portfolio_id"] == portfolio.id
        assert data["asset"]["ticker"] == "TSLA"

    def test_get_transaction_not_found(self, client: TestClient):
        """Should return 404 for non-existent transaction."""
        response = client.get("/transactions/99999")

        assert response.status_code == 404


# =============================================================================
# TEST: PATCH /transactions/{id} (Update)
# =============================================================================

class TestUpdateTransaction:
    """Tests for PATCH /transactions/{id} endpoint."""

    def test_update_transaction_quantity(self, client: TestClient, test_db: Session):
        """Should update transaction quantity."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        asset = seed_asset(test_db)
        txn = seed_transaction(test_db, portfolio, asset, quantity=Decimal("10"))

        response = client.patch(
            f"/transactions/{txn.id}",
            json={"quantity": "20"}
        )

        assert response.status_code == 200
        assert Decimal(response.json()["quantity"]) == Decimal("20")

    def test_update_transaction_price(self, client: TestClient, test_db: Session):
        """Should update transaction price."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        asset = seed_asset(test_db)
        txn = seed_transaction(test_db, portfolio, asset, price=Decimal("100"))

        response = client.patch(
            f"/transactions/{txn.id}",
            json={"price_per_share": "150.50"}
        )

        assert response.status_code == 200
        assert Decimal(response.json()["price_per_share"]) == Decimal("150.50")

    def test_update_transaction_not_found(self, client: TestClient):
        """Should return 404 for non-existent transaction."""
        response = client.patch(
            "/transactions/99999",
            json={"quantity": "10"}
        )

        assert response.status_code == 404


# =============================================================================
# TEST: DELETE /transactions/{id}
# =============================================================================

class TestDeleteTransaction:
    """Tests for DELETE /transactions/{id} endpoint."""

    def test_delete_transaction_success(self, client: TestClient, test_db: Session):
        """Should delete transaction and return 204."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        asset = seed_asset(test_db)
        txn = seed_transaction(test_db, portfolio, asset)

        response = client.delete(f"/transactions/{txn.id}")

        assert response.status_code == 204

        # Verify deleted
        get_response = client.get(f"/transactions/{txn.id}")
        assert get_response.status_code == 404

    def test_delete_transaction_not_found(self, client: TestClient):
        """Should return 404 for non-existent transaction."""
        response = client.delete("/transactions/99999")

        assert response.status_code == 404


# =============================================================================
# TEST: GET /transactions/portfolio/{id}
# =============================================================================

class TestGetPortfolioTransactions:
    """Tests for GET /transactions/portfolio/{id} endpoint."""

    def test_get_portfolio_transactions(self, client: TestClient, test_db: Session):
        """Should return transactions for specific portfolio."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        asset = seed_asset(test_db)

        seed_transaction(test_db, portfolio, asset)
        seed_transaction(test_db, portfolio, asset)

        response = client.get(f"/transactions/portfolio/{portfolio.id}")

        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) == 2
        assert data["pagination"]["total"] == 2

    def test_get_portfolio_transactions_not_found(self, client: TestClient):
        """Should return 404 for non-existent portfolio."""
        response = client.get("/transactions/portfolio/99999")

        assert response.status_code == 404


# =============================================================================
# TEST: FULL CRUD FLOW
# =============================================================================

class TestTransactionCRUDFlow:
    """Integration tests for complete CRUD lifecycle."""

    def test_full_crud_lifecycle(self, client: TestClient, test_db: Session):
        """Test complete Create -> Read -> Update -> Delete flow."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user, currency="USD")
        seed_asset(test_db, "META", "NASDAQ", "USD")

        # CREATE
        create_response = client.post(
            "/transactions/",
            json={
                "portfolio_id": portfolio.id,
                "ticker": "META",
                "exchange": "NASDAQ",
                "transaction_type": "BUY",
                "date": "2024-06-15T10:00:00Z",
                "quantity": "25",
                "price_per_share": "500",
                "currency": "USD",
            }
        )
        assert create_response.status_code == 201
        txn_id = create_response.json()["id"]

        # READ
        read_response = client.get(f"/transactions/{txn_id}")
        assert read_response.status_code == 200
        assert Decimal(read_response.json()["quantity"]) == Decimal("25")

        # UPDATE
        update_response = client.patch(
            f"/transactions/{txn_id}",
            json={"quantity": "30", "price_per_share": "495"}
        )
        assert update_response.status_code == 200
        assert Decimal(update_response.json()["quantity"]) == Decimal("30")

        # DELETE
        delete_response = client.delete(f"/transactions/{txn_id}")
        assert delete_response.status_code == 204

        # Verify deleted
        final_response = client.get(f"/transactions/{txn_id}")
        assert final_response.status_code == 404
