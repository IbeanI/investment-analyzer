"""
Core authentication service.

Handles:
- User registration
- Login (email/password)
- Token refresh with rotation
- Logout (single session or all sessions)
- Email verification
- Password reset

Security features:
- Refresh token rotation on each use
- Token family tracking for replay detection
- Automatic revocation of all family tokens on replay attempt
"""

import hashlib
import uuid
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User, RefreshToken
from app.services.auth.password import PasswordService
from app.services.auth.jwt_handler import JWTHandler
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


logger = logging.getLogger(__name__)


@dataclass
class TokenPair:
    """Access and refresh token pair."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = settings.jwt_access_token_expire_minutes * 60


class AuthService:
    """
    Core authentication service.

    Manages user registration, authentication, and token lifecycle.
    """

    def __init__(self, email_service: EmailService | None = None) -> None:
        """
        Initialize the auth service.

        Args:
            email_service: Optional email service for sending verification emails.
                          If not provided, a new instance will be created.
        """
        self._email_service = email_service or EmailService()

    def register(
        self,
        db: Session,
        email: str,
        password: str,
        full_name: str | None = None,
    ) -> User:
        """
        Register a new user with email/password.

        Args:
            db: Database session
            email: User's email address
            password: Plain text password
            full_name: Optional user's full name

        Returns:
            The created User object

        Raises:
            UserExistsError: If email is already registered
        """
        # Check if user exists
        existing_user = db.execute(
            select(User).where(User.email == email.lower())
        ).scalar_one_or_none()

        if existing_user:
            raise UserExistsError(email)

        # Create user
        user = User(
            email=email.lower(),
            hashed_password=PasswordService.hash_password(password),
            full_name=full_name,
            is_email_verified=False,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # Send verification email
        token = self._email_service.generate_verification_token(user.email)
        self._email_service.send_verification_email(user.email, token)

        logger.info(f"User registered: {user.email}")
        return user

    def login(
        self,
        db: Session,
        email: str,
        password: str,
        device_info: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        """
        Authenticate user with email/password and return tokens.

        Args:
            db: Database session
            email: User's email address
            password: Plain text password
            device_info: Optional device information for session tracking
            ip_address: Optional IP address for session tracking

        Returns:
            TokenPair containing access and refresh tokens

        Raises:
            InvalidCredentialsError: If credentials are incorrect
            EmailNotVerifiedError: If email is not verified
            UserInactiveError: If user account is inactive
        """
        # Find user
        user = db.execute(
            select(User).where(User.email == email.lower())
        ).scalar_one_or_none()

        if not user or not user.hashed_password:
            raise InvalidCredentialsError()

        # Verify password
        if not PasswordService.verify_password(password, user.hashed_password):
            raise InvalidCredentialsError()

        # Check if email is verified
        if not user.is_email_verified:
            raise EmailNotVerifiedError(user.email)

        # Check if user is active
        if not user.is_active:
            raise UserInactiveError()

        # Check if password needs rehash
        if PasswordService.needs_rehash(user.hashed_password):
            user.hashed_password = PasswordService.hash_password(password)
            db.commit()

        # Create tokens
        tokens = self._create_token_pair(db, user, device_info, ip_address)

        logger.info(f"User logged in: {user.email}")
        return tokens

    def refresh_tokens(
        self,
        db: Session,
        refresh_token: str,
        device_info: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        """
        Refresh tokens using a refresh token.

        Implements token rotation: each refresh creates a new refresh token
        and invalidates the old one. If a revoked token is used, all tokens
        in the family are revoked (replay attack detection).

        Args:
            db: Database session
            refresh_token: The refresh token
            device_info: Optional device information
            ip_address: Optional IP address

        Returns:
            New TokenPair

        Raises:
            TokenExpiredError: If refresh token has expired
            TokenRevokedError: If token was revoked (possible replay attack)
            InvalidCredentialsError: If token is invalid
        """
        token_hash = self._hash_token(refresh_token)

        # Find token record
        token_record = db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        ).scalar_one_or_none()

        if not token_record:
            raise InvalidCredentialsError("Invalid refresh token")

        # Check if token was revoked - this indicates a replay attack!
        if token_record.revoked_at is not None:
            # Revoke ALL tokens in this family
            self._revoke_token_family(db, token_record.family_id)
            logger.warning(
                f"Refresh token replay detected for user {token_record.user_id}, "
                f"family {token_record.family_id}"
            )
            raise TokenRevokedError("Token has been revoked. All sessions have been terminated.")

        # Check expiration
        # Handle both timezone-aware and naive datetimes (SQLite returns naive)
        expires_at = token_record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise TokenExpiredError("Refresh token has expired", token_type="refresh")

        # Get user
        user = db.get(User, token_record.user_id)
        if not user or not user.is_active:
            raise UserInactiveError()

        # Revoke current token (rotation)
        token_record.revoked_at = datetime.now(timezone.utc)

        # Create new token pair with same family
        tokens = self._create_token_pair(
            db,
            user,
            device_info,
            ip_address,
            family_id=token_record.family_id,
        )

        db.commit()
        logger.info(f"Tokens refreshed for user {user.email}")
        return tokens

    def logout(self, db: Session, refresh_token: str) -> bool:
        """
        Logout by revoking the refresh token.

        Args:
            db: Database session
            refresh_token: The refresh token to revoke

        Returns:
            True if token was found and revoked
        """
        token_hash = self._hash_token(refresh_token)

        token_record = db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        ).scalar_one_or_none()

        if token_record and token_record.revoked_at is None:
            token_record.revoked_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(f"User logged out, token revoked")
            return True

        return False

    def logout_all(self, db: Session, user_id: int) -> int:
        """
        Logout from all sessions by revoking all refresh tokens.

        Args:
            db: Database session
            user_id: The user's ID

        Returns:
            Number of tokens revoked
        """
        now = datetime.now(timezone.utc)
        result = db.execute(
            select(RefreshToken).where(
                and_(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                )
            )
        ).scalars().all()

        count = 0
        for token in result:
            token.revoked_at = now
            count += 1

        db.commit()
        logger.info(f"User {user_id} logged out from all sessions ({count} tokens revoked)")
        return count

    def verify_email(self, db: Session, token: str) -> User:
        """
        Verify a user's email using verification token.

        Args:
            db: Database session
            token: Email verification token

        Returns:
            The verified User object

        Raises:
            TokenExpiredError: If token has expired
            InvalidCredentialsError: If token is invalid
            UserNotFoundError: If user doesn't exist
        """
        email = self._email_service.validate_verification_token(token)

        user = db.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()

        if not user:
            raise UserNotFoundError(email)

        if user.is_email_verified:
            # Already verified, just return
            return user

        user.is_email_verified = True
        user.email_verified_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(f"Email verified: {user.email}")
        return user

    def resend_verification_email(self, db: Session, email: str) -> bool:
        """
        Resend email verification email.

        Args:
            db: Database session
            email: User's email address

        Returns:
            True if email was sent (or user doesn't exist - for security)
        """
        user = db.execute(
            select(User).where(User.email == email.lower())
        ).scalar_one_or_none()

        # Always return True to prevent user enumeration
        if not user:
            return True

        if user.is_email_verified:
            # Already verified
            return True

        token = self._email_service.generate_verification_token(user.email)
        self._email_service.send_verification_email(user.email, token)

        logger.info(f"Verification email resent to: {user.email}")
        return True

    def request_password_reset(self, db: Session, email: str) -> bool:
        """
        Request a password reset email.

        Args:
            db: Database session
            email: User's email address

        Returns:
            True (always, to prevent user enumeration)
        """
        user = db.execute(
            select(User).where(User.email == email.lower())
        ).scalar_one_or_none()

        # Always return True to prevent user enumeration
        if not user:
            logger.info(f"Password reset requested for non-existent email: {email}")
            return True

        # Only allow reset for users with password (not OAuth-only)
        if not user.hashed_password:
            logger.info(f"Password reset requested for OAuth-only user: {email}")
            return True

        token = self._email_service.generate_password_reset_token(user.email)
        self._email_service.send_password_reset_email(user.email, token)

        logger.info(f"Password reset email sent to: {user.email}")
        return True

    def reset_password(
        self,
        db: Session,
        token: str,
        new_password: str,
    ) -> User:
        """
        Reset a user's password using reset token.

        Also revokes all existing refresh tokens for security.

        Args:
            db: Database session
            token: Password reset token
            new_password: New password

        Returns:
            The updated User object

        Raises:
            TokenExpiredError: If token has expired
            InvalidCredentialsError: If token is invalid
            UserNotFoundError: If user doesn't exist
        """
        email = self._email_service.validate_password_reset_token(token)

        user = db.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()

        if not user:
            raise UserNotFoundError(email)

        # Update password
        user.hashed_password = PasswordService.hash_password(new_password)
        user.password_reset_at = datetime.now(timezone.utc)

        # Revoke all refresh tokens for security
        self.logout_all(db, user.id)

        db.commit()

        logger.info(f"Password reset for user: {user.email}")
        return user

    def get_user_by_id(self, db: Session, user_id: int) -> User | None:
        """
        Get a user by their ID.

        Args:
            db: Database session
            user_id: User's ID

        Returns:
            User object or None if not found
        """
        return db.get(User, user_id)

    def get_user_by_email(self, db: Session, email: str) -> User | None:
        """
        Get a user by their email.

        Args:
            db: Database session
            email: User's email

        Returns:
            User object or None if not found
        """
        return db.execute(
            select(User).where(User.email == email.lower())
        ).scalar_one_or_none()

    def _create_token_pair(
        self,
        db: Session,
        user: User,
        device_info: str | None = None,
        ip_address: str | None = None,
        family_id: str | None = None,
    ) -> TokenPair:
        """
        Create access and refresh token pair.

        Args:
            db: Database session
            user: User object
            device_info: Optional device information
            ip_address: Optional IP address
            family_id: Optional family ID for token rotation

        Returns:
            TokenPair with access and refresh tokens
        """
        # Create access token
        access_token = JWTHandler.create_access_token(
            user_id=user.id,
            email=user.email,
        )

        # Create refresh token (random UUID)
        refresh_token = str(uuid.uuid4())
        token_hash = self._hash_token(refresh_token)

        # Use existing family or create new one
        if family_id is None:
            family_id = str(uuid.uuid4())

        # Store refresh token
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.jwt_refresh_token_expire_days
        )

        refresh_token_record = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            family_id=family_id,
            expires_at=expires_at,
            device_info=device_info,
            ip_address=ip_address,
        )
        db.add(refresh_token_record)
        db.commit()

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    def _hash_token(self, token: str) -> str:
        """Hash a token using SHA-256."""
        return hashlib.sha256(token.encode()).hexdigest()

    def _revoke_token_family(self, db: Session, family_id: str) -> int:
        """
        Revoke all tokens in a family (for replay attack response).

        Args:
            db: Database session
            family_id: The token family ID

        Returns:
            Number of tokens revoked
        """
        now = datetime.now(timezone.utc)
        tokens = db.execute(
            select(RefreshToken).where(
                and_(
                    RefreshToken.family_id == family_id,
                    RefreshToken.revoked_at.is_(None),
                )
            )
        ).scalars().all()

        count = 0
        for token in tokens:
            token.revoked_at = now
            count += 1

        db.commit()
        return count
