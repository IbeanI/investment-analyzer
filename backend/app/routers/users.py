# backend/app/routers/users.py
"""
User Settings and Profile endpoints.

Provides endpoints for managing user-level preferences and profile.

Endpoints:
    GET    /users/me/settings  - Get user settings (creates defaults if needed)
    PATCH  /users/me/settings  - Update user settings
    GET    /users/me/profile   - Get user profile
    PATCH  /users/me/profile   - Update user profile (name only)
    POST   /users/me/password  - Change password
    DELETE /users/me           - Delete account (danger zone)
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas.auth import MessageResponse
from app.schemas.user_settings import (
    UserSettingsResponse,
    UserSettingsUpdate,
)
from app.schemas.user_profile import (
    UserProfileResponse,
    UserProfileUpdate,
    PasswordChangeRequest,
    AccountDeleteRequest,
)
from app.services.user_settings_service import UserSettingsService
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)


# =============================================================================
# ROUTER SETUP
# =============================================================================

router = APIRouter(
    prefix="/users",
    tags=["User Settings"],
)


# =============================================================================
# DEPENDENCIES
# =============================================================================

def get_user_settings_service() -> UserSettingsService:
    """Dependency that provides the user settings service."""
    return UserSettingsService()


# =============================================================================
# SETTINGS ENDPOINTS
# =============================================================================

@router.get(
    "/me/settings",
    response_model=UserSettingsResponse,
    summary="Get user settings",
    response_description="Current user settings",
    responses={
        200: {
            "description": "Settings retrieved successfully",
            "model": UserSettingsResponse,
        },
        401: {
            "description": "Not authenticated",
        },
    },
)
def get_user_settings(
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
        service: Annotated[UserSettingsService, Depends(get_user_settings_service)],
) -> UserSettingsResponse:
    """
    Get settings for the current user.

    If settings don't exist yet, they will be automatically created
    with default values:

    | Setting | Default | Description |
    |---------|---------|-------------|
    | `theme` | `system` | UI theme (light, dark, system) |
    | `date_format` | `YYYY-MM-DD` | Date display format |
    | `number_format` | `US` | Number format (US: 1,234.56, EU: 1.234,56) |
    | `default_currency` | `EUR` | Default currency for new portfolios |
    | `default_benchmark` | `null` | Default benchmark for new portfolios |
    | `timezone` | `UTC` | User's timezone |
    """
    logger.info(f"Getting settings for user {current_user.id}")

    settings = service.get_or_create_settings(db, current_user.id)

    return UserSettingsResponse(
        theme=settings.theme,
        date_format=settings.date_format,
        number_format=settings.number_format,
        default_currency=settings.default_currency,
        default_benchmark=settings.default_benchmark,
        timezone=settings.timezone,
    )


@router.patch(
    "/me/settings",
    response_model=UserSettingsResponse,
    summary="Update user settings",
    response_description="Updated user settings",
    responses={
        200: {
            "description": "Settings updated successfully",
            "model": UserSettingsResponse,
        },
        401: {
            "description": "Not authenticated",
        },
    },
)
def update_user_settings(
        settings_update: UserSettingsUpdate,
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
        service: Annotated[UserSettingsService, Depends(get_user_settings_service)],
) -> UserSettingsResponse:
    """
    Update settings for the current user.

    Only send the fields you want to change. Omitted fields remain unchanged.

    **Available Settings:**

    | Setting | Type | Options |
    |---------|------|---------|
    | `theme` | string | `light`, `dark`, `system` |
    | `date_format` | string | `YYYY-MM-DD`, `MM/DD/YYYY`, `DD/MM/YYYY` |
    | `number_format` | string | `US`, `EU` |
    | `default_currency` | string | 3-letter currency code (e.g., `EUR`, `USD`) |
    | `default_benchmark` | string | Benchmark ticker (e.g., `^GSPC`) or `null` |
    | `timezone` | string | IANA timezone (e.g., `Europe/Rome`) |
    """
    logger.info(
        f"Updating settings for user {current_user.id}: "
        f"{settings_update.model_dump(exclude_unset=True)}"
    )

    # Check if benchmark should be cleared (explicitly set to None)
    clear_benchmark = (
        settings_update.default_benchmark is None
        and "default_benchmark" in settings_update.model_fields_set
    )

    result = service.update_settings(
        db=db,
        user_id=current_user.id,
        theme=settings_update.theme,
        date_format=settings_update.date_format,
        number_format=settings_update.number_format,
        default_currency=settings_update.default_currency,
        default_benchmark=settings_update.default_benchmark,
        timezone_str=settings_update.timezone,
        clear_default_benchmark=clear_benchmark,
    )

    return UserSettingsResponse(
        theme=result.settings.theme,
        date_format=result.settings.date_format,
        number_format=result.settings.number_format,
        default_currency=result.settings.default_currency,
        default_benchmark=result.settings.default_benchmark,
        timezone=result.settings.timezone,
    )


# =============================================================================
# PROFILE ENDPOINTS
# =============================================================================

@router.get(
    "/me/profile",
    response_model=UserProfileResponse,
    summary="Get user profile",
    response_description="Current user profile",
    responses={
        200: {
            "description": "Profile retrieved successfully",
            "model": UserProfileResponse,
        },
        401: {
            "description": "Not authenticated",
        },
    },
)
def get_user_profile(
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
        service: Annotated[UserSettingsService, Depends(get_user_settings_service)],
) -> UserProfileResponse:
    """
    Get profile for the current user.

    Returns user information including:
    - Email (read-only)
    - Full name (editable)
    - Profile picture URL (from OAuth, read-only)
    - Whether user has a password set
    - OAuth provider (if signed up via OAuth)
    - Account creation date
    """
    user = service.get_profile(db, current_user.id)

    return UserProfileResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        picture_url=user.picture_url,
        has_password=user.hashed_password is not None,
        oauth_provider=user.oauth_provider,
        created_at=user.created_at,
    )


@router.patch(
    "/me/profile",
    response_model=UserProfileResponse,
    summary="Update user profile",
    response_description="Updated user profile",
    responses={
        200: {
            "description": "Profile updated successfully",
            "model": UserProfileResponse,
        },
        401: {
            "description": "Not authenticated",
        },
    },
)
def update_user_profile(
        profile_update: UserProfileUpdate,
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
        service: Annotated[UserSettingsService, Depends(get_user_settings_service)],
) -> UserProfileResponse:
    """
    Update profile for the current user.

    Currently only supports updating:
    - `full_name`: User's display name

    Email cannot be changed.
    """
    logger.info(
        f"Updating profile for user {current_user.id}: "
        f"{profile_update.model_dump(exclude_unset=True)}"
    )

    result = service.update_profile(
        db=db,
        user_id=current_user.id,
        full_name=profile_update.full_name,
    )

    return UserProfileResponse(
        id=result.user.id,
        email=result.user.email,
        full_name=result.user.full_name,
        picture_url=result.user.picture_url,
        has_password=result.user.hashed_password is not None,
        oauth_provider=result.user.oauth_provider,
        created_at=result.user.created_at,
    )


# =============================================================================
# PASSWORD ENDPOINTS
# =============================================================================

@router.post(
    "/me/password",
    response_model=MessageResponse,
    summary="Change password",
    response_description="Password change confirmation",
    responses={
        200: {
            "description": "Password changed successfully",
            "model": MessageResponse,
        },
        400: {
            "description": "Invalid current password or OAuth-only account",
        },
        401: {
            "description": "Not authenticated",
        },
    },
)
def change_password(
        password_request: PasswordChangeRequest,
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
        service: Annotated[UserSettingsService, Depends(get_user_settings_service)],
) -> MessageResponse:
    """
    Change password for the current user.

    Requires the current password for verification.

    **Note:** This endpoint is only available for users who have a password set.
    OAuth-only users (e.g., signed up via Google) cannot use this endpoint.
    """
    logger.info(f"Password change requested for user {current_user.id}")

    service.change_password(
        db=db,
        user_id=current_user.id,
        current_password=password_request.current_password,
        new_password=password_request.new_password,
    )

    return MessageResponse(message="Password changed successfully")


# =============================================================================
# ACCOUNT DELETION (DANGER ZONE)
# =============================================================================

@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete account",
    response_description="Account deleted successfully",
    responses={
        204: {
            "description": "Account deleted successfully",
        },
        400: {
            "description": "Invalid password or confirmation",
        },
        401: {
            "description": "Not authenticated",
        },
    },
)
def delete_account(
        delete_request: AccountDeleteRequest,
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
        service: Annotated[UserSettingsService, Depends(get_user_settings_service)],
) -> None:
    """
    Delete the current user's account.

    **WARNING: This action is irreversible!**

    This will permanently delete:
    - Your user account
    - All your portfolios
    - All transactions in your portfolios
    - All your settings

    **Requirements:**
    - `confirmation` must be exactly `"DELETE"`
    - `password` is required for users with password authentication

    OAuth-only users (e.g., signed up via Google) do not need to provide a password.
    """
    logger.warning(f"Account deletion requested for user {current_user.id}")

    service.delete_account(
        db=db,
        user_id=current_user.id,
        password=delete_request.password,
    )

    logger.warning(f"Account deleted: user {current_user.id} ({current_user.email})")
