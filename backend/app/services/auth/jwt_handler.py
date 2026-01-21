"""
JWT token creation and validation.

Handles:
- Access tokens (short-lived, for API authentication)
- Token validation and payload extraction
- Token expiration checking

Security notes:
- Access tokens are NOT stored in database (stateless)
- Refresh tokens ARE stored (for revocation, see service.py)
- Uses HS256 algorithm by default (symmetric, fast)
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from app.config import settings
from app.services.exceptions import TokenExpiredError, InvalidCredentialsError


class JWTHandler:
    """
    Handles JWT token creation and validation.

    Access tokens contain:
    - sub: User ID (string)
    - email: User's email
    - exp: Expiration timestamp
    - iat: Issued at timestamp
    - type: "access" (to distinguish from other token types)
    """

    @staticmethod
    def create_access_token(
        user_id: int,
        email: str,
        expires_delta: timedelta | None = None,
    ) -> str:
        """
        Create a new access token.

        Args:
            user_id: The user's database ID
            email: The user's email address
            expires_delta: Optional custom expiration time

        Returns:
            Encoded JWT string

        Example:
            token = JWTHandler.create_access_token(
                user_id=1,
                email="user@example.com"
            )
        """
        if expires_delta is None:
            expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)

        now = datetime.now(timezone.utc)
        expire = now + expires_delta

        payload = {
            "sub": str(user_id),
            "email": email,
            "exp": expire,
            "iat": now,
            "type": "access",
        }

        return jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

    @staticmethod
    def validate_access_token(token: str) -> dict[str, Any]:
        """
        Validate an access token and return its payload.

        Args:
            token: The JWT string to validate

        Returns:
            Dict containing the token payload (sub, email, exp, iat, type)

        Raises:
            TokenExpiredError: If the token has expired
            InvalidCredentialsError: If the token is invalid or malformed

        Example:
            try:
                payload = JWTHandler.validate_access_token(token)
                user_id = int(payload["sub"])
            except TokenExpiredError:
                # Redirect to refresh endpoint
                pass
        """
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
            )

            # Verify this is an access token
            if payload.get("type") != "access":
                raise InvalidCredentialsError("Invalid token type")

            return payload

        except jwt.ExpiredSignatureError:
            raise TokenExpiredError("Access token has expired")
        except JWTError as e:
            raise InvalidCredentialsError(f"Invalid token: {str(e)}")

    @staticmethod
    def decode_token_without_verification(token: str) -> dict[str, Any]:
        """
        Decode a token without verifying signature or expiration.

        CAUTION: Only use this for debugging or extracting claims from
        expired tokens (e.g., to identify user for refresh flow).

        Args:
            token: The JWT string to decode

        Returns:
            Dict containing the token payload

        Raises:
            InvalidCredentialsError: If the token is malformed
        """
        try:
            return jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
                options={"verify_signature": False, "verify_exp": False},
            )
        except JWTError as e:
            raise InvalidCredentialsError(f"Malformed token: {str(e)}")

    @staticmethod
    def get_token_expiry(token: str) -> datetime | None:
        """
        Get the expiration time of a token.

        Args:
            token: The JWT string

        Returns:
            Expiration datetime (UTC) or None if not found
        """
        try:
            payload = JWTHandler.decode_token_without_verification(token)
            exp = payload.get("exp")
            if exp:
                return datetime.fromtimestamp(exp, tz=timezone.utc)
            return None
        except InvalidCredentialsError:
            return None
