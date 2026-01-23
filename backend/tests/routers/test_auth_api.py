# tests/routers/test_auth_api.py
"""
API layer tests for authentication endpoints.

Tests:
- POST /auth/register
- POST /auth/login
- POST /auth/refresh
- POST /auth/logout
- POST /auth/logout/all
- POST /auth/verify-email
- POST /auth/resend-verification
- POST /auth/forgot-password
- POST /auth/reset-password
- GET /auth/me
"""

import os
from unittest.mock import patch, MagicMock

import pytest

# Set required environment variables BEFORE importing app modules
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_NAME", "Test App")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-at-least-32-chars-long")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import get_db
from app.models import Base, User
from app.services.auth.password import PasswordService
from app.services.auth.jwt_handler import JWTHandler


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
# HELPER FUNCTIONS
# =============================================================================


def create_user(
    db: Session,
    email: str = "test@example.com",
    password: str = "password123",
    is_email_verified: bool = True,
    is_active: bool = True,
) -> User:
    """Create a test user."""
    user = User(
        email=email.lower(),
        hashed_password=PasswordService.hash_password(password),
        is_email_verified=is_email_verified,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_auth_headers(user: User) -> dict[str, str]:
    """Generate auth headers for a user."""
    token = JWTHandler.create_access_token(user_id=user.id, email=user.email)
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# TEST: POST /auth/register
# =============================================================================


class TestRegisterEndpoint:
    """Tests for POST /auth/register endpoint."""

    @patch("app.services.auth.service.EmailService")
    def test_register_success(self, mock_email, client: TestClient, test_db: Session):
        """Successful registration should return 201 with user data."""
        response = client.post(
            "/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "securepassword123",
                "full_name": "New User",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert data["full_name"] == "New User"
        assert data["is_email_verified"] is False
        assert "id" in data

    @patch("app.services.auth.service.EmailService")
    def test_register_duplicate_email(
        self, mock_email, client: TestClient, test_db: Session
    ):
        """Registration with existing email should return 409."""
        create_user(test_db, email="existing@example.com")

        response = client.post(
            "/auth/register",
            json={
                "email": "existing@example.com",
                "password": "password123",
            },
        )

        assert response.status_code == 409
        assert "already" in response.json()["message"].lower()

    def test_register_invalid_email(self, client: TestClient):
        """Registration with invalid email should return 422."""
        response = client.post(
            "/auth/register",
            json={
                "email": "not-an-email",
                "password": "password123",
            },
        )

        assert response.status_code == 422

    def test_register_short_password(self, client: TestClient):
        """Registration with short password should return 422."""
        response = client.post(
            "/auth/register",
            json={
                "email": "test@example.com",
                "password": "short",  # Less than 8 chars
            },
        )

        assert response.status_code == 422


# =============================================================================
# TEST: POST /auth/login
# =============================================================================


class TestLoginEndpoint:
    """Tests for POST /auth/login endpoint."""

    def test_login_success(self, client: TestClient, test_db: Session):
        """Successful login should return access token and set refresh token cookie."""
        create_user(test_db, email="test@example.com", password="password123")

        response = client.post(
            "/auth/login",
            json={
                "email": "test@example.com",
                "password": "password123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "expires_in" in data
        # Refresh token should be in httpOnly cookie, not in response body
        assert "refresh_token" not in data
        # Check that refresh_token cookie is set
        assert "refresh_token" in response.cookies

    def test_login_wrong_password(self, client: TestClient, test_db: Session):
        """Login with wrong password should return 401."""
        create_user(test_db, email="test@example.com", password="password123")

        response = client.post(
            "/auth/login",
            json={
                "email": "test@example.com",
                "password": "wrongpassword",
            },
        )

        assert response.status_code == 401

    def test_login_nonexistent_user(self, client: TestClient):
        """Login with non-existent user should return 401."""
        response = client.post(
            "/auth/login",
            json={
                "email": "notexist@example.com",
                "password": "password123",
            },
        )

        assert response.status_code == 401

    def test_login_unverified_email(self, client: TestClient, test_db: Session):
        """Login with unverified email should return 403."""
        create_user(
            test_db,
            email="unverified@example.com",
            password="password123",
            is_email_verified=False,
        )

        response = client.post(
            "/auth/login",
            json={
                "email": "unverified@example.com",
                "password": "password123",
            },
        )

        assert response.status_code == 403
        assert "verified" in response.json()["message"].lower()

    def test_login_inactive_user(self, client: TestClient, test_db: Session):
        """Login with inactive user should return 403."""
        create_user(
            test_db,
            email="inactive@example.com",
            password="password123",
            is_active=False,
        )

        response = client.post(
            "/auth/login",
            json={
                "email": "inactive@example.com",
                "password": "password123",
            },
        )

        assert response.status_code == 403


# =============================================================================
# TEST: POST /auth/refresh
# =============================================================================


class TestRefreshEndpoint:
    """Tests for POST /auth/refresh endpoint."""

    def test_refresh_success(self, client: TestClient, test_db: Session):
        """Successful refresh should return new access token and rotate refresh cookie."""
        create_user(test_db, email="test@example.com", password="password123")

        # Login first - this sets the refresh_token cookie
        login_response = client.post(
            "/auth/login",
            json={"email": "test@example.com", "password": "password123"},
        )
        old_refresh_cookie = login_response.cookies.get("refresh_token")

        # Refresh - cookie is sent automatically by TestClient
        response = client.post("/auth/refresh")

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "expires_in" in data
        # Refresh token should be in cookie, not in response body
        assert "refresh_token" not in data
        # New refresh token cookie should be set (rotation)
        new_refresh_cookie = response.cookies.get("refresh_token")
        assert new_refresh_cookie is not None
        assert new_refresh_cookie != old_refresh_cookie

    def test_refresh_no_cookie(self, client: TestClient):
        """Refresh without cookie should return 401."""
        # Clear any existing cookies
        client.cookies.clear()
        response = client.post("/auth/refresh")

        assert response.status_code == 401

    def test_refresh_invalid_cookie(self, client: TestClient):
        """Refresh with invalid cookie should return 401."""
        client.cookies.set("refresh_token", "invalid-token", path="/auth")
        response = client.post("/auth/refresh")

        assert response.status_code == 401

    def test_refresh_used_token_revoked(self, client: TestClient, test_db: Session):
        """Using already-used refresh token should return 401/403."""
        create_user(test_db, email="test@example.com", password="password123")

        # Login - sets refresh_token cookie
        login_response = client.post(
            "/auth/login",
            json={"email": "test@example.com", "password": "password123"},
        )
        old_refresh_token = login_response.cookies.get("refresh_token")

        # First refresh - success, rotates the token
        first_refresh = client.post("/auth/refresh")
        assert first_refresh.status_code == 200

        # Manually set back the OLD token (simulating replay attack)
        client.cookies.set("refresh_token", old_refresh_token, path="/auth")

        # Second refresh with same token - should fail (replay attack detection)
        response = client.post("/auth/refresh")

        assert response.status_code in [401, 403]


# =============================================================================
# TEST: POST /auth/logout
# =============================================================================


class TestLogoutEndpoint:
    """Tests for POST /auth/logout endpoint."""

    def test_logout_success(self, client: TestClient, test_db: Session):
        """Successful logout should return success message and clear cookie."""
        create_user(test_db, email="test@example.com", password="password123")

        # Login - sets refresh_token cookie
        client.post(
            "/auth/login",
            json={"email": "test@example.com", "password": "password123"},
        )

        # Logout - reads token from cookie
        response = client.post("/auth/logout")

        assert response.status_code == 200
        assert "message" in response.json()
        # Cookie should be cleared (empty or deleted)
        # Note: TestClient may show empty string or missing cookie after delete

    def test_logout_revokes_token(self, client: TestClient, test_db: Session):
        """After logout, refresh token should be invalid."""
        create_user(test_db, email="test@example.com", password="password123")

        # Login - sets refresh_token cookie
        login_response = client.post(
            "/auth/login",
            json={"email": "test@example.com", "password": "password123"},
        )
        old_refresh_token = login_response.cookies.get("refresh_token")

        # Logout - revokes token and clears cookie
        client.post("/auth/logout")

        # Manually set back the OLD token to try to use it
        client.cookies.set("refresh_token", old_refresh_token, path="/auth")

        # Try to refresh with the revoked token
        response = client.post("/auth/refresh")

        assert response.status_code in [401, 403]


# =============================================================================
# TEST: POST /auth/logout/all
# =============================================================================


class TestLogoutAllEndpoint:
    """Tests for POST /auth/logout/all endpoint."""

    def test_logout_all_requires_auth(self, client: TestClient):
        """Logout all should require authentication."""
        response = client.post("/auth/logout/all")

        assert response.status_code == 401

    def test_logout_all_success(self, client: TestClient, test_db: Session):
        """Successful logout all should revoke all sessions."""
        user = create_user(test_db, email="test@example.com", password="password123")
        headers = get_auth_headers(user)

        # Create multiple sessions and store their refresh tokens
        login1 = client.post(
            "/auth/login",
            json={"email": "test@example.com", "password": "password123"},
        )
        token1 = login1.cookies.get("refresh_token")

        login2 = client.post(
            "/auth/login",
            json={"email": "test@example.com", "password": "password123"},
        )
        token2 = login2.cookies.get("refresh_token")

        # Logout all
        response = client.post("/auth/logout/all", headers=headers)

        assert response.status_code == 200
        assert "session" in response.json()["message"].lower()

        # Both refresh tokens should be revoked
        for token in [token1, token2]:
            client.cookies.set("refresh_token", token, path="/auth")
            refresh_response = client.post("/auth/refresh")
            assert refresh_response.status_code in [401, 403]


# =============================================================================
# TEST: GET /auth/me
# =============================================================================


class TestMeEndpoint:
    """Tests for GET /auth/me endpoint."""

    def test_me_requires_auth(self, client: TestClient):
        """Me endpoint should require authentication."""
        response = client.get("/auth/me")

        assert response.status_code == 401

    def test_me_returns_user_profile(self, client: TestClient, test_db: Session):
        """Authenticated request should return user profile."""
        user = create_user(
            test_db,
            email="test@example.com",
            password="password123",
        )
        headers = get_auth_headers(user)

        response = client.get("/auth/me", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@example.com"
        assert data["id"] == user.id
        assert "hashed_password" not in data  # Should not expose password

    def test_me_with_invalid_token(self, client: TestClient):
        """Invalid token should return 401."""
        response = client.get(
            "/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )

        assert response.status_code == 401


# =============================================================================
# TEST: POST /auth/verify-email
# =============================================================================


class TestVerifyEmailEndpoint:
    """Tests for POST /auth/verify-email endpoint."""

    @patch("app.services.auth.email_service.EmailService.validate_verification_token")
    def test_verify_email_success(
        self, mock_validate, client: TestClient, test_db: Session
    ):
        """Successful verification should return success message."""
        user = create_user(test_db, is_email_verified=False)
        mock_validate.return_value = user.email

        response = client.post(
            "/auth/verify-email",
            json={"token": "valid-token"},
        )

        assert response.status_code == 200
        assert "verified" in response.json()["message"].lower()

    @patch("app.services.auth.email_service.EmailService.validate_verification_token")
    def test_verify_email_invalid_token(self, mock_validate, client: TestClient):
        """Invalid token should return 401."""
        from app.services.exceptions import InvalidCredentialsError

        mock_validate.side_effect = InvalidCredentialsError("Invalid token")

        response = client.post(
            "/auth/verify-email",
            json={"token": "invalid-token"},
        )

        assert response.status_code == 401


# =============================================================================
# TEST: POST /auth/forgot-password
# =============================================================================


class TestForgotPasswordEndpoint:
    """Tests for POST /auth/forgot-password endpoint."""

    @patch("app.services.auth.service.EmailService")
    def test_forgot_password_success(
        self, mock_email, client: TestClient, test_db: Session
    ):
        """Forgot password should return success (even for non-existent email)."""
        create_user(test_db, email="test@example.com")

        response = client.post(
            "/auth/forgot-password",
            json={"email": "test@example.com"},
        )

        assert response.status_code == 200
        assert "message" in response.json()

    @patch("app.services.auth.service.EmailService")
    def test_forgot_password_nonexistent_email(self, mock_email, client: TestClient):
        """Non-existent email should still return success (prevent enumeration)."""
        response = client.post(
            "/auth/forgot-password",
            json={"email": "notexist@example.com"},
        )

        # Should return 200 to prevent user enumeration
        assert response.status_code == 200


# =============================================================================
# TEST: POST /auth/reset-password
# =============================================================================


class TestResetPasswordEndpoint:
    """Tests for POST /auth/reset-password endpoint."""

    @patch("app.services.auth.email_service.EmailService.validate_password_reset_token")
    def test_reset_password_success(
        self, mock_validate, client: TestClient, test_db: Session
    ):
        """Successful password reset should return success message."""
        user = create_user(test_db, password="oldpassword")
        mock_validate.return_value = user.email

        response = client.post(
            "/auth/reset-password",
            json={
                "token": "valid-token",
                "new_password": "newpassword123",
            },
        )

        assert response.status_code == 200
        assert "reset" in response.json()["message"].lower()

        # Should be able to login with new password
        login_response = client.post(
            "/auth/login",
            json={"email": user.email, "password": "newpassword123"},
        )
        assert login_response.status_code == 200

    @patch("app.services.auth.email_service.EmailService.validate_password_reset_token")
    def test_reset_password_invalid_token(self, mock_validate, client: TestClient):
        """Invalid token should return 401."""
        from app.services.exceptions import InvalidCredentialsError

        mock_validate.side_effect = InvalidCredentialsError("Invalid token")

        response = client.post(
            "/auth/reset-password",
            json={
                "token": "invalid-token",
                "new_password": "newpassword123",
            },
        )

        assert response.status_code == 401

    def test_reset_password_short_password(self, client: TestClient):
        """Short new password should return 422."""
        response = client.post(
            "/auth/reset-password",
            json={
                "token": "some-token",
                "new_password": "short",  # Less than 8 chars
            },
        )

        assert response.status_code == 422


# =============================================================================
# TEST: OWNERSHIP VERIFICATION (403 FORBIDDEN)
# =============================================================================


class TestOwnershipVerification:
    """Tests for ownership verification on portfolio endpoints."""

    def test_access_own_portfolio_succeeds(self, client: TestClient, test_db: Session):
        """User should be able to access their own portfolio."""
        from app.models import Portfolio

        user = create_user(test_db, email="owner@example.com", password="password123")
        portfolio = Portfolio(user_id=user.id, name="My Portfolio", currency="USD")
        test_db.add(portfolio)
        test_db.commit()
        test_db.refresh(portfolio)

        headers = get_auth_headers(user)
        response = client.get(f"/portfolios/{portfolio.id}", headers=headers)

        assert response.status_code == 200
        assert response.json()["name"] == "My Portfolio"

    def test_access_other_user_portfolio_forbidden(
        self, client: TestClient, test_db: Session
    ):
        """User should not be able to access another user's portfolio."""
        from app.models import Portfolio

        owner = create_user(test_db, email="owner@example.com", password="password123")
        other_user = create_user(
            test_db, email="other@example.com", password="password123"
        )

        portfolio = Portfolio(user_id=owner.id, name="Owner Portfolio", currency="USD")
        test_db.add(portfolio)
        test_db.commit()
        test_db.refresh(portfolio)

        # Other user tries to access owner's portfolio
        headers = get_auth_headers(other_user)
        response = client.get(f"/portfolios/{portfolio.id}", headers=headers)

        assert response.status_code == 403

    def test_access_nonexistent_portfolio_404(
        self, client: TestClient, test_db: Session
    ):
        """Accessing non-existent portfolio should return 404."""
        user = create_user(test_db)
        headers = get_auth_headers(user)

        response = client.get("/portfolios/99999", headers=headers)

        assert response.status_code == 404


# =============================================================================
# TEST: AUTHENTICATION REQUIREMENT
# =============================================================================


class TestAuthenticationRequired:
    """Tests that protected endpoints require authentication."""

    def test_portfolios_list_requires_auth(self, client: TestClient):
        """GET /portfolios/ should require authentication."""
        response = client.get("/portfolios/")
        assert response.status_code == 401

    def test_portfolios_create_requires_auth(self, client: TestClient):
        """POST /portfolios/ should require authentication."""
        response = client.post(
            "/portfolios/",
            json={"name": "Test", "currency": "USD"},
        )
        assert response.status_code == 401

    def test_transactions_list_requires_auth(self, client: TestClient):
        """GET /transactions/ should require authentication."""
        response = client.get("/transactions/")
        assert response.status_code == 401

    def test_valuation_requires_auth(self, client: TestClient, test_db: Session):
        """GET /portfolios/{id}/valuation should require authentication."""
        from app.models import Portfolio

        user = create_user(test_db)
        portfolio = Portfolio(user_id=user.id, name="Test", currency="USD")
        test_db.add(portfolio)
        test_db.commit()

        response = client.get(f"/portfolios/{portfolio.id}/valuation")
        assert response.status_code == 401
