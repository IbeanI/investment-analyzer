# tests/services/auth/test_auth_service.py
"""
Tests for the core authentication service.

Tests:
- User registration
- Login (email/password)
- Token refresh with rotation
- Logout (single and all sessions)
- Email verification
- Password reset
- Replay attack detection
"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

# Set required environment variables BEFORE importing app modules
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_NAME", "Test App")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-at-least-32-chars-long")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, User, RefreshToken
from app.services.auth.service import AuthService, TokenPair
from app.services.auth.password import PasswordService
from app.services.auth.email_service import EmailService
from app.services.exceptions import (
    UserExistsError,
    InvalidCredentialsError,
    EmailNotVerifiedError,
    TokenExpiredError,
    TokenRevokedError,
    UserNotFoundError,
    UserInactiveError,
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
def db(test_engine) -> Session:
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
def mock_email_service():
    """Create a mock email service."""
    mock = MagicMock(spec=EmailService)
    mock.send_verification_email.return_value = True
    mock.send_password_reset_email.return_value = True
    mock.generate_verification_token.return_value = "test-verification-token"
    mock.generate_password_reset_token.return_value = "test-reset-token"
    return mock


@pytest.fixture
def auth_service(mock_email_service):
    """Create auth service with mocked email service."""
    return AuthService(email_service=mock_email_service)


def create_verified_user(
    db: Session,
    email: str = "test@example.com",
    password: str = "password123",
) -> User:
    """Create a verified user for testing."""
    user = User(
        email=email.lower(),
        hashed_password=PasswordService.hash_password(password),
        is_email_verified=True,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_unverified_user(
    db: Session,
    email: str = "unverified@example.com",
    password: str = "password123",
) -> User:
    """Create an unverified user for testing."""
    user = User(
        email=email.lower(),
        hashed_password=PasswordService.hash_password(password),
        is_email_verified=False,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# =============================================================================
# TEST: USER REGISTRATION
# =============================================================================


class TestRegistration:
    """Tests for user registration."""

    def test_register_creates_user(self, db: Session, auth_service: AuthService):
        """Registration should create a new user."""
        user = auth_service.register(
            db=db,
            email="new@example.com",
            password="securepassword123",
            full_name="New User",
        )

        assert user.id is not None
        assert user.email == "new@example.com"
        assert user.full_name == "New User"
        assert user.is_email_verified is False
        assert user.is_active is True

    def test_register_normalizes_email(self, db: Session, auth_service: AuthService):
        """Registration should normalize email to lowercase."""
        user = auth_service.register(
            db=db,
            email="Test@Example.COM",
            password="password123",
        )

        assert user.email == "test@example.com"

    def test_register_hashes_password(self, db: Session, auth_service: AuthService):
        """Registration should hash the password."""
        password = "plainpassword123"
        user = auth_service.register(
            db=db,
            email="test@example.com",
            password=password,
        )

        assert user.hashed_password != password
        assert user.hashed_password.startswith("$2b$")
        assert PasswordService.verify_password(password, user.hashed_password)

    def test_register_sends_verification_email(
        self, db: Session, auth_service: AuthService, mock_email_service
    ):
        """Registration should send verification email."""
        auth_service.register(
            db=db,
            email="test@example.com",
            password="password123",
        )

        mock_email_service.generate_verification_token.assert_called_once()
        mock_email_service.send_verification_email.assert_called_once()

    def test_register_duplicate_email_raises_error(
        self, db: Session, auth_service: AuthService
    ):
        """Registration with existing email should raise UserExistsError."""
        auth_service.register(db=db, email="test@example.com", password="password123")

        with pytest.raises(UserExistsError):
            auth_service.register(
                db=db, email="test@example.com", password="otherpassword"
            )

    def test_register_duplicate_email_case_insensitive(
        self, db: Session, auth_service: AuthService
    ):
        """Duplicate check should be case-insensitive."""
        auth_service.register(db=db, email="test@example.com", password="password123")

        with pytest.raises(UserExistsError):
            auth_service.register(
                db=db, email="TEST@Example.COM", password="otherpassword"
            )


# =============================================================================
# TEST: LOGIN
# =============================================================================


class TestLogin:
    """Tests for user login."""

    def test_login_success_returns_tokens(self, db: Session, auth_service: AuthService):
        """Successful login should return access and refresh tokens."""
        create_verified_user(db, email="test@example.com", password="password123")

        tokens = auth_service.login(
            db=db,
            email="test@example.com",
            password="password123",
        )

        assert isinstance(tokens, TokenPair)
        assert tokens.access_token is not None
        assert tokens.refresh_token is not None
        assert tokens.token_type == "bearer"

    def test_login_wrong_email_raises_error(
        self, db: Session, auth_service: AuthService
    ):
        """Login with wrong email should raise InvalidCredentialsError."""
        create_verified_user(db)

        with pytest.raises(InvalidCredentialsError):
            auth_service.login(
                db=db,
                email="wrong@example.com",
                password="password123",
            )

    def test_login_wrong_password_raises_error(
        self, db: Session, auth_service: AuthService
    ):
        """Login with wrong password should raise InvalidCredentialsError."""
        create_verified_user(db, email="test@example.com", password="password123")

        with pytest.raises(InvalidCredentialsError):
            auth_service.login(
                db=db,
                email="test@example.com",
                password="wrongpassword",
            )

    def test_login_unverified_email_raises_error(
        self, db: Session, auth_service: AuthService
    ):
        """Login with unverified email should raise EmailNotVerifiedError."""
        create_unverified_user(db, email="unverified@example.com", password="password123")

        with pytest.raises(EmailNotVerifiedError):
            auth_service.login(
                db=db,
                email="unverified@example.com",
                password="password123",
            )

    def test_login_inactive_user_raises_error(
        self, db: Session, auth_service: AuthService
    ):
        """Login with inactive user should raise UserInactiveError."""
        user = create_verified_user(db)
        user.is_active = False
        db.commit()

        with pytest.raises(UserInactiveError):
            auth_service.login(
                db=db,
                email=user.email,
                password="password123",
            )

    def test_login_stores_refresh_token(self, db: Session, auth_service: AuthService):
        """Login should store refresh token in database."""
        user = create_verified_user(db)

        tokens = auth_service.login(db=db, email=user.email, password="password123")

        # Check refresh token is stored
        stored_tokens = db.query(RefreshToken).filter_by(user_id=user.id).all()
        assert len(stored_tokens) == 1
        assert stored_tokens[0].revoked_at is None

    def test_login_is_case_insensitive(self, db: Session, auth_service: AuthService):
        """Login email should be case-insensitive."""
        create_verified_user(db, email="test@example.com", password="password123")

        # Should succeed with different case
        tokens = auth_service.login(
            db=db,
            email="TEST@Example.COM",
            password="password123",
        )

        assert tokens.access_token is not None


# =============================================================================
# TEST: TOKEN REFRESH
# =============================================================================


class TestTokenRefresh:
    """Tests for token refresh functionality."""

    def test_refresh_returns_new_tokens(self, db: Session, auth_service: AuthService):
        """Refresh should return new access and refresh tokens."""
        user = create_verified_user(db)
        tokens = auth_service.login(db=db, email=user.email, password="password123")

        new_tokens = auth_service.refresh_tokens(
            db=db,
            refresh_token=tokens.refresh_token,
        )

        assert new_tokens.access_token is not None
        assert new_tokens.refresh_token is not None
        # New refresh token should be different (rotation)
        assert new_tokens.refresh_token != tokens.refresh_token

    def test_refresh_invalidates_old_token(
        self, db: Session, auth_service: AuthService
    ):
        """Refresh should invalidate the old refresh token."""
        user = create_verified_user(db)
        tokens = auth_service.login(db=db, email=user.email, password="password123")

        auth_service.refresh_tokens(db=db, refresh_token=tokens.refresh_token)

        # Old token should be revoked - using it again should raise error
        with pytest.raises(TokenRevokedError):
            auth_service.refresh_tokens(db=db, refresh_token=tokens.refresh_token)

    def test_refresh_with_invalid_token_raises_error(
        self, db: Session, auth_service: AuthService
    ):
        """Refresh with invalid token should raise InvalidCredentialsError."""
        with pytest.raises(InvalidCredentialsError):
            auth_service.refresh_tokens(
                db=db,
                refresh_token="invalid-token",
            )

    def test_refresh_replay_attack_revokes_family(
        self, db: Session, auth_service: AuthService
    ):
        """Using revoked token should revoke all tokens in family (replay attack)."""
        user = create_verified_user(db)
        tokens = auth_service.login(db=db, email=user.email, password="password123")
        old_refresh_token = tokens.refresh_token

        # First refresh - success, rotates token
        new_tokens = auth_service.refresh_tokens(
            db=db, refresh_token=tokens.refresh_token
        )

        # Try to use the old token again (replay attack)
        with pytest.raises(TokenRevokedError):
            auth_service.refresh_tokens(db=db, refresh_token=old_refresh_token)

        # The new token should also be revoked now (family revocation)
        with pytest.raises((TokenRevokedError, InvalidCredentialsError)):
            auth_service.refresh_tokens(db=db, refresh_token=new_tokens.refresh_token)


# =============================================================================
# TEST: LOGOUT
# =============================================================================


class TestLogout:
    """Tests for logout functionality."""

    def test_logout_revokes_token(self, db: Session, auth_service: AuthService):
        """Logout should revoke the refresh token."""
        user = create_verified_user(db)
        tokens = auth_service.login(db=db, email=user.email, password="password123")

        result = auth_service.logout(db=db, refresh_token=tokens.refresh_token)

        assert result is True

        # Token should no longer work
        with pytest.raises((TokenRevokedError, InvalidCredentialsError)):
            auth_service.refresh_tokens(db=db, refresh_token=tokens.refresh_token)

    def test_logout_with_invalid_token_returns_false(
        self, db: Session, auth_service: AuthService
    ):
        """Logout with invalid token should return False."""
        result = auth_service.logout(db=db, refresh_token="invalid-token")

        assert result is False

    def test_logout_all_revokes_all_sessions(
        self, db: Session, auth_service: AuthService
    ):
        """Logout all should revoke all refresh tokens for user."""
        user = create_verified_user(db)

        # Create multiple sessions
        tokens1 = auth_service.login(db=db, email=user.email, password="password123")
        tokens2 = auth_service.login(db=db, email=user.email, password="password123")
        tokens3 = auth_service.login(db=db, email=user.email, password="password123")

        count = auth_service.logout_all(db=db, user_id=user.id)

        assert count == 3

        # All tokens should be revoked
        for token in [tokens1, tokens2, tokens3]:
            with pytest.raises((TokenRevokedError, InvalidCredentialsError)):
                auth_service.refresh_tokens(db=db, refresh_token=token.refresh_token)


# =============================================================================
# TEST: EMAIL VERIFICATION
# =============================================================================


class TestEmailVerification:
    """Tests for email verification."""

    def test_verify_email_success(self, db: Session, auth_service: AuthService):
        """Verify email should mark user as verified."""
        user = create_unverified_user(db)
        email_service = auth_service._email_service
        email_service.validate_verification_token.return_value = user.email

        result = auth_service.verify_email(db=db, token="valid-token")

        assert result.is_email_verified is True
        assert result.email_verified_at is not None

    def test_verify_email_already_verified(self, db: Session, auth_service: AuthService):
        """Verifying already verified email should succeed without error."""
        user = create_verified_user(db)
        email_service = auth_service._email_service
        email_service.validate_verification_token.return_value = user.email

        result = auth_service.verify_email(db=db, token="valid-token")

        assert result.is_email_verified is True

    def test_verify_email_invalid_token(self, db: Session, auth_service: AuthService):
        """Invalid verification token should raise error."""
        email_service = auth_service._email_service
        email_service.validate_verification_token.side_effect = InvalidCredentialsError(
            "Invalid token"
        )

        with pytest.raises(InvalidCredentialsError):
            auth_service.verify_email(db=db, token="invalid-token")

    def test_verify_email_user_not_found(self, db: Session, auth_service: AuthService):
        """Verification for non-existent user should raise error."""
        email_service = auth_service._email_service
        email_service.validate_verification_token.return_value = "notexist@example.com"

        with pytest.raises(UserNotFoundError):
            auth_service.verify_email(db=db, token="valid-token")

    def test_resend_verification_email(
        self, db: Session, auth_service: AuthService, mock_email_service
    ):
        """Resend verification should send new email."""
        user = create_unverified_user(db)

        result = auth_service.resend_verification_email(db=db, email=user.email)

        assert result is True
        mock_email_service.send_verification_email.assert_called()


# =============================================================================
# TEST: PASSWORD RESET
# =============================================================================


class TestPasswordReset:
    """Tests for password reset functionality."""

    def test_request_password_reset_sends_email(
        self, db: Session, auth_service: AuthService, mock_email_service
    ):
        """Password reset request should send email."""
        user = create_verified_user(db)

        result = auth_service.request_password_reset(db=db, email=user.email)

        assert result is True
        mock_email_service.send_password_reset_email.assert_called()

    def test_request_password_reset_nonexistent_email(
        self, db: Session, auth_service: AuthService
    ):
        """Password reset for non-existent email should return True (no enumeration)."""
        result = auth_service.request_password_reset(
            db=db, email="notexist@example.com"
        )

        # Should return True to prevent user enumeration
        assert result is True

    def test_reset_password_success(self, db: Session, auth_service: AuthService):
        """Password reset should update password."""
        user = create_verified_user(db, password="oldpassword")
        email_service = auth_service._email_service
        email_service.validate_password_reset_token.return_value = user.email

        auth_service.reset_password(
            db=db,
            token="valid-token",
            new_password="newpassword123",
        )

        # Old password should no longer work
        with pytest.raises(InvalidCredentialsError):
            auth_service.login(db=db, email=user.email, password="oldpassword")

        # New password should work
        tokens = auth_service.login(db=db, email=user.email, password="newpassword123")
        assert tokens.access_token is not None

    def test_reset_password_revokes_all_sessions(
        self, db: Session, auth_service: AuthService
    ):
        """Password reset should revoke all refresh tokens."""
        user = create_verified_user(db)

        # Create some sessions
        tokens1 = auth_service.login(db=db, email=user.email, password="password123")
        tokens2 = auth_service.login(db=db, email=user.email, password="password123")

        email_service = auth_service._email_service
        email_service.validate_password_reset_token.return_value = user.email

        auth_service.reset_password(
            db=db,
            token="valid-token",
            new_password="newpassword123",
        )

        # Old tokens should be revoked
        for token in [tokens1, tokens2]:
            with pytest.raises((TokenRevokedError, InvalidCredentialsError)):
                auth_service.refresh_tokens(db=db, refresh_token=token.refresh_token)


# =============================================================================
# TEST: USER LOOKUP
# =============================================================================


class TestUserLookup:
    """Tests for user lookup methods."""

    def test_get_user_by_id(self, db: Session, auth_service: AuthService):
        """Should return user by ID."""
        user = create_verified_user(db)

        result = auth_service.get_user_by_id(db=db, user_id=user.id)

        assert result is not None
        assert result.id == user.id

    def test_get_user_by_id_not_found(self, db: Session, auth_service: AuthService):
        """Should return None for non-existent ID."""
        result = auth_service.get_user_by_id(db=db, user_id=99999)

        assert result is None

    def test_get_user_by_email(self, db: Session, auth_service: AuthService):
        """Should return user by email."""
        user = create_verified_user(db, email="findme@example.com")

        result = auth_service.get_user_by_email(db=db, email="findme@example.com")

        assert result is not None
        assert result.email == "findme@example.com"

    def test_get_user_by_email_case_insensitive(
        self, db: Session, auth_service: AuthService
    ):
        """Email lookup should be case-insensitive."""
        create_verified_user(db, email="findme@example.com")

        result = auth_service.get_user_by_email(db=db, email="FINDME@Example.COM")

        assert result is not None

    def test_get_user_by_email_not_found(self, db: Session, auth_service: AuthService):
        """Should return None for non-existent email."""
        result = auth_service.get_user_by_email(db=db, email="notexist@example.com")

        assert result is None
