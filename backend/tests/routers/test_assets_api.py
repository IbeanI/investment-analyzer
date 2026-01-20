# tests/routers/test_assets_api.py
"""
Integration tests for Asset API endpoints.

These tests verify full HTTP request/response cycles for:
- POST /assets/ (Create)
- GET /assets/ (List with filters and pagination)
- GET /assets/{id} (Read)
- PATCH /assets/{id} (Update)
- DELETE /assets/{id} (Soft delete/deactivate)

Tests validate:
- Unique constraints (ticker+exchange, ISIN)
- Correct status codes
- Response structure matches schemas
- Pagination metadata
- Error responses (404, 409, 422)
"""

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_NAME", "Test App")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import get_db
from app.models import Base, Asset, AssetClass


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

def seed_asset(
        db: Session,
        ticker: str = "AAPL",
        exchange: str = "NASDAQ",
        currency: str = "USD",
        name: str = "Apple Inc.",
        asset_class: AssetClass = AssetClass.STOCK,
        is_active: bool = True,
        isin: str | None = None,
) -> Asset:
    """Create a test asset."""
    asset = Asset(
        ticker=ticker,
        exchange=exchange,
        name=name,
        currency=currency,
        asset_class=asset_class,
        is_active=is_active,
        isin=isin,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


# =============================================================================
# TEST: POST /assets/ (Create)
# =============================================================================

class TestCreateAsset:
    """Tests for POST /assets/ endpoint."""

    def test_create_asset_success(self, client: TestClient):
        """Should create asset and return 201."""
        response = client.post(
            "/assets/",
            json={
                "ticker": "NVDA",
                "exchange": "NASDAQ",
                "name": "NVIDIA Corporation",
                "asset_class": "STOCK",
                "currency": "USD",
                "sector": "Technology",
                "region": "United States",
            }
        )

        assert response.status_code == 201
        data = response.json()

        assert data["ticker"] == "NVDA"
        assert data["exchange"] == "NASDAQ"
        assert data["name"] == "NVIDIA Corporation"
        assert data["asset_class"] == "STOCK"
        assert data["currency"] == "USD"
        assert data["is_active"] is True
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    def test_create_asset_normalizes_ticker(self, client: TestClient):
        """Should normalize ticker and exchange to uppercase."""
        response = client.post(
            "/assets/",
            json={
                "ticker": "aapl",  # lowercase
                "exchange": "nasdaq",  # lowercase
                "name": "Apple Inc.",
                "asset_class": "STOCK",
                "currency": "USD",  # Currency pattern requires uppercase
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert data["ticker"] == "AAPL"
        assert data["exchange"] == "NASDAQ"
        assert data["currency"] == "USD"

    def test_create_asset_with_isin(self, client: TestClient):
        """Should create asset with ISIN."""
        response = client.post(
            "/assets/",
            json={
                "ticker": "MSFT",
                "exchange": "NASDAQ",
                "name": "Microsoft Corporation",
                "asset_class": "STOCK",
                "currency": "USD",
                "isin": "US5949181045",
            }
        )

        assert response.status_code == 201
        assert response.json()["isin"] == "US5949181045"

    def test_create_asset_etf(self, client: TestClient):
        """Should create ETF asset."""
        response = client.post(
            "/assets/",
            json={
                "ticker": "VOO",
                "exchange": "NYSE",
                "name": "Vanguard S&P 500 ETF",
                "asset_class": "ETF",
                "currency": "USD",
            }
        )

        assert response.status_code == 201
        assert response.json()["asset_class"] == "ETF"

    def test_create_asset_duplicate_ticker_exchange(
            self, client: TestClient, test_db: Session
    ):
        """Should return 409 for duplicate ticker+exchange."""
        seed_asset(test_db, "GOOGL", "NASDAQ", "USD")

        response = client.post(
            "/assets/",
            json={
                "ticker": "GOOGL",
                "exchange": "NASDAQ",
                "name": "Another Google",
                "asset_class": "STOCK",
                "currency": "USD",
            }
        )

        assert response.status_code == 409
        assert "already exists" in response.json()["message"].lower()

    def test_create_asset_same_ticker_different_exchange(
            self, client: TestClient, test_db: Session
    ):
        """Should allow same ticker on different exchange."""
        seed_asset(test_db, "VUAA", "XETRA", "EUR")

        response = client.post(
            "/assets/",
            json={
                "ticker": "VUAA",
                "exchange": "LSE",  # Different exchange
                "name": "Vanguard S&P 500 UCITS ETF (LSE)",
                "asset_class": "ETF",
                "currency": "GBP",
            }
        )

        assert response.status_code == 201
        assert response.json()["exchange"] == "LSE"

    def test_create_asset_duplicate_isin(self, client: TestClient, test_db: Session):
        """Should return 409 for duplicate ISIN."""
        seed_asset(test_db, "AAPL", "NASDAQ", "USD", isin="US0378331005")

        response = client.post(
            "/assets/",
            json={
                "ticker": "DIFF",
                "exchange": "NYSE",
                "name": "Different Asset",
                "asset_class": "STOCK",
                "currency": "USD",
                "isin": "US0378331005",  # Duplicate ISIN
            }
        )

        assert response.status_code == 409
        assert "isin" in response.json()["message"].lower()

    def test_create_asset_validation_error(self, client: TestClient):
        """Should return 422 for invalid data."""
        response = client.post(
            "/assets/",
            json={
                "ticker": "",  # Empty
                "exchange": "NASDAQ",
                "asset_class": "STOCK",
                "currency": "USD",
            }
        )

        assert response.status_code == 422


# =============================================================================
# TEST: GET /assets/ (List)
# =============================================================================

class TestListAssets:
    """Tests for GET /assets/ endpoint."""

    def test_list_assets_empty(self, client: TestClient):
        """Should return empty list with pagination."""
        response = client.get("/assets/")

        assert response.status_code == 200
        data = response.json()

        assert data["items"] == []
        assert data["pagination"]["total"] == 0
        assert data["pagination"]["page"] == 1

    def test_list_assets_returns_items(self, client: TestClient, test_db: Session):
        """Should return list of assets."""
        seed_asset(test_db, "AAPL", "NASDAQ", "USD")
        seed_asset(test_db, "MSFT", "NASDAQ", "USD")

        response = client.get("/assets/")

        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) == 2
        assert data["pagination"]["total"] == 2

    def test_list_assets_filter_by_asset_class(
            self, client: TestClient, test_db: Session
    ):
        """Should filter by asset_class."""
        seed_asset(test_db, "AAPL", "NASDAQ", "USD", asset_class=AssetClass.STOCK)
        seed_asset(test_db, "VOO", "NYSE", "USD", asset_class=AssetClass.ETF)

        response = client.get("/assets/", params={"asset_class": "ETF"})

        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) == 1
        assert data["items"][0]["asset_class"] == "ETF"

    def test_list_assets_filter_by_exchange(
            self, client: TestClient, test_db: Session
    ):
        """Should filter by exchange."""
        seed_asset(test_db, "AAPL", "NASDAQ", "USD")
        seed_asset(test_db, "SAP", "XETRA", "EUR")

        response = client.get("/assets/", params={"exchange": "XETRA"})

        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) == 1
        assert data["items"][0]["exchange"] == "XETRA"

    def test_list_assets_filter_by_currency(
            self, client: TestClient, test_db: Session
    ):
        """Should filter by currency."""
        seed_asset(test_db, "AAPL", "NASDAQ", "USD")
        seed_asset(test_db, "SAP", "XETRA", "EUR")

        response = client.get("/assets/", params={"currency": "EUR"})

        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) == 1
        assert data["items"][0]["currency"] == "EUR"

    def test_list_assets_filter_by_active_status(
            self, client: TestClient, test_db: Session
    ):
        """Should filter by is_active status."""
        seed_asset(test_db, "AAPL", "NASDAQ", "USD", is_active=True)
        seed_asset(test_db, "OLD", "NYSE", "USD", is_active=False)

        # Active only
        response = client.get("/assets/", params={"is_active": True})
        assert len(response.json()["items"]) == 1

        # Inactive only
        response = client.get("/assets/", params={"is_active": False})
        assert len(response.json()["items"]) == 1

    def test_list_assets_search(self, client: TestClient, test_db: Session):
        """Should search by ticker or name."""
        seed_asset(test_db, "AAPL", "NASDAQ", "USD", name="Apple Inc.")
        seed_asset(test_db, "MSFT", "NASDAQ", "USD", name="Microsoft Corporation")

        # Search by ticker
        response = client.get("/assets/", params={"search": "AAPL"})
        assert len(response.json()["items"]) == 1
        assert response.json()["items"][0]["ticker"] == "AAPL"

        # Search by name
        response = client.get("/assets/", params={"search": "Microsoft"})
        assert len(response.json()["items"]) == 1
        assert response.json()["items"][0]["ticker"] == "MSFT"

    def test_list_assets_pagination(self, client: TestClient, test_db: Session):
        """Should paginate results correctly."""
        # Create 15 assets
        for i in range(15):
            seed_asset(test_db, f"TKR{i:02d}", "NYSE", "USD", name=f"Asset {i}")

        # First page
        response = client.get("/assets/", params={"skip": 0, "limit": 10})
        data = response.json()

        assert len(data["items"]) == 10
        assert data["pagination"]["total"] == 15
        assert data["pagination"]["page"] == 1
        assert data["pagination"]["pages"] == 2
        assert data["pagination"]["has_next"] is True
        assert data["pagination"]["has_previous"] is False

        # Second page
        response = client.get("/assets/", params={"skip": 10, "limit": 10})
        data = response.json()

        assert len(data["items"]) == 5
        assert data["pagination"]["page"] == 2
        assert data["pagination"]["has_next"] is False
        assert data["pagination"]["has_previous"] is True


# =============================================================================
# TEST: GET /assets/{id} (Read)
# =============================================================================

class TestGetAsset:
    """Tests for GET /assets/{id} endpoint."""

    def test_get_asset_success(self, client: TestClient, test_db: Session):
        """Should return asset with 200."""
        asset = seed_asset(test_db, "TSLA", "NASDAQ", "USD", name="Tesla Inc.")

        response = client.get(f"/assets/{asset.id}")

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == asset.id
        assert data["ticker"] == "TSLA"
        assert data["name"] == "Tesla Inc."

    def test_get_asset_not_found(self, client: TestClient):
        """Should return 404 for non-existent asset."""
        response = client.get("/assets/99999")

        assert response.status_code == 404


# =============================================================================
# TEST: PATCH /assets/{id} (Update)
# =============================================================================

class TestUpdateAsset:
    """Tests for PATCH /assets/{id} endpoint."""

    def test_update_asset_name(self, client: TestClient, test_db: Session):
        """Should update asset name."""
        asset = seed_asset(test_db, "AAPL", "NASDAQ", "USD", name="Apple")

        response = client.patch(
            f"/assets/{asset.id}",
            json={"name": "Apple Inc."}
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Apple Inc."

    def test_update_asset_sector(self, client: TestClient, test_db: Session):
        """Should update asset sector."""
        asset = seed_asset(test_db, "AAPL", "NASDAQ", "USD")

        response = client.patch(
            f"/assets/{asset.id}",
            json={"sector": "Technology", "region": "North America"}
        )

        assert response.status_code == 200
        assert response.json()["sector"] == "Technology"
        assert response.json()["region"] == "North America"

    def test_update_asset_ticker_unique_check(
            self, client: TestClient, test_db: Session
    ):
        """Should reject update if new ticker+exchange already exists."""
        seed_asset(test_db, "AAPL", "NASDAQ", "USD")
        asset2 = seed_asset(test_db, "MSFT", "NASDAQ", "USD")

        response = client.patch(
            f"/assets/{asset2.id}",
            json={"ticker": "AAPL"}  # Would conflict
        )

        assert response.status_code == 409

    def test_update_asset_isin_unique_check(
            self, client: TestClient, test_db: Session
    ):
        """Should reject update if new ISIN already exists."""
        seed_asset(test_db, "AAPL", "NASDAQ", "USD", isin="US0378331005")
        asset2 = seed_asset(test_db, "MSFT", "NASDAQ", "USD")

        response = client.patch(
            f"/assets/{asset2.id}",
            json={"isin": "US0378331005"}  # Would conflict
        )

        assert response.status_code == 409

    def test_update_asset_not_found(self, client: TestClient):
        """Should return 404 for non-existent asset."""
        response = client.patch(
            "/assets/99999",
            json={"name": "Test"}
        )

        assert response.status_code == 404

    def test_update_asset_deactivate(self, client: TestClient, test_db: Session):
        """Should be able to deactivate asset via update."""
        asset = seed_asset(test_db, "OLD", "NYSE", "USD", is_active=True)

        response = client.patch(
            f"/assets/{asset.id}",
            json={"is_active": False}
        )

        assert response.status_code == 200
        assert response.json()["is_active"] is False


# =============================================================================
# TEST: DELETE /assets/{id} (Soft Delete)
# =============================================================================

class TestDeleteAsset:
    """Tests for DELETE /assets/{id} endpoint (soft delete)."""

    def test_delete_asset_deactivates(self, client: TestClient, test_db: Session):
        """Should soft delete (deactivate) asset and return 204."""
        asset = seed_asset(test_db, "OLD", "NYSE", "USD", is_active=True)

        response = client.delete(f"/assets/{asset.id}")

        assert response.status_code == 204

        # Verify deactivated (not deleted)
        get_response = client.get(f"/assets/{asset.id}")
        assert get_response.status_code == 200
        assert get_response.json()["is_active"] is False

    def test_delete_asset_not_found(self, client: TestClient):
        """Should return 404 for non-existent asset."""
        response = client.delete("/assets/99999")

        assert response.status_code == 404


# =============================================================================
# TEST: FULL CRUD FLOW
# =============================================================================

class TestAssetCRUDFlow:
    """Integration tests for complete CRUD lifecycle."""

    def test_full_crud_lifecycle(self, client: TestClient):
        """Test complete Create -> Read -> Update -> Delete flow."""
        # CREATE
        create_response = client.post(
            "/assets/",
            json={
                "ticker": "TEST",
                "exchange": "NYSE",
                "name": "Test Corporation",
                "asset_class": "STOCK",
                "currency": "USD",
            }
        )
        assert create_response.status_code == 201
        asset_id = create_response.json()["id"]

        # READ
        read_response = client.get(f"/assets/{asset_id}")
        assert read_response.status_code == 200
        assert read_response.json()["ticker"] == "TEST"

        # UPDATE
        update_response = client.patch(
            f"/assets/{asset_id}",
            json={"name": "Updated Test Corp", "sector": "Technology"}
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "Updated Test Corp"
        assert update_response.json()["sector"] == "Technology"

        # DELETE (soft delete)
        delete_response = client.delete(f"/assets/{asset_id}")
        assert delete_response.status_code == 204

        # Verify soft deleted
        final_response = client.get(f"/assets/{asset_id}")
        assert final_response.status_code == 200
        assert final_response.json()["is_active"] is False

    def test_list_reflects_crud_operations(self, client: TestClient):
        """List endpoint should reflect all CRUD operations."""
        # Initially empty
        response = client.get("/assets/")
        assert response.json()["pagination"]["total"] == 0

        # Create
        client.post(
            "/assets/",
            json={
                "ticker": "NEW",
                "exchange": "NYSE",
                "name": "New Asset",
                "asset_class": "STOCK",
                "currency": "USD",
            }
        )

        response = client.get("/assets/")
        assert response.json()["pagination"]["total"] == 1

        # After soft delete, still exists but inactive
        asset_id = response.json()["items"][0]["id"]
        client.delete(f"/assets/{asset_id}")

        # All assets (including inactive)
        response = client.get("/assets/")
        assert response.json()["pagination"]["total"] == 1
        assert response.json()["items"][0]["is_active"] is False

        # Only active assets
        response = client.get("/assets/", params={"is_active": True})
        assert response.json()["pagination"]["total"] == 0
