# backend/app/schemas/user_profile.py
"""
User profile request/response schemas.

Defines Pydantic models for:
- Profile viewing
- Profile updates (name only, email is read-only)
- Password change
- Account deletion
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================


class UserProfileResponse(BaseModel):
    """Response containing user profile information."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(
        ...,
        description="User's unique ID",
    )
    email: str = Field(
        ...,
        description="User's email address (read-only)",
    )
    full_name: str | None = Field(
        None,
        description="User's full name",
    )
    picture_url: str | None = Field(
        None,
        description="URL to user's profile picture (from OAuth)",
    )
    has_password: bool = Field(
        ...,
        description="Whether user has a password set (false for OAuth-only users)",
    )
    oauth_provider: str | None = Field(
        None,
        description="OAuth provider if user signed up via OAuth (e.g., 'google')",
    )
    created_at: datetime = Field(
        ...,
        description="When the user account was created",
    )


# =============================================================================
# REQUEST SCHEMAS
# =============================================================================


class UserProfileUpdate(BaseModel):
    """Request body for updating user profile (partial update)."""

    full_name: str | None = Field(
        None,
        max_length=255,
        description="User's full name",
        examples=["Daniel Zito"],
    )


class PasswordChangeRequest(BaseModel):
    """Request body for changing password."""

    current_password: str = Field(
        ...,
        description="User's current password",
        examples=["currentPassword123"],
    )
    new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="New password (min 8 characters)",
        examples=["newSecurePassword456"],
    )

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Validate password has minimum complexity."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class AccountDeleteRequest(BaseModel):
    """Request body for account deletion."""

    password: str | None = Field(
        None,
        description="User's password (required for users with password)",
        examples=["myPassword123"],
    )
    confirmation: str = Field(
        ...,
        description="Must be exactly 'DELETE' to confirm deletion",
        examples=["DELETE"],
    )

    @field_validator("confirmation")
    @classmethod
    def validate_confirmation(cls, v: str) -> str:
        """Ensure confirmation is exactly 'DELETE'."""
        if v != "DELETE":
            raise ValueError("Confirmation must be exactly 'DELETE'")
        return v
