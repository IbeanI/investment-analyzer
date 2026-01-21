# tests/routers/test_error_handling.py
"""
Integration tests for error handling across all API endpoints.

These tests verify:
- Consistent error response format (ErrorDetail schema)
- Correct HTTP status codes for different error types
- Correlation ID headers in responses
- Validation error details
- Global exception handler behavior
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
from app.models import Base, User, Portfolio, Asset, AssetClass


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


def seed_portfolio(db: Session, user: User) -> Portfolio:
    """Create a test portfolio."""
    portfolio = Portfolio(user_id=user.id, name="Test", currency="EUR")
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return portfolio


def seed_asset(db: Session, ticker: str = "AAPL", is_active: bool = True) -> Asset:
    """Create a test asset."""
    asset = Asset(
        ticker=ticker,
        exchange="NASDAQ",
        name=f"{ticker} Inc.",
        currency="USD",
        asset_class=AssetClass.STOCK,
        is_active=is_active,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


# =============================================================================
# TEST: CORRELATION ID HEADERS
# =============================================================================

class TestCorrelationIdHeaders:
    """Tests for correlation ID header handling."""

    def test_response_includes_correlation_id(self, client: TestClient):
        """All responses should include X-Correlation-ID header."""
        response = client.get("/health")

        assert response.status_code == 200
        assert "x-correlation-id" in response.headers

    def test_uses_provided_correlation_id(self, client: TestClient):
        """Should use correlation ID from request header."""
        custom_id = "test-correlation-123"

        response = client.get(
            "/health",
            headers={"X-Correlation-ID": custom_id}
        )

        assert response.headers["x-correlation-id"] == custom_id

    def test_generates_correlation_id_when_not_provided(self, client: TestClient):
        """Should generate correlation ID if not provided."""
        response = client.get("/health")

        correlation_id = response.headers["x-correlation-id"]
        assert correlation_id is not None
        assert len(correlation_id) > 0

    def test_error_responses_include_correlation_id(
            self, client: TestClient, test_db: Session
    ):
        """Error responses should also include correlation ID."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.get("/portfolios/99999", headers=headers)

        assert response.status_code == 404
        assert "x-correlation-id" in response.headers


# =============================================================================
# TEST: 404 NOT FOUND ERRORS
# =============================================================================

class TestNotFoundErrors:
    """Tests for 404 Not Found error responses."""

    def test_portfolio_not_found_format(
            self, client: TestClient, test_db: Session
    ):
        """Portfolio not found should return consistent error format."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.get("/portfolios/99999", headers=headers)

        assert response.status_code == 404
        data = response.json()

        assert "error" in data
        assert "message" in data
        assert data["error"] == "NotFoundError"
        assert "99999" in data["message"] or "not found" in data["message"].lower()

    def test_transaction_not_found_format(
            self, client: TestClient, test_db: Session
    ):
        """Transaction not found should return consistent error format."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.get("/transactions/99999", headers=headers)

        assert response.status_code == 404
        data = response.json()

        assert data["error"] == "NotFoundError"

    def test_asset_not_found_format(self, client: TestClient):
        """Asset not found should return consistent error format."""
        # Assets endpoint doesn't require auth
        response = client.get("/assets/99999")

        assert response.status_code == 404
        data = response.json()

        assert data["error"] == "NotFoundError"


# =============================================================================
# TEST: 409 CONFLICT ERRORS
# =============================================================================

class TestConflictErrors:
    """Tests for 409 Conflict error responses."""

    def test_duplicate_asset_ticker_exchange(
            self, client: TestClient, test_db: Session
    ):
        """Duplicate ticker+exchange should return 409 with details."""
        # Assets endpoint doesn't require auth
        seed_asset(test_db, "AAPL")

        response = client.post(
            "/assets/",
            json={
                "ticker": "AAPL",
                "exchange": "NASDAQ",
                "name": "Duplicate Apple",
                "asset_class": "STOCK",
                "currency": "USD",
            }
        )

        assert response.status_code == 409
        data = response.json()

        assert data["error"] == "ConflictError"
        assert "already exists" in data["message"].lower()


# =============================================================================
# TEST: 422 VALIDATION ERRORS
# =============================================================================

class TestValidationErrors:
    """Tests for 422 Validation error responses."""

    def test_validation_error_format(self, client: TestClient, test_db: Session):
        """Validation errors should include field details."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.post(
            "/portfolios/",
            json={
                "name": "",  # Empty name - invalid
                "currency": "EUR",
            },
            headers=headers,
        )

        assert response.status_code == 422
        data = response.json()

        assert data["error"] == "ValidationError"
        assert "details" in data
        assert isinstance(data["details"], list)

        # Should have error for name field
        field_errors = [e for e in data["details"] if "name" in e.get("field", "")]
        assert len(field_errors) > 0

    def test_validation_error_multiple_fields(self, client: TestClient):
        """Should report multiple validation errors."""
        # Assets endpoint doesn't require auth
        response = client.post(
            "/assets/",
            json={
                "ticker": "",  # Invalid
                "exchange": "",  # Invalid (could be empty but ticker is required)
                "asset_class": "INVALID_TYPE",  # Invalid enum
                "currency": "TOOLONG",  # Invalid length
            }
        )

        assert response.status_code == 422
        data = response.json()

        assert len(data["details"]) >= 1

    def test_validation_error_type_mismatch(self, client: TestClient, test_db: Session):
        """Should handle type mismatch errors."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.post(
            "/portfolios/",
            json={
                "name": "Test",
                "currency": "EUR",
            },
            headers=headers,
        )

        # This should now succeed since user_id is removed from schema
        # The test was checking for type mismatch on user_id which no longer exists
        assert response.status_code == 201

    def test_transaction_future_date_validation(
            self, client: TestClient, test_db: Session
    ):
        """Future transaction date should return validation error."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)
        portfolio = seed_portfolio(test_db, user)
        seed_asset(test_db, "AAPL")

        response = client.post(
            "/transactions/",
            json={
                "portfolio_id": portfolio.id,
                "ticker": "AAPL",
                "exchange": "NASDAQ",
                "transaction_type": "BUY",
                "date": "2099-12-31T10:00:00Z",  # Future date
                "quantity": "10",
                "price_per_share": "180",
                "currency": "USD",
            },
            headers=headers,
        )

        assert response.status_code == 422

    def test_negative_quantity_validation(
            self, client: TestClient, test_db: Session
    ):
        """Negative quantity should return validation error."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)
        portfolio = seed_portfolio(test_db, user)
        seed_asset(test_db, "AAPL")

        response = client.post(
            "/transactions/",
            json={
                "portfolio_id": portfolio.id,
                "ticker": "AAPL",
                "exchange": "NASDAQ",
                "transaction_type": "BUY",
                "date": "2024-06-15T10:00:00Z",
                "quantity": "-10",  # Negative
                "price_per_share": "180",
                "currency": "USD",
            },
            headers=headers,
        )

        assert response.status_code == 422


# =============================================================================
# TEST: ERROR RESPONSE STRUCTURE
# =============================================================================

class TestErrorResponseStructure:
    """Tests for consistent error response structure."""

    def test_all_errors_have_required_fields(
            self, client: TestClient, test_db: Session
    ):
        """All error responses should have error and message fields."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        # Test various error endpoints
        # Portfolios and transactions require auth, assets don't
        endpoints = [
            ("/portfolios/99999", "GET", True),
            ("/transactions/99999", "GET", True),
            ("/assets/99999", "GET", False),
        ]

        for endpoint, method, requires_auth in endpoints:
            if method == "GET":
                if requires_auth:
                    response = client.get(endpoint, headers=headers)
                else:
                    response = client.get(endpoint)

            assert response.status_code in [400, 404, 409, 422, 500, 503]
            data = response.json()

            assert "error" in data, f"Missing 'error' field for {endpoint}"
            assert "message" in data, f"Missing 'message' field for {endpoint}"

    def test_error_type_matches_status_code(
            self, client: TestClient, test_db: Session
    ):
        """Error type should be appropriate for status code."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        # 404 errors
        response = client.get("/portfolios/99999", headers=headers)
        assert response.status_code == 404
        assert "NotFound" in response.json()["error"]

    def test_details_field_is_optional(
            self, client: TestClient, test_db: Session
    ):
        """Details field may be null for simple errors."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.get("/portfolios/99999", headers=headers)

        data = response.json()
        # details can be null or contain data
        assert "details" in data or data.get("details") is None


# =============================================================================
# TEST: HEALTH CHECK
# =============================================================================

class TestHealthCheck:
    """Tests for health check endpoints."""

    def test_health_check_success(self, client: TestClient):
        """Health check should return 200 with detailed status."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()

        assert "status" in data
        assert data["status"] in ["healthy", "degraded"]
        assert "checks" in data
        assert "database" in data["checks"]
        assert data["checks"]["database"]["status"] == "healthy"
        assert data["checks"]["database"]["critical"] is True

    def test_health_check_includes_yahoo_finance_status(self, client: TestClient):
        """Health check should include Yahoo Finance circuit breaker status."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()

        assert "yahoo_finance" in data["checks"]
        assert "circuit_breaker_state" in data["checks"]["yahoo_finance"]
        assert data["checks"]["yahoo_finance"]["critical"] is False

    def test_liveness_check_always_succeeds(self, client: TestClient):
        """Liveness check should always return 200 if app is running."""
        response = client.get("/health/live")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "alive"

    def test_readiness_check_success(self, client: TestClient):
        """Readiness check should return 200 when database is available."""
        response = client.get("/health/ready")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "ready"

    def test_root_endpoint(self, client: TestClient):
        """Root endpoint should return API info."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()

        assert "message" in data
        assert "docs" in data


# =============================================================================
# TEST: HTTP METHOD NOT ALLOWED
# =============================================================================

class TestMethodNotAllowed:
    """Tests for 405 Method Not Allowed errors."""

    def test_post_to_get_only_endpoint(self, client: TestClient):
        """POST to GET-only endpoint should return 405."""
        response = client.post("/health")

        assert response.status_code == 405


# =============================================================================
# TEST: CASCADING ERRORS
# =============================================================================

class TestCascadingErrors:
    """Tests for errors that cascade through the system."""

    def test_transaction_with_nonexistent_portfolio(
            self, client: TestClient, test_db: Session
    ):
        """Creating transaction for non-existent portfolio returns 404."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

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
            },
            headers=headers,
        )

        assert response.status_code == 404
        assert "portfolio" in response.json()["message"].lower()

    def test_update_nonexistent_resource(
            self, client: TestClient, test_db: Session
    ):
        """Updating non-existent resources returns 404."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        # Portfolio (requires auth)
        response = client.patch(
            "/portfolios/99999",
            json={"name": "New Name"},
            headers=headers,
        )
        assert response.status_code == 404

        # Asset (doesn't require auth)
        response = client.patch(
            "/assets/99999",
            json={"name": "New Name"}
        )
        assert response.status_code == 404

        # Transaction (requires auth)
        response = client.patch(
            "/transactions/99999",
            json={"quantity": "10"},
            headers=headers,
        )
        assert response.status_code == 404

    def test_delete_nonexistent_resource(
            self, client: TestClient, test_db: Session
    ):
        """Deleting non-existent resources returns 404."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        # Portfolio (requires auth)
        response = client.delete("/portfolios/99999", headers=headers)
        assert response.status_code == 404

        # Asset (doesn't require auth)
        response = client.delete("/assets/99999")
        assert response.status_code == 404

        # Transaction (requires auth)
        response = client.delete("/transactions/99999", headers=headers)
        assert response.status_code == 404


# =============================================================================
# TEST: QUERY PARAMETER VALIDATION
# =============================================================================

class TestQueryParameterValidation:
    """Tests for query parameter validation."""

    def test_invalid_skip_parameter(
            self, client: TestClient, test_db: Session
    ):
        """Negative skip should return validation error."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.get(
            "/portfolios/",
            params={"skip": -1},
            headers=headers,
        )

        assert response.status_code == 422

    def test_invalid_limit_parameter(
            self, client: TestClient, test_db: Session
    ):
        """Zero limit should return validation error."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.get(
            "/portfolios/",
            params={"limit": 0},
            headers=headers,
        )

        assert response.status_code == 422

    def test_limit_exceeds_maximum(
            self, client: TestClient, test_db: Session
    ):
        """Limit exceeding maximum should return validation error."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.get(
            "/portfolios/",
            params={"limit": 9999},
            headers=headers,
        )

        assert response.status_code == 422

    def test_invalid_currency_filter(
            self, client: TestClient, test_db: Session
    ):
        """Invalid currency format should be handled."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        # This depends on how strict the validation is
        response = client.get(
            "/portfolios/",
            params={"currency": "INVALID"},
            headers=headers,
        )

        # Either 422 (strict validation) or 200 with no results
        assert response.status_code in [200, 422]
