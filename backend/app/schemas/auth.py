"""
Authentication request/response schemas.

Defines Pydantic models for:
- User registration
- Login
- Token responses
- Password reset
- Email verification
- User profile
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# =============================================================================
# REQUEST SCHEMAS
# =============================================================================


class UserRegisterRequest(BaseModel):
    """Request body for user registration."""

    email: EmailStr = Field(
        ...,
        description="User's email address",
        examples=["user@example.com"],
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Password (min 8 characters)",
        examples=["MySecurePassword123!"],
    )
    full_name: str | None = Field(
        None,
        max_length=255,
        description="User's full name",
        examples=["John Doe"],
    )

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Validate password has minimum complexity."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        # Could add more complexity requirements here
        return v


class UserLoginRequest(BaseModel):
    """Request body for user login."""

    email: EmailStr = Field(
        ...,
        description="User's email address",
        examples=["user@example.com"],
    )
    password: str = Field(
        ...,
        description="User's password",
        examples=["MySecurePassword123!"],
    )


class TokenRefreshRequest(BaseModel):
    """Request body for token refresh."""

    refresh_token: str = Field(
        ...,
        description="Refresh token from login",
    )


class VerifyEmailRequest(BaseModel):
    """Request body for email verification."""

    token: str = Field(
        ...,
        description="Email verification token",
    )


class ResendVerificationRequest(BaseModel):
    """Request body for resending verification email."""

    email: EmailStr = Field(
        ...,
        description="User's email address",
        examples=["user@example.com"],
    )


class ForgotPasswordRequest(BaseModel):
    """Request body for password reset request."""

    email: EmailStr = Field(
        ...,
        description="User's email address",
        examples=["user@example.com"],
    )


class ResetPasswordRequest(BaseModel):
    """Request body for password reset."""

    token: str = Field(
        ...,
        description="Password reset token",
    )
    new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="New password (min 8 characters)",
        examples=["MyNewSecurePassword123!"],
    )

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Validate password has minimum complexity."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LogoutRequest(BaseModel):
    """Request body for logout."""

    refresh_token: str = Field(
        ...,
        description="Refresh token to revoke",
    )


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================


class TokenResponse(BaseModel):
    """Response containing access and refresh tokens."""

    access_token: str = Field(
        ...,
        description="JWT access token",
    )
    refresh_token: str = Field(
        ...,
        description="Refresh token for obtaining new access tokens",
    )
    token_type: str = Field(
        default="bearer",
        description="Token type (always 'bearer')",
    )
    expires_in: int = Field(
        ...,
        description="Access token expiration time in seconds",
    )


class UserResponse(BaseModel):
    """Response containing user profile information."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(
        ...,
        description="User's unique ID",
    )
    email: str = Field(
        ...,
        description="User's email address",
    )
    full_name: str | None = Field(
        None,
        description="User's full name",
    )
    picture_url: str | None = Field(
        None,
        description="URL to user's profile picture",
    )
    is_email_verified: bool = Field(
        ...,
        description="Whether email is verified",
    )
    oauth_provider: str | None = Field(
        None,
        description="OAuth provider if user signed up via OAuth",
    )
    created_at: datetime = Field(
        ...,
        description="When the user account was created",
    )


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str = Field(
        ...,
        description="Response message",
    )


class GoogleAuthUrlResponse(BaseModel):
    """Response containing Google OAuth authorization URL."""

    authorization_url: str = Field(
        ...,
        description="URL to redirect user to for Google OAuth",
    )
    state: str = Field(
        ...,
        description="State parameter for CSRF protection (store in session)",
    )
