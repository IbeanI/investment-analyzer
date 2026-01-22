# tests/routers/test_oauth_api.py
"""
API layer tests for Google OAuth endpoints.

Tests:
- GET /auth/google - Get Google OAuth authorization URL
- GET /auth/google/callback - Handle Google OAuth callback

These tests verify the OAuth flow with mocked Google API responses.
"""

import os
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock
from datetime import datetime, timezone

import pytest

# Set required environment variables BEFORE importing app modules
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["APP_NAME"] = "Test App"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-at-least-32-chars-long"
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import get_db
from app.models import Base, User
from app.services.auth.oauth_google import GoogleUserInfo, OAuthStateStore, get_oauth_state_store


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


@pytest.fixture(autouse=True)
def reset_oauth_state_store():
    """Reset OAuth state store before each test."""
    store = get_oauth_state_store()
    with store._lock:
        store._states.clear()
    yield


@pytest.fixture(scope="function")
def client(test_db: Session) -> TestClient:
    """Create TestClient with database override and mocked OAuth config."""

    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    # Patch settings to indicate Google OAuth is configured
    with patch("app.services.auth.oauth_google.settings") as mock_settings:
        mock_settings.is_google_oauth_configured = True
        mock_settings.google_client_id = "test-client-id"
        mock_settings.google_client_secret = "test-client-secret"
        mock_settings.google_redirect_uri = "http://localhost:8000/auth/google/callback"

        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def seed_user(
    db: Session,
    email: str = "oauth@example.com",
    oauth_provider: str = "google",
    oauth_provider_id: str = "google-123",
) -> User:
    """Create a test user with OAuth."""
    user = User(
        email=email,
        oauth_provider=oauth_provider,
        oauth_provider_id=oauth_provider_id,
        is_email_verified=True,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# =============================================================================
# TEST: GET /auth/google
# =============================================================================

class TestGetGoogleAuthUrl:
    """Tests for GET /auth/google endpoint."""

    def test_get_auth_url_success(self, client: TestClient):
        """Should return authorization URL with state parameter."""
        response = client.get("/auth/google")

        assert response.status_code == 200
        data = response.json()
        assert "authorization_url" in data
        assert "state" in data
        assert "accounts.google.com" in data["authorization_url"]
        assert data["state"] in data["authorization_url"]

    def test_get_auth_url_stores_state(self, client: TestClient):
        """Should store state in OAuth state store for CSRF validation."""
        response = client.get("/auth/google")

        assert response.status_code == 200
        state = response.json()["state"]

        # Verify state was stored
        store = get_oauth_state_store()
        with store._lock:
            assert state in store._states

    def test_get_auth_url_unique_states(self, client: TestClient):
        """Should generate unique states for each request."""
        response1 = client.get("/auth/google")
        response2 = client.get("/auth/google")

        state1 = response1.json()["state"]
        state2 = response2.json()["state"]

        assert state1 != state2


# =============================================================================
# TEST: GET /auth/google/callback
# =============================================================================

class TestGoogleCallback:
    """Tests for GET /auth/google/callback endpoint."""

    @patch("app.routers.auth.GoogleOAuthService.exchange_code_for_tokens")
    @patch("app.routers.auth.GoogleOAuthService.get_user_info")
    def test_callback_creates_new_user(
        self,
        mock_get_user_info: AsyncMock,
        mock_exchange_code: AsyncMock,
        client: TestClient,
        test_db: Session,
    ):
        """Should create new user on first OAuth login."""
        # Setup: Get a valid state
        auth_response = client.get("/auth/google")
        valid_state = auth_response.json()["state"]

        # Mock Google responses
        mock_exchange_code.return_value = {"access_token": "google-access-token"}
        mock_get_user_info.return_value = GoogleUserInfo(
            id="google-new-user-123",
            email="newuser@gmail.com",
            verified_email=True,
            name="New User",
            picture="https://example.com/photo.jpg",
        )

        response = client.get(
            "/auth/google/callback",
            params={"code": "google-auth-code", "state": valid_state},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

        # Verify user was created
        user = test_db.query(User).filter(User.email == "newuser@gmail.com").first()
        assert user is not None
        assert user.oauth_provider == "google"
        assert user.oauth_provider_id == "google-new-user-123"
        assert user.full_name == "New User"
        assert user.is_email_verified is True

    @patch("app.routers.auth.GoogleOAuthService.exchange_code_for_tokens")
    @patch("app.routers.auth.GoogleOAuthService.get_user_info")
    def test_callback_logs_in_existing_user(
        self,
        mock_get_user_info: AsyncMock,
        mock_exchange_code: AsyncMock,
        client: TestClient,
        test_db: Session,
    ):
        """Should log in existing OAuth user."""
        # Setup: Create existing user
        existing_user = seed_user(
            test_db,
            email="existing@gmail.com",
            oauth_provider="google",
            oauth_provider_id="google-existing-123",
        )

        # Get valid state
        auth_response = client.get("/auth/google")
        valid_state = auth_response.json()["state"]

        # Mock Google responses
        mock_exchange_code.return_value = {"access_token": "google-access-token"}
        mock_get_user_info.return_value = GoogleUserInfo(
            id="google-existing-123",
            email="existing@gmail.com",
            verified_email=True,
            name="Existing User",
        )

        response = client.get(
            "/auth/google/callback",
            params={"code": "google-auth-code", "state": valid_state},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data

        # Verify no new user was created
        user_count = test_db.query(User).filter(User.email == "existing@gmail.com").count()
        assert user_count == 1

    @patch("app.routers.auth.GoogleOAuthService.exchange_code_for_tokens")
    @patch("app.routers.auth.GoogleOAuthService.get_user_info")
    def test_callback_links_oauth_to_existing_email_user(
        self,
        mock_get_user_info: AsyncMock,
        mock_exchange_code: AsyncMock,
        client: TestClient,
        test_db: Session,
    ):
        """Should link OAuth to existing email/password user."""
        # Setup: Create existing user with email/password
        existing_user = User(
            email="user@gmail.com",
            hashed_password="hashed-password",
            is_email_verified=True,
            is_active=True,
        )
        test_db.add(existing_user)
        test_db.commit()

        # Get valid state
        auth_response = client.get("/auth/google")
        valid_state = auth_response.json()["state"]

        # Mock Google responses with same email
        mock_exchange_code.return_value = {"access_token": "google-access-token"}
        mock_get_user_info.return_value = GoogleUserInfo(
            id="google-new-id-456",
            email="user@gmail.com",
            verified_email=True,
            name="User Name",
        )

        response = client.get(
            "/auth/google/callback",
            params={"code": "google-auth-code", "state": valid_state},
        )

        assert response.status_code == 200

        # Verify OAuth was linked to existing user
        test_db.refresh(existing_user)
        assert existing_user.oauth_provider == "google"
        assert existing_user.oauth_provider_id == "google-new-id-456"

    def test_callback_invalid_state_rejected(self, client: TestClient):
        """Should reject callback with invalid state (CSRF protection)."""
        response = client.get(
            "/auth/google/callback",
            params={"code": "google-auth-code", "state": "invalid-state"},
        )

        assert response.status_code == 400
        assert "state" in response.json()["message"].lower()

    def test_callback_missing_state_rejected(self, client: TestClient):
        """Should reject callback with missing state."""
        response = client.get(
            "/auth/google/callback",
            params={"code": "google-auth-code"},
        )

        assert response.status_code == 422  # Validation error

    def test_callback_missing_code_rejected(self, client: TestClient):
        """Should reject callback with missing code."""
        auth_response = client.get("/auth/google")
        valid_state = auth_response.json()["state"]

        response = client.get(
            "/auth/google/callback",
            params={"state": valid_state},
        )

        assert response.status_code == 422  # Validation error

    def test_callback_state_consumed_after_use(self, client: TestClient):
        """Should consume state after successful validation (one-time use)."""
        # Get valid state
        auth_response = client.get("/auth/google")
        valid_state = auth_response.json()["state"]

        # Consume the state
        store = get_oauth_state_store()
        store.validate_and_consume(valid_state)

        # Attempt to use the same state again
        response = client.get(
            "/auth/google/callback",
            params={"code": "google-auth-code", "state": valid_state},
        )

        assert response.status_code == 400
        assert "state" in response.json()["message"].lower()

    @patch("app.routers.auth.GoogleOAuthService.exchange_code_for_tokens")
    def test_callback_handles_token_exchange_failure(
        self,
        mock_exchange_code: AsyncMock,
        client: TestClient,
    ):
        """Should handle failure when exchanging code for tokens."""
        # Get valid state
        auth_response = client.get("/auth/google")
        valid_state = auth_response.json()["state"]

        # Mock failed token exchange
        mock_exchange_code.return_value = {}  # No access_token

        response = client.get(
            "/auth/google/callback",
            params={"code": "invalid-code", "state": valid_state},
        )

        assert response.status_code == 400
        assert "access token" in response.json()["message"].lower()
