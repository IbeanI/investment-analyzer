# backend/app/services/user_settings_service.py
"""
User Settings Service for managing user-level preferences.

This service handles:
- Creating default settings for new users
- Retrieving settings with auto-creation of defaults
- Updating settings (display, defaults, regional)
- User profile management (view, update name)
- Password changes
- Account deletion

Design Principles:
- Single Responsibility: Only handles user settings and profile
- Sensible Defaults: Settings created automatically when needed
- No HTTP Knowledge: Raises domain exceptions, not HTTPException
- Security: Password verification for sensitive operations

Default Settings:
- theme: "system"
- date_format: "YYYY-MM-DD"
- number_format: "US"
- default_currency: "EUR"
- default_benchmark: None
- timezone: "UTC"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.models import User, UserSettings, Portfolio, RefreshToken
from app.services.auth.password import PasswordService
from app.services.exceptions import (
    InvalidCredentialsError,
    UserNotFoundError,
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

DEFAULT_THEME = "system"
DEFAULT_DATE_FORMAT = "YYYY-MM-DD"
DEFAULT_NUMBER_FORMAT = "US"
DEFAULT_CURRENCY = "EUR"
DEFAULT_BENCHMARK = None
DEFAULT_TIMEZONE = "UTC"


# =============================================================================
# RESULT TYPES
# =============================================================================

@dataclass
class SettingsUpdateResult:
    """Result of updating user settings."""

    settings: UserSettings
    was_created: bool
    changed_fields: list[str]


@dataclass
class ProfileUpdateResult:
    """Result of updating user profile."""

    user: User
    changed_fields: list[str]


@dataclass
class AccountDeleteResult:
    """Result of account deletion."""

    user_id: int
    email: str
    portfolios_deleted: int
    tokens_revoked: int


# =============================================================================
# SERVICE
# =============================================================================

class UserSettingsService:
    """
    Service for managing user settings and profile.

    Provides a consistent interface for reading and writing user
    settings with automatic default creation.
    """

    def __init__(self) -> None:
        """Initialize the user settings service."""
        logger.info("UserSettingsService initialized")

    # =========================================================================
    # SETTINGS MANAGEMENT
    # =========================================================================

    def get_settings(
            self,
            db: Session,
            user_id: int,
    ) -> UserSettings | None:
        """
        Get settings for a user.

        Returns None if no settings exist yet.
        """
        return db.scalar(
            select(UserSettings)
            .where(UserSettings.user_id == user_id)
        )

    def get_or_create_settings(
            self,
            db: Session,
            user_id: int,
    ) -> UserSettings:
        """
        Get settings for a user, creating defaults if not exists.

        This is the primary method to use when you need settings.
        """
        settings = self.get_settings(db, user_id)
        if settings is not None:
            return settings

        # Verify user exists
        user = db.get(User, user_id)
        if user is None:
            raise UserNotFoundError(user_id)

        # Create with defaults
        logger.info(f"Creating default settings for user {user_id}")

        settings = UserSettings(
            user_id=user_id,
            theme=DEFAULT_THEME,
            date_format=DEFAULT_DATE_FORMAT,
            number_format=DEFAULT_NUMBER_FORMAT,
            default_currency=DEFAULT_CURRENCY,
            default_benchmark=DEFAULT_BENCHMARK,
            timezone=DEFAULT_TIMEZONE,
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)

        return settings

    def update_settings(
            self,
            db: Session,
            user_id: int,
            theme: str | None = None,
            date_format: str | None = None,
            number_format: str | None = None,
            default_currency: str | None = None,
            default_benchmark: str | None = None,
            timezone_str: str | None = None,
            clear_default_benchmark: bool = False,
    ) -> SettingsUpdateResult:
        """
        Update settings for a user.

        Creates settings with defaults first if they don't exist,
        then applies the requested changes.
        """
        settings = self.get_or_create_settings(db, user_id)
        was_created = settings.created_at == settings.updated_at
        changed_fields: list[str] = []

        # Apply changes
        if theme is not None and settings.theme != theme:
            settings.theme = theme
            changed_fields.append("theme")

        if date_format is not None and settings.date_format != date_format:
            settings.date_format = date_format
            changed_fields.append("date_format")

        if number_format is not None and settings.number_format != number_format:
            settings.number_format = number_format
            changed_fields.append("number_format")

        if default_currency is not None and settings.default_currency != default_currency:
            settings.default_currency = default_currency
            changed_fields.append("default_currency")

        # Handle default_benchmark - can be set to a value or cleared
        if clear_default_benchmark:
            if settings.default_benchmark is not None:
                settings.default_benchmark = None
                changed_fields.append("default_benchmark")
        elif default_benchmark is not None and settings.default_benchmark != default_benchmark:
            settings.default_benchmark = default_benchmark
            changed_fields.append("default_benchmark")

        if timezone_str is not None and settings.timezone != timezone_str:
            settings.timezone = timezone_str
            changed_fields.append("timezone")

        # Commit if changes were made
        if changed_fields:
            settings.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(settings)
            logger.info(f"User {user_id} settings updated: {changed_fields}")

        return SettingsUpdateResult(
            settings=settings,
            was_created=was_created,
            changed_fields=changed_fields,
        )

    # =========================================================================
    # PROFILE MANAGEMENT
    # =========================================================================

    def get_profile(
            self,
            db: Session,
            user_id: int,
    ) -> User:
        """
        Get user profile by ID.

        Raises:
            UserNotFoundError: If user doesn't exist
        """
        user = db.get(User, user_id)
        if user is None:
            raise UserNotFoundError(user_id)
        return user

    def update_profile(
            self,
            db: Session,
            user_id: int,
            full_name: str | None = None,
    ) -> ProfileUpdateResult:
        """
        Update user profile.

        Currently only supports updating full_name.
        Email is read-only.
        """
        user = self.get_profile(db, user_id)
        changed_fields: list[str] = []

        if full_name is not None and user.full_name != full_name:
            user.full_name = full_name
            changed_fields.append("full_name")

        if changed_fields:
            user.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(user)
            logger.info(f"User {user_id} profile updated: {changed_fields}")

        return ProfileUpdateResult(
            user=user,
            changed_fields=changed_fields,
        )

    # =========================================================================
    # PASSWORD MANAGEMENT
    # =========================================================================

    def change_password(
            self,
            db: Session,
            user_id: int,
            current_password: str,
            new_password: str,
    ) -> bool:
        """
        Change user's password.

        Verifies current password before changing.

        Raises:
            UserNotFoundError: If user doesn't exist
            InvalidCredentialsError: If current password is wrong or user has no password
        """
        user = self.get_profile(db, user_id)

        # Check if user has a password (not OAuth-only)
        if not user.hashed_password:
            raise InvalidCredentialsError(
                "Cannot change password for OAuth-only accounts"
            )

        # Verify current password
        if not PasswordService.verify_password(current_password, user.hashed_password):
            raise InvalidCredentialsError("Current password is incorrect")

        # Update password
        user.hashed_password = PasswordService.hash_password(new_password)
        user.password_reset_at = datetime.now(timezone.utc)
        user.updated_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(f"User {user_id} changed password")
        return True

    def user_has_password(
            self,
            db: Session,
            user_id: int,
    ) -> bool:
        """Check if user has a password set (not OAuth-only)."""
        user = self.get_profile(db, user_id)
        return user.hashed_password is not None

    # =========================================================================
    # ACCOUNT DELETION
    # =========================================================================

    def delete_account(
            self,
            db: Session,
            user_id: int,
            password: str | None = None,
    ) -> AccountDeleteResult:
        """
        Delete user account and all associated data.

        For users with passwords, password verification is required.
        For OAuth-only users, no password is needed.

        Deletes:
        - All portfolios (and their transactions via cascade)
        - All refresh tokens
        - User settings
        - The user record

        Raises:
            UserNotFoundError: If user doesn't exist
            InvalidCredentialsError: If password is required but wrong/missing
        """
        user = self.get_profile(db, user_id)

        # If user has a password, verify it
        if user.hashed_password:
            if not password:
                raise InvalidCredentialsError("Password is required to delete account")
            if not PasswordService.verify_password(password, user.hashed_password):
                raise InvalidCredentialsError("Password is incorrect")

        email = user.email

        # Count portfolios to be deleted
        portfolios = db.scalars(
            select(Portfolio).where(Portfolio.user_id == user_id)
        ).all()
        portfolios_count = len(portfolios)

        # Revoke all refresh tokens
        tokens = db.scalars(
            select(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .where(RefreshToken.revoked_at.is_(None))
        ).all()
        tokens_count = len(tokens)

        for token in tokens:
            token.revoked_at = datetime.now(timezone.utc)

        # Delete user (cascades to settings, portfolios, transactions, etc.)
        db.delete(user)
        db.commit()

        logger.warning(
            f"User account deleted: {email} (id={user_id}, "
            f"portfolios={portfolios_count}, tokens={tokens_count})"
        )

        return AccountDeleteResult(
            user_id=user_id,
            email=email,
            portfolios_deleted=portfolios_count,
            tokens_revoked=tokens_count,
        )
