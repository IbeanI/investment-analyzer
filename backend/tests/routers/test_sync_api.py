# tests/routers/test_sync_api.py
"""
API layer tests for market data sync endpoints.

Tests:
- POST /portfolios/{id}/sync - Sync portfolio market data
- GET /portfolios/{id}/sync/status - Get sync status

These tests verify the HTTP layer using FastAPI's TestClient with
mocked sync service to avoid actual Yahoo Finance calls.
"""

import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_NAME", "Test App")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-at-least-32-chars-long")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import get_db
from app.models import Base, User, Portfolio, SyncStatus, SyncStatusEnum
from app.services.auth.jwt_handler import JWTHandler
from app.services.market_data.sync_service import SyncResult
from app.dependencies import get_sync_service


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
    """Create a database session."""
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def mock_sync_service():
    """Create a mock sync service."""
    service = MagicMock()
    service.sync_portfolio.return_value = SyncResult(
        portfolio_id=1,
        status="completed",
        sync_started=datetime.now(timezone.utc),
        sync_completed=datetime.now(timezone.utc),
        assets_synced=3,
        assets_failed=0,
        prices_fetched=750,
        fx_pairs_synced=2,
        fx_rates_fetched=500,
        warnings=[],
        error=None,
    )
    service.is_data_stale.return_value = (False, None)
    return service


@pytest.fixture(scope="function")
def client(test_db: Session, mock_sync_service) -> TestClient:
    """Create TestClient with database and service overrides."""

    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    def override_get_sync_service():
        return mock_sync_service

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_sync_service] = override_get_sync_service

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def seed_user(db: Session, email: str = "test@example.com") -> User:
    """Create a test user."""
    user = User(
        email=email,
        hashed_password="hashed",
        is_email_verified=True,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def seed_portfolio(db: Session, user: User, name: str = "Test Portfolio") -> Portfolio:
    """Create a test portfolio."""
    portfolio = Portfolio(user_id=user.id, name=name, currency="EUR")
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return portfolio


def get_auth_headers(user: User) -> dict[str, str]:
    """Get authorization headers with JWT token."""
    jwt_handler = JWTHandler()
    token = jwt_handler.create_access_token(user_id=user.id, email=user.email)
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# TEST: POST /portfolios/{id}/sync
# =============================================================================

class TestSyncPortfolio:
    """Tests for POST /portfolios/{id}/sync endpoint."""

    def test_sync_portfolio_success(self, client: TestClient, test_db: Session, mock_sync_service):
        """Should sync portfolio and return success response."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        headers = get_auth_headers(user)

        response = client.post(f"/portfolios/{portfolio.id}/sync", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["portfolio_id"] == portfolio.id
        assert data["status"] == "completed"
        assert data["assets_synced"] == 3
        assert data["prices_fetched"] == 750
        mock_sync_service.sync_portfolio.assert_called_once()

    def test_sync_portfolio_with_force_refresh(self, client: TestClient, test_db: Session, mock_sync_service):
        """Should pass force_refresh flag to service."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        headers = get_auth_headers(user)

        response = client.post(
            f"/portfolios/{portfolio.id}/sync",
            json={"force_refresh": True},
            headers=headers
        )

        assert response.status_code == 200
        call_kwargs = mock_sync_service.sync_portfolio.call_args.kwargs
        assert call_kwargs["force"] is True

    def test_sync_portfolio_partial_success(self, client: TestClient, test_db: Session, mock_sync_service):
        """Should return partial success when some assets fail."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        headers = get_auth_headers(user)

        mock_sync_service.sync_portfolio.return_value = SyncResult(
            portfolio_id=portfolio.id,
            status="partial",
            sync_started=datetime.now(timezone.utc),
            sync_completed=datetime.now(timezone.utc),
            assets_synced=2,
            assets_failed=1,
            prices_fetched=500,
            fx_pairs_synced=2,
            fx_rates_fetched=500,
            warnings=["Failed to sync DELISTED: Ticker not found"],
            error=None,
        )

        response = client.post(f"/portfolios/{portfolio.id}/sync", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True  # partial is still success
        assert data["status"] == "partial"
        assert data["assets_failed"] == 1
        assert len(data["warnings"]) == 1

    def test_sync_portfolio_requires_auth(self, client: TestClient, test_db: Session):
        """Should return 401 when not authenticated."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)

        response = client.post(f"/portfolios/{portfolio.id}/sync")

        assert response.status_code == 401

    def test_sync_portfolio_not_found(self, client: TestClient, test_db: Session):
        """Should return 404 when portfolio doesn't exist."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.post("/portfolios/99999/sync", headers=headers)

        assert response.status_code == 404

    def test_sync_portfolio_forbidden(self, client: TestClient, test_db: Session):
        """Should return 403 when user doesn't own portfolio."""
        user1 = seed_user(test_db, email="user1@example.com")
        user2 = seed_user(test_db, email="user2@example.com")
        portfolio = seed_portfolio(test_db, user1)
        headers = get_auth_headers(user2)

        response = client.post(f"/portfolios/{portfolio.id}/sync", headers=headers)

        assert response.status_code == 403


# =============================================================================
# TEST: GET /portfolios/{id}/sync/status
# =============================================================================

class TestGetSyncStatus:
    """Tests for GET /portfolios/{id}/sync/status endpoint."""

    def test_get_sync_status_never_synced(self, client: TestClient, test_db: Session):
        """Should return NEVER status when portfolio has no sync history."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        headers = get_auth_headers(user)

        response = client.get(f"/portfolios/{portfolio.id}/sync/status", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["portfolio_id"] == portfolio.id
        assert data["status"] == "NEVER"
        assert data["is_stale"] is True
        assert data["staleness_reason"] == "Portfolio has never been synced"

    def test_get_sync_status_completed(self, client: TestClient, test_db: Session, mock_sync_service):
        """Should return sync status with timestamps."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        headers = get_auth_headers(user)

        # Create sync status record
        sync_status = SyncStatus(
            portfolio_id=portfolio.id,
            status=SyncStatusEnum.COMPLETED,
            last_sync_started=datetime.now(timezone.utc),
            last_sync_completed=datetime.now(timezone.utc),
        )
        test_db.add(sync_status)
        test_db.commit()

        response = client.get(f"/portfolios/{portfolio.id}/sync/status", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "COMPLETED"
        assert data["last_sync_started"] is not None
        assert data["last_sync_completed"] is not None

    def test_get_sync_status_stale(self, client: TestClient, test_db: Session, mock_sync_service):
        """Should indicate when data is stale."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        headers = get_auth_headers(user)

        mock_sync_service.is_data_stale.return_value = (True, "Last sync was more than 24 hours ago")

        sync_status = SyncStatus(
            portfolio_id=portfolio.id,
            status=SyncStatusEnum.COMPLETED,
        )
        test_db.add(sync_status)
        test_db.commit()

        response = client.get(f"/portfolios/{portfolio.id}/sync/status", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["is_stale"] is True
        assert "24 hours" in data["staleness_reason"]

    def test_get_sync_status_requires_auth(self, client: TestClient, test_db: Session):
        """Should return 401 when not authenticated."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)

        response = client.get(f"/portfolios/{portfolio.id}/sync/status")

        assert response.status_code == 401

    def test_get_sync_status_not_found(self, client: TestClient, test_db: Session):
        """Should return 404 when portfolio doesn't exist."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.get("/portfolios/99999/sync/status", headers=headers)

        assert response.status_code == 404

    def test_get_sync_status_forbidden(self, client: TestClient, test_db: Session):
        """Should return 403 when user doesn't own portfolio."""
        user1 = seed_user(test_db, email="user1@example.com")
        user2 = seed_user(test_db, email="user2@example.com")
        portfolio = seed_portfolio(test_db, user1)
        headers = get_auth_headers(user2)

        response = client.get(f"/portfolios/{portfolio.id}/sync/status", headers=headers)

        assert response.status_code == 403
