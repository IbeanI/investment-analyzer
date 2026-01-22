# tests/routers/test_portfolios_api.py
"""
Integration tests for Portfolio API endpoints.

These tests verify full HTTP request/response cycles for:
- POST /portfolios/ (Create)
- GET /portfolios/ (List with pagination)
- GET /portfolios/{id} (Read)
- PATCH /portfolios/{id} (Update)
- DELETE /portfolios/{id} (Delete)

Tests validate:
- Correct status codes
- Response structure matches schemas
- Pagination metadata (page, pages, has_next, has_previous)
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
from app.models import Base, User, Portfolio


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

def seed_user(
        db: Session,
        email: str = "test@example.com",
        is_email_verified: bool = True,
        is_active: bool = True,
) -> User:
    """Create a test user with email verified by default."""
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
    """Get authorization headers with JWT token for a user."""
    from app.services.auth.jwt_handler import JWTHandler
    jwt_handler = JWTHandler()
    token = jwt_handler.create_access_token(user_id=user.id, email=user.email)
    return {"Authorization": f"Bearer {token}"}


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


# =============================================================================
# TEST: POST /portfolios/ (Create)
# =============================================================================

class TestCreatePortfolio:
    """Tests for POST /portfolios/ endpoint."""

    def test_create_portfolio_success(self, client: TestClient, test_db: Session):
        """Should create portfolio and return 201."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.post(
            "/portfolios/",
            json={
                "name": "My Retirement Fund",
                "currency": "USD",
            },
            headers=headers,
        )

        assert response.status_code == 201
        data = response.json()

        assert data["name"] == "My Retirement Fund"
        assert data["currency"] == "USD"
        assert data["user_id"] == user.id
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    def test_create_portfolio_normalizes_currency(self, client: TestClient, test_db: Session):
        """Should normalize currency to uppercase."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.post(
            "/portfolios/",
            json={
                "name": "Test",
                "currency": "eur",  # lowercase
            },
            headers=headers,
        )

        assert response.status_code == 201
        assert response.json()["currency"] == "EUR"

    def test_create_portfolio_trims_name(self, client: TestClient, test_db: Session):
        """Should trim whitespace from name."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.post(
            "/portfolios/",
            json={
                "name": "  Trimmed Name  ",
                "currency": "EUR",
            },
            headers=headers,
        )

        assert response.status_code == 201
        assert response.json()["name"] == "Trimmed Name"

    def test_create_portfolio_requires_auth(self, client: TestClient):
        """Should return 401 if not authenticated."""
        response = client.post(
            "/portfolios/",
            json={
                "name": "Test",
                "currency": "EUR",
            }
        )

        assert response.status_code == 401

    def test_create_portfolio_validation_error(self, client: TestClient, test_db: Session):
        """Should return 422 for invalid data."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.post(
            "/portfolios/",
            json={
                "name": "",  # Empty name
                "currency": "EUR",
            },
            headers=headers,
        )

        assert response.status_code == 422
        assert response.json()["error"] == "ValidationError"

    def test_create_portfolio_invalid_currency_length(self, client: TestClient, test_db: Session):
        """Should reject currency that's not 3 characters."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.post(
            "/portfolios/",
            json={
                "name": "Test",
                "currency": "EURO",  # 4 characters
            },
            headers=headers,
        )

        assert response.status_code == 422

    def test_create_portfolio_duplicate_name_conflict(self, client: TestClient, test_db: Session):
        """Should return 409 when creating portfolio with duplicate name for same user."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        # Create first portfolio
        response1 = client.post(
            "/portfolios/",
            json={"name": "My Portfolio", "currency": "EUR"},
            headers=headers,
        )
        assert response1.status_code == 201

        # Try to create duplicate
        response2 = client.post(
            "/portfolios/",
            json={"name": "My Portfolio", "currency": "USD"},  # Same name, different currency
            headers=headers,
        )
        assert response2.status_code == 409
        assert "already exists" in response2.json()["message"]

    def test_create_portfolio_same_name_different_user_allowed(self, client: TestClient, test_db: Session):
        """Different users should be able to create portfolios with same name."""
        user1 = seed_user(test_db, email="user1@example.com")
        user2 = seed_user(test_db, email="user2@example.com")
        headers1 = get_auth_headers(user1)
        headers2 = get_auth_headers(user2)

        # Create portfolio for user 1
        response1 = client.post(
            "/portfolios/",
            json={"name": "My Portfolio", "currency": "EUR"},
            headers=headers1,
        )
        assert response1.status_code == 201

        # Create portfolio with same name for user 2
        response2 = client.post(
            "/portfolios/",
            json={"name": "My Portfolio", "currency": "EUR"},
            headers=headers2,
        )
        assert response2.status_code == 201


# =============================================================================
# TEST: GET /portfolios/ (List)
# =============================================================================

class TestListPortfolios:
    """Tests for GET /portfolios/ endpoint."""

    def test_list_portfolios_empty(self, client: TestClient, test_db: Session):
        """Should return empty list with pagination when no portfolios exist."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.get("/portfolios/", headers=headers)

        assert response.status_code == 200
        data = response.json()

        assert data["items"] == []
        assert "pagination" in data
        assert data["pagination"]["total"] == 0
        assert data["pagination"]["page"] == 1
        assert data["pagination"]["pages"] == 1
        assert data["pagination"]["has_next"] is False
        assert data["pagination"]["has_previous"] is False

    def test_list_portfolios_returns_items(self, client: TestClient, test_db: Session):
        """Should return list of portfolios with pagination metadata."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)
        seed_portfolio(test_db, user, "Portfolio 1", "EUR")
        seed_portfolio(test_db, user, "Portfolio 2", "USD")

        response = client.get("/portfolios/", headers=headers)

        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) == 2
        assert data["pagination"]["total"] == 2
        assert data["pagination"]["page"] == 1
        assert data["pagination"]["pages"] == 1

    def test_list_portfolios_only_returns_own_portfolios(self, client: TestClient, test_db: Session):
        """Should only return portfolios owned by the authenticated user."""
        user1 = seed_user(test_db, "user1@test.com")
        user2 = seed_user(test_db, "user2@test.com")
        headers = get_auth_headers(user1)

        seed_portfolio(test_db, user1, "User1 Portfolio")
        seed_portfolio(test_db, user2, "User2 Portfolio")

        response = client.get("/portfolios/", headers=headers)

        assert response.status_code == 200
        data = response.json()

        # User1 should only see their own portfolio
        assert len(data["items"]) == 1
        assert data["items"][0]["name"] == "User1 Portfolio"
        assert data["pagination"]["total"] == 1

    def test_list_portfolios_filter_by_currency(self, client: TestClient, test_db: Session):
        """Should filter portfolios by currency."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)
        seed_portfolio(test_db, user, "EUR Portfolio", "EUR")
        seed_portfolio(test_db, user, "USD Portfolio", "USD")

        response = client.get("/portfolios/", params={"currency": "EUR"}, headers=headers)

        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) == 1
        assert data["items"][0]["currency"] == "EUR"

    def test_list_portfolios_search(self, client: TestClient, test_db: Session):
        """Should search portfolios by name."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)
        seed_portfolio(test_db, user, "Retirement Fund", "EUR")
        seed_portfolio(test_db, user, "Trading Account", "USD")

        response = client.get("/portfolios/", params={"search": "Retire"}, headers=headers)

        assert response.status_code == 200
        data = response.json()

        assert len(data["items"]) == 1
        assert "Retirement" in data["items"][0]["name"]

    def test_list_portfolios_pagination(self, client: TestClient, test_db: Session):
        """Should paginate results correctly."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)
        for i in range(15):
            seed_portfolio(test_db, user, f"Portfolio {i}", "EUR")

        # First page
        response = client.get("/portfolios/", params={"skip": 0, "limit": 10}, headers=headers)
        data = response.json()

        assert len(data["items"]) == 10
        assert data["pagination"]["total"] == 15
        assert data["pagination"]["page"] == 1
        assert data["pagination"]["pages"] == 2
        assert data["pagination"]["has_next"] is True
        assert data["pagination"]["has_previous"] is False

        # Second page
        response = client.get("/portfolios/", params={"skip": 10, "limit": 10}, headers=headers)
        data = response.json()

        assert len(data["items"]) == 5
        assert data["pagination"]["page"] == 2
        assert data["pagination"]["has_next"] is False
        assert data["pagination"]["has_previous"] is True

    def test_list_portfolios_requires_auth(self, client: TestClient):
        """Should return 401 if not authenticated."""
        response = client.get("/portfolios/")
        assert response.status_code == 401


# =============================================================================
# TEST: GET /portfolios/{id} (Read)
# =============================================================================

class TestGetPortfolio:
    """Tests for GET /portfolios/{id} endpoint."""

    def test_get_portfolio_success(self, client: TestClient, test_db: Session):
        """Should return portfolio with 200."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)
        portfolio = seed_portfolio(test_db, user, "My Portfolio", "EUR")

        response = client.get(f"/portfolios/{portfolio.id}", headers=headers)

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == portfolio.id
        assert data["name"] == "My Portfolio"
        assert data["currency"] == "EUR"
        assert data["user_id"] == user.id

    def test_get_portfolio_not_found(self, client: TestClient, test_db: Session):
        """Should return 404 for non-existent portfolio."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.get("/portfolios/99999", headers=headers)

        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "NotFoundError"

    def test_get_portfolio_forbidden_if_not_owner(self, client: TestClient, test_db: Session):
        """Should return 403 if user doesn't own the portfolio."""
        user1 = seed_user(test_db, "user1@test.com")
        user2 = seed_user(test_db, "user2@test.com")
        portfolio = seed_portfolio(test_db, user1, "User1 Portfolio")
        headers = get_auth_headers(user2)

        response = client.get(f"/portfolios/{portfolio.id}", headers=headers)

        assert response.status_code == 403

    def test_get_portfolio_requires_auth(self, client: TestClient, test_db: Session):
        """Should return 401 if not authenticated."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user, "My Portfolio")

        response = client.get(f"/portfolios/{portfolio.id}")

        assert response.status_code == 401


# =============================================================================
# TEST: PATCH /portfolios/{id} (Update)
# =============================================================================

class TestUpdatePortfolio:
    """Tests for PATCH /portfolios/{id} endpoint."""

    def test_update_portfolio_name(self, client: TestClient, test_db: Session):
        """Should update portfolio name."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)
        portfolio = seed_portfolio(test_db, user, "Old Name", "EUR")

        response = client.patch(
            f"/portfolios/{portfolio.id}",
            json={"name": "New Name"},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Name"
        assert data["currency"] == "EUR"  # Unchanged

    def test_update_portfolio_currency(self, client: TestClient, test_db: Session):
        """Should update portfolio currency."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)
        portfolio = seed_portfolio(test_db, user, "Test", "EUR")

        response = client.patch(
            f"/portfolios/{portfolio.id}",
            json={"currency": "USD"},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["currency"] == "USD"

    def test_update_portfolio_partial(self, client: TestClient, test_db: Session):
        """Should only update provided fields."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)
        portfolio = seed_portfolio(test_db, user, "Original Name", "EUR")

        response = client.patch(
            f"/portfolios/{portfolio.id}",
            json={"name": "Updated Name"},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"
        assert data["currency"] == "EUR"  # Not changed

    def test_update_portfolio_not_found(self, client: TestClient, test_db: Session):
        """Should return 404 for non-existent portfolio."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.patch(
            "/portfolios/99999",
            json={"name": "Test"},
            headers=headers,
        )

        assert response.status_code == 404

    def test_update_portfolio_normalizes_currency(self, client: TestClient, test_db: Session):
        """Should normalize currency to uppercase."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)
        portfolio = seed_portfolio(test_db, user, "Test", "EUR")

        response = client.patch(
            f"/portfolios/{portfolio.id}",
            json={"currency": "usd"},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["currency"] == "USD"

    def test_update_portfolio_requires_auth(self, client: TestClient, test_db: Session):
        """Should return 401 if not authenticated."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user, "Test", "EUR")

        response = client.patch(
            f"/portfolios/{portfolio.id}",
            json={"name": "Test"},
        )

        assert response.status_code == 401

    def test_update_portfolio_duplicate_name_conflict(self, client: TestClient, test_db: Session):
        """Should return 409 when renaming to existing portfolio name."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)
        portfolio1 = seed_portfolio(test_db, user, "Portfolio 1", "EUR")
        portfolio2 = seed_portfolio(test_db, user, "Portfolio 2", "EUR")

        # Try to rename portfolio2 to portfolio1's name
        response = client.patch(
            f"/portfolios/{portfolio2.id}",
            json={"name": "Portfolio 1"},
            headers=headers,
        )

        assert response.status_code == 409
        assert "already exists" in response.json()["message"]

    def test_update_portfolio_same_name_unchanged_allowed(self, client: TestClient, test_db: Session):
        """Should allow updating without changing name (no conflict with self)."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)
        portfolio = seed_portfolio(test_db, user, "My Portfolio", "EUR")

        # Update only currency, keeping same name
        response = client.patch(
            f"/portfolios/{portfolio.id}",
            json={"name": "My Portfolio", "currency": "USD"},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["name"] == "My Portfolio"
        assert response.json()["currency"] == "USD"


# =============================================================================
# TEST: DELETE /portfolios/{id}
# =============================================================================

class TestDeletePortfolio:
    """Tests for DELETE /portfolios/{id} endpoint."""

    def test_delete_portfolio_success(self, client: TestClient, test_db: Session):
        """Should delete portfolio and return 204."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)
        portfolio = seed_portfolio(test_db, user, "To Delete", "EUR")

        response = client.delete(f"/portfolios/{portfolio.id}", headers=headers)

        assert response.status_code == 204

        # Verify deleted
        get_response = client.get(f"/portfolios/{portfolio.id}", headers=headers)
        assert get_response.status_code == 404

    def test_delete_portfolio_not_found(self, client: TestClient, test_db: Session):
        """Should return 404 for non-existent portfolio."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.delete("/portfolios/99999", headers=headers)

        assert response.status_code == 404

    def test_delete_portfolio_requires_auth(self, client: TestClient, test_db: Session):
        """Should return 401 if not authenticated."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user, "Test", "EUR")

        response = client.delete(f"/portfolios/{portfolio.id}")

        assert response.status_code == 401


# =============================================================================
# TEST: FULL CRUD FLOW
# =============================================================================

class TestPortfolioCRUDFlow:
    """Integration tests for complete CRUD lifecycle."""

    def test_full_crud_lifecycle(self, client: TestClient, test_db: Session):
        """Test complete Create -> Read -> Update -> Delete flow."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        # CREATE
        create_response = client.post(
            "/portfolios/",
            json={
                "name": "Lifecycle Test",
                "currency": "EUR",
            },
            headers=headers,
        )
        assert create_response.status_code == 201
        portfolio_id = create_response.json()["id"]

        # READ
        read_response = client.get(f"/portfolios/{portfolio_id}", headers=headers)
        assert read_response.status_code == 200
        assert read_response.json()["name"] == "Lifecycle Test"

        # UPDATE
        update_response = client.patch(
            f"/portfolios/{portfolio_id}",
            json={"name": "Updated Lifecycle Test", "currency": "USD"},
            headers=headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "Updated Lifecycle Test"
        assert update_response.json()["currency"] == "USD"

        # Verify update persisted
        verify_response = client.get(f"/portfolios/{portfolio_id}", headers=headers)
        assert verify_response.json()["name"] == "Updated Lifecycle Test"

        # DELETE
        delete_response = client.delete(f"/portfolios/{portfolio_id}", headers=headers)
        assert delete_response.status_code == 204

        # Verify deleted
        final_response = client.get(f"/portfolios/{portfolio_id}", headers=headers)
        assert final_response.status_code == 404

    def test_list_reflects_crud_operations(self, client: TestClient, test_db: Session):
        """List endpoint should reflect all CRUD operations."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        # Initially empty
        response = client.get("/portfolios/", headers=headers)
        assert response.json()["pagination"]["total"] == 0

        # Create
        create_response = client.post(
            "/portfolios/",
            json={"name": "Test", "currency": "EUR"},
            headers=headers,
        )
        portfolio_id = create_response.json()["id"]

        response = client.get("/portfolios/", headers=headers)
        assert response.json()["pagination"]["total"] == 1

        # Delete
        client.delete(f"/portfolios/{portfolio_id}", headers=headers)

        response = client.get("/portfolios/", headers=headers)
        assert response.json()["pagination"]["total"] == 0
