# tests/services/auth/test_jwt_handler.py
"""
Tests for JWT token handling.

Tests:
- Access token creation with correct claims
- Token validation (valid, expired, invalid)
- Token type verification
- Token decoding without verification
- Token expiry extraction
"""

import os
from datetime import datetime, timedelta, timezone

import pytest

# Set required environment variables BEFORE importing app modules
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_NAME", "Test App")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-at-least-32-chars-long")

from app.services.auth.jwt_handler import JWTHandler
from app.services.exceptions import TokenExpiredError, InvalidCredentialsError


# =============================================================================
# TEST: ACCESS TOKEN CREATION
# =============================================================================


class TestCreateAccessToken:
    """Tests for access token creation."""

    def test_create_token_returns_string(self):
        """Token creation should return a non-empty string."""
        token = JWTHandler.create_access_token(user_id=1, email="test@example.com")

        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_token_is_valid_jwt(self):
        """Created token should be a valid JWT (3 dot-separated parts)."""
        token = JWTHandler.create_access_token(user_id=1, email="test@example.com")

        parts = token.split(".")
        assert len(parts) == 3  # header.payload.signature

    def test_token_contains_correct_claims(self):
        """Token should contain user_id, email, and type claims."""
        token = JWTHandler.create_access_token(user_id=123, email="user@example.com")

        payload = JWTHandler.validate_access_token(token)

        assert payload["sub"] == "123"  # user_id as string
        assert payload["email"] == "user@example.com"
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "iat" in payload

    def test_token_with_custom_expiry(self):
        """Token should respect custom expiry time."""
        expires_delta = timedelta(hours=2)
        token = JWTHandler.create_access_token(
            user_id=1,
            email="test@example.com",
            expires_delta=expires_delta,
        )

        payload = JWTHandler.validate_access_token(token)
        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        iat_time = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)

        # Should be approximately 2 hours apart
        diff = exp_time - iat_time
        assert timedelta(hours=1, minutes=59) < diff < timedelta(hours=2, minutes=1)

    def test_different_users_get_different_tokens(self):
        """Different users should get different tokens."""
        token1 = JWTHandler.create_access_token(user_id=1, email="user1@example.com")
        token2 = JWTHandler.create_access_token(user_id=2, email="user2@example.com")

        assert token1 != token2


# =============================================================================
# TEST: ACCESS TOKEN VALIDATION
# =============================================================================


class TestValidateAccessToken:
    """Tests for access token validation."""

    def test_valid_token_returns_payload(self):
        """Valid token should return its payload."""
        token = JWTHandler.create_access_token(user_id=1, email="test@example.com")

        payload = JWTHandler.validate_access_token(token)

        assert payload["sub"] == "1"
        assert payload["email"] == "test@example.com"

    def test_expired_token_raises_error(self):
        """Expired token should raise TokenExpiredError."""
        # Create token that's already expired
        token = JWTHandler.create_access_token(
            user_id=1,
            email="test@example.com",
            expires_delta=timedelta(seconds=-10),  # Expired 10 seconds ago
        )

        with pytest.raises(TokenExpiredError) as exc_info:
            JWTHandler.validate_access_token(token)

        assert "expired" in str(exc_info.value).lower()

    def test_invalid_token_raises_error(self):
        """Invalid token should raise InvalidCredentialsError."""
        with pytest.raises(InvalidCredentialsError):
            JWTHandler.validate_access_token("not-a-valid-jwt")

    def test_malformed_token_raises_error(self):
        """Malformed token should raise InvalidCredentialsError."""
        with pytest.raises(InvalidCredentialsError):
            JWTHandler.validate_access_token("header.payload")  # Missing signature

    def test_tampered_token_raises_error(self):
        """Token with tampered payload should raise InvalidCredentialsError."""
        token = JWTHandler.create_access_token(user_id=1, email="test@example.com")

        # Tamper with the payload (middle part)
        parts = token.split(".")
        parts[1] = parts[1][:-5] + "xxxxx"  # Modify payload
        tampered_token = ".".join(parts)

        with pytest.raises(InvalidCredentialsError):
            JWTHandler.validate_access_token(tampered_token)

    def test_wrong_token_type_raises_error(self):
        """Token with wrong type should raise InvalidCredentialsError."""
        # Create a token manually with wrong type
        from jose import jwt
        from app.config import settings

        payload = {
            "sub": "1",
            "email": "test@example.com",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "iat": datetime.now(timezone.utc),
            "type": "refresh",  # Wrong type!
        }
        token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

        with pytest.raises(InvalidCredentialsError) as exc_info:
            JWTHandler.validate_access_token(token)

        assert "token type" in str(exc_info.value).lower()


# =============================================================================
# TEST: TOKEN DECODING WITHOUT VERIFICATION
# =============================================================================


class TestDecodeWithoutVerification:
    """Tests for decoding tokens without verification."""

    def test_decode_valid_token(self):
        """Should decode valid token without checking signature/expiry."""
        token = JWTHandler.create_access_token(user_id=1, email="test@example.com")

        payload = JWTHandler.decode_token_without_verification(token)

        assert payload["sub"] == "1"
        assert payload["email"] == "test@example.com"

    def test_decode_expired_token(self):
        """Should decode expired token (useful for getting user info)."""
        token = JWTHandler.create_access_token(
            user_id=1,
            email="test@example.com",
            expires_delta=timedelta(seconds=-10),
        )

        # This should NOT raise even though token is expired
        payload = JWTHandler.decode_token_without_verification(token)

        assert payload["sub"] == "1"

    def test_decode_malformed_token_raises_error(self):
        """Malformed token should still raise error."""
        with pytest.raises(InvalidCredentialsError):
            JWTHandler.decode_token_without_verification("not-a-token")


# =============================================================================
# TEST: TOKEN EXPIRY EXTRACTION
# =============================================================================


class TestGetTokenExpiry:
    """Tests for extracting token expiry time."""

    def test_get_expiry_from_valid_token(self):
        """Should return expiry datetime from valid token."""
        token = JWTHandler.create_access_token(user_id=1, email="test@example.com")

        expiry = JWTHandler.get_token_expiry(token)

        assert expiry is not None
        assert isinstance(expiry, datetime)
        assert expiry.tzinfo is not None  # Should be timezone-aware

    def test_get_expiry_from_expired_token(self):
        """Should return expiry even from expired token."""
        token = JWTHandler.create_access_token(
            user_id=1,
            email="test@example.com",
            expires_delta=timedelta(seconds=-10),
        )

        expiry = JWTHandler.get_token_expiry(token)

        assert expiry is not None
        assert expiry < datetime.now(timezone.utc)  # Should be in the past

    def test_get_expiry_from_invalid_token_returns_none(self):
        """Should return None for invalid token."""
        expiry = JWTHandler.get_token_expiry("not-a-valid-token")

        assert expiry is None
