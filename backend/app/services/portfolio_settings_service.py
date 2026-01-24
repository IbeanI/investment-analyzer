# backend/app/services/portfolio_settings_service.py
"""
Portfolio Settings Service for managing portfolio-level preferences.

This service handles:
- Creating default settings for new portfolios
- Retrieving settings with auto-creation of defaults
- Updating settings with validation
- Checking feature flags (e.g., backcasting enabled)

Design Principles:
- Single Responsibility: Only handles portfolio settings
- Sensible Defaults: Settings created automatically when needed
- No HTTP Knowledge: Raises domain exceptions, not HTTPException
- Opt-Out Model: Features enabled by default, users can disable

Default Settings:
- enable_proxy_backcasting: True (users opt-out if they want pure data)

Usage:
    from app.services.portfolio_settings_service import PortfolioSettingsService

    service = PortfolioSettingsService()

    # Get or create settings (auto-creates with defaults if not exists)
    settings = service.get_or_create_default(db, portfolio_id=1)

    # Check if backcasting is enabled
    if service.is_backcasting_enabled(db, portfolio_id=1):
        # Apply proxy mappings and generate synthetic data
        pass

    # Update settings
    settings = service.update_settings(
        db, portfolio_id=1,
        enable_proxy_backcasting=False
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PortfolioSettings, Portfolio
from app.schemas.portfolio_settings import BackcastingMethod
from app.services.constants import DEFAULT_ENABLE_PROXY_BACKCASTING
from app.services.exceptions import PortfolioNotFoundError

logger = logging.getLogger(__name__)


# =============================================================================
# RESULT TYPES
# =============================================================================

@dataclass
class SettingsUpdateResult:
    """Result of updating portfolio settings."""

    settings: PortfolioSettings
    was_created: bool  # True if settings were just created
    changed_fields: list[str]  # Fields that were actually changed
    warning: str | None = None  # Warning message (e.g., when disabling features)


# =============================================================================
# SERVICE
# =============================================================================

class PortfolioSettingsService:
    """
    Service for managing portfolio settings.

    Provides a consistent interface for reading and writing portfolio
    settings with automatic default creation.

    Features:
        - Auto-creation: Settings created on first access with sensible defaults
        - Validation: Ensures portfolio exists before creating settings
        - Audit trail: Tracks when settings were changed
        - Warnings: Returns warnings when disabling important features

    Example:
        service = PortfolioSettingsService()

        # Settings are auto-created with defaults on first access
        settings = service.get_or_create_default(db, portfolio_id=1)
        print(settings.enable_proxy_backcasting)  # True (default)

        # Disable backcasting (user opts out)
        result = service.update_settings(
            db, portfolio_id=1,
            enable_proxy_backcasting=False
        )
        if result.warning:
            print(result.warning)  # User should be aware of implications
    """

    def __init__(self) -> None:
        """Initialize the portfolio settings service."""
        logger.info("PortfolioSettingsService initialized")

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def get_settings(
            self,
            db: Session,
            portfolio_id: int,
    ) -> PortfolioSettings | None:
        """
        Get settings for a portfolio.

        Returns None if no settings exist yet. Use get_or_create_default()
        if you want automatic creation with defaults.

        Args:
            db: Database session
            portfolio_id: Portfolio to get settings for

        Returns:
            PortfolioSettings or None if not found
        """
        return db.scalar(
            select(PortfolioSettings)
            .where(PortfolioSettings.portfolio_id == portfolio_id)
        )

    def get_or_create_default(
            self,
            db: Session,
            portfolio_id: int,
    ) -> PortfolioSettings:
        """
        Get settings for a portfolio, creating defaults if not exists.

        This is the primary method to use when you need settings.
        It ensures settings always exist with sensible defaults.

        Args:
            db: Database session
            portfolio_id: Portfolio to get/create settings for

        Returns:
            PortfolioSettings (existing or newly created)

        Raises:
            ValueError: If portfolio doesn't exist
        """
        # Check existing
        settings = self.get_settings(db, portfolio_id)
        if settings is not None:
            return settings

        # Verify portfolio exists
        portfolio = db.get(Portfolio, portfolio_id)
        if portfolio is None:
            raise PortfolioNotFoundError(portfolio_id)

        # Create with defaults
        logger.info(
            f"Creating default settings for portfolio {portfolio_id} "
            f"(enable_proxy_backcasting={DEFAULT_ENABLE_PROXY_BACKCASTING}, "
            f"backcasting_method=proxy_preferred)"
        )

        settings = PortfolioSettings(
            portfolio_id=portfolio_id,
            enable_proxy_backcasting=DEFAULT_ENABLE_PROXY_BACKCASTING,
            backcasting_method=BackcastingMethod.PROXY_PREFERRED.value,
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)

        return settings

    def update_settings(
            self,
            db: Session,
            portfolio_id: int,
            enable_proxy_backcasting: bool | None = None,
            backcasting_method: BackcastingMethod | None = None,
    ) -> SettingsUpdateResult:
        """
        Update settings for a portfolio.

        Creates settings with defaults first if they don't exist,
        then applies the requested changes.

        Args:
            db: Database session
            portfolio_id: Portfolio to update settings for
            enable_proxy_backcasting: New value for backcasting flag (None = no change) - DEPRECATED
            backcasting_method: New value for backcasting method (None = no change)

        Returns:
            SettingsUpdateResult with updated settings and any warnings

        Raises:
            ValueError: If portfolio doesn't exist
        """
        # Get or create
        settings = self.get_or_create_default(db, portfolio_id)
        was_created = settings.created_at == settings.updated_at  # Just created
        changed_fields: list[str] = []
        warning: str | None = None

        # Apply changes for enable_proxy_backcasting (DEPRECATED)
        if enable_proxy_backcasting is not None:
            old_value = settings.enable_proxy_backcasting
            if old_value != enable_proxy_backcasting:
                settings.enable_proxy_backcasting = enable_proxy_backcasting
                changed_fields.append("enable_proxy_backcasting")

                # Generate warning when disabling backcasting
                if old_value is True and enable_proxy_backcasting is False:
                    warning = (
                        "Proxy backcasting disabled. Historical valuations may be "
                        "incomplete for assets with limited price history (e.g., "
                        "delisted ETFs, merged funds). Existing synthetic prices "
                        "will NOT be removed."
                    )
                    logger.warning(
                        f"Portfolio {portfolio_id}: Backcasting disabled by user"
                    )

        # Apply changes for backcasting_method
        if backcasting_method is not None:
            old_method = settings.backcasting_method
            new_method = backcasting_method.value if isinstance(backcasting_method, BackcastingMethod) else backcasting_method
            if old_method != new_method:
                settings.backcasting_method = new_method
                changed_fields.append("backcasting_method")

                # Generate warning when disabling backcasting
                if new_method == BackcastingMethod.DISABLED.value:
                    warning = (
                        "Backcasting disabled. Historical valuations may be "
                        "incomplete for assets with limited price history (e.g., "
                        "delisted ETFs, merged funds). Existing synthetic prices "
                        "will NOT be removed."
                    )
                    logger.warning(
                        f"Portfolio {portfolio_id}: Backcasting method set to disabled"
                    )
                elif new_method == BackcastingMethod.COST_CARRY_ONLY.value:
                    logger.info(
                        f"Portfolio {portfolio_id}: Backcasting method set to cost_carry_only"
                    )

        # Commit if changes were made
        if changed_fields:
            settings.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(settings)
            logger.info(
                f"Portfolio {portfolio_id} settings updated: {changed_fields}"
            )

        return SettingsUpdateResult(
            settings=settings,
            was_created=was_created,
            changed_fields=changed_fields,
            warning=warning,
        )

    def is_backcasting_enabled(
            self,
            db: Session,
            portfolio_id: int,
    ) -> bool:
        """
        Check if proxy backcasting is enabled for a portfolio.

        Convenience method that returns the default (True) if no
        settings exist yet.

        NOTE: This method is DEPRECATED. Use get_backcasting_method() instead.

        Args:
            db: Database session
            portfolio_id: Portfolio to check

        Returns:
            True if backcasting is enabled (default), False if disabled
        """
        settings = self.get_settings(db, portfolio_id)

        if settings is None:
            # No settings = use default (enabled)
            return DEFAULT_ENABLE_PROXY_BACKCASTING

        return settings.enable_proxy_backcasting

    def get_backcasting_method(
            self,
            db: Session,
            portfolio_id: int,
    ) -> BackcastingMethod:
        """
        Get the backcasting method preference for a portfolio.

        Args:
            db: Database session
            portfolio_id: Portfolio to check

        Returns:
            BackcastingMethod enum value (defaults to PROXY_PREFERRED)
        """
        settings = self.get_settings(db, portfolio_id)

        if settings is None:
            # No settings = use default
            return BackcastingMethod.PROXY_PREFERRED

        # Convert string to enum
        try:
            return BackcastingMethod(settings.backcasting_method)
        except ValueError:
            # Invalid value in DB, return default
            logger.warning(
                f"Invalid backcasting_method '{settings.backcasting_method}' "
                f"for portfolio {portfolio_id}, using default"
            )
            return BackcastingMethod.PROXY_PREFERRED

    def ensure_settings_exist(
            self,
            db: Session,
            portfolio_id: int,
    ) -> bool:
        """
        Ensure settings exist for a portfolio, creating if needed.

        This is a convenience method that returns True if settings
        were just created, False if they already existed.

        Args:
            db: Database session
            portfolio_id: Portfolio to ensure settings for

        Returns:
            True if settings were created, False if already existed
        """
        existing = self.get_settings(db, portfolio_id)
        if existing is not None:
            return False

        self.get_or_create_default(db, portfolio_id)
        return True
