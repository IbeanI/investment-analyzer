"""
Authentication endpoints.

Provides:
- POST /auth/register - Register new user
- POST /auth/login - Login with email/password
- POST /auth/refresh - Refresh access token
- POST /auth/logout - Logout (revoke refresh token)
- POST /auth/logout/all - Logout from all sessions
- POST /auth/verify-email - Verify email with token
- POST /auth/resend-verification - Resend verification email
- POST /auth/forgot-password - Request password reset
- POST /auth/reset-password - Reset password with token
- GET /auth/me - Get current user profile
- GET /auth/google - Get Google OAuth URL
- GET /auth/google/callback - Handle Google OAuth callback
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Query, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
from app.schemas.auth import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenRefreshRequest,
    VerifyEmailRequest,
    ResendVerificationRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    LogoutRequest,
    TokenResponse,
    UserResponse,
    MessageResponse,
    GoogleAuthUrlResponse,
)
from app.services.auth import AuthService, GoogleOAuthService
from app.services.auth.service import TokenPair
from app.dependencies import get_auth_service, get_current_user


router = APIRouter(prefix="/auth", tags=["Authentication"])


def _token_pair_to_response(tokens: TokenPair) -> TokenResponse:
    """Convert TokenPair to TokenResponse."""
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
    )


def _get_client_info(request: Request) -> tuple[str | None, str | None]:
    """Extract device info and IP address from request."""
    device_info = request.headers.get("User-Agent")
    ip_address = request.client.host if request.client else None
    # Handle X-Forwarded-For for proxied requests
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip_address = forwarded_for.split(",")[0].strip()
    return device_info, ip_address


# =============================================================================
# REGISTRATION & LOGIN
# =============================================================================


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Create a new user account with email and password. A verification email will be sent.",
)
def register(
    data: UserRegisterRequest,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    """Register a new user with email/password."""
    user = auth_service.register(
        db=db,
        email=data.email,
        password=data.password,
        full_name=data.full_name,
    )
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with email and password",
    description="Authenticate with email and password. Returns access and refresh tokens.",
)
def login(
    data: UserLoginRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """Login with email and password."""
    device_info, ip_address = _get_client_info(request)

    tokens = auth_service.login(
        db=db,
        email=data.email,
        password=data.password,
        device_info=device_info,
        ip_address=ip_address,
    )
    return _token_pair_to_response(tokens)


# =============================================================================
# TOKEN MANAGEMENT
# =============================================================================


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description="Get a new access token using a refresh token. The old refresh token is invalidated.",
)
def refresh_token(
    data: TokenRefreshRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """Refresh access token using refresh token."""
    device_info, ip_address = _get_client_info(request)

    tokens = auth_service.refresh_tokens(
        db=db,
        refresh_token=data.refresh_token,
        device_info=device_info,
        ip_address=ip_address,
    )
    return _token_pair_to_response(tokens)


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Logout (revoke refresh token)",
    description="Revoke the provided refresh token, ending the session.",
)
def logout(
    data: LogoutRequest,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    """Logout by revoking refresh token."""
    auth_service.logout(db=db, refresh_token=data.refresh_token)
    return MessageResponse(message="Successfully logged out")


@router.post(
    "/logout/all",
    response_model=MessageResponse,
    summary="Logout from all sessions",
    description="Revoke all refresh tokens for the current user, ending all sessions.",
)
def logout_all(
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MessageResponse:
    """Logout from all sessions."""
    count = auth_service.logout_all(db=db, user_id=current_user.id)
    return MessageResponse(message=f"Logged out from {count} session(s)")


# =============================================================================
# EMAIL VERIFICATION
# =============================================================================


@router.post(
    "/verify-email",
    response_model=MessageResponse,
    summary="Verify email address",
    description="Verify email address using the token sent via email.",
)
def verify_email(
    data: VerifyEmailRequest,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    """Verify email with token."""
    auth_service.verify_email(db=db, token=data.token)
    return MessageResponse(message="Email verified successfully")


@router.post(
    "/resend-verification",
    response_model=MessageResponse,
    summary="Resend verification email",
    description="Resend the email verification link. Works even if email doesn't exist (for security).",
)
def resend_verification(
    data: ResendVerificationRequest,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    """Resend verification email."""
    auth_service.resend_verification_email(db=db, email=data.email)
    return MessageResponse(message="If that email exists, a verification link has been sent")


# =============================================================================
# PASSWORD RESET
# =============================================================================


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request password reset",
    description="Request a password reset email. Works even if email doesn't exist (for security).",
)
def forgot_password(
    data: ForgotPasswordRequest,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    """Request password reset email."""
    auth_service.request_password_reset(db=db, email=data.email)
    return MessageResponse(message="If that email exists, a password reset link has been sent")


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Reset password",
    description="Reset password using the token from the reset email.",
)
def reset_password(
    data: ResetPasswordRequest,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    """Reset password with token."""
    auth_service.reset_password(db=db, token=data.token, new_password=data.new_password)
    return MessageResponse(message="Password reset successfully. Please login with your new password.")


# =============================================================================
# USER PROFILE
# =============================================================================


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
    description="Get the profile of the currently authenticated user.",
)
def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get current user profile."""
    return current_user


# =============================================================================
# GOOGLE OAUTH
# =============================================================================


@router.get(
    "/google",
    response_model=GoogleAuthUrlResponse,
    summary="Get Google OAuth URL",
    description="Get the URL to redirect the user to for Google OAuth authentication.",
)
def get_google_auth_url() -> GoogleAuthUrlResponse:
    """Get Google OAuth authorization URL."""
    url, state = GoogleOAuthService.get_authorization_url()
    return GoogleAuthUrlResponse(authorization_url=url, state=state)


@router.get(
    "/google/callback",
    response_model=TokenResponse,
    summary="Google OAuth callback",
    description="Handle the callback from Google OAuth. Exchange code for tokens and create/login user.",
)
async def google_callback(
    code: Annotated[str, Query(description="Authorization code from Google")],
    state: Annotated[str, Query(description="State parameter for CSRF protection")],
    db: Annotated[Session, Depends(get_db)],
    request: Request,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """
    Handle Google OAuth callback.

    This endpoint:
    1. Exchanges the authorization code for tokens
    2. Retrieves user info from Google
    3. Creates user if they don't exist, or logs them in
    4. Returns access and refresh tokens
    """
    # Exchange code for tokens
    google_tokens = await GoogleOAuthService.exchange_code_for_tokens(code)
    access_token = google_tokens.get("access_token")

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get access token from Google",
        )

    # Get user info from Google
    user_info = await GoogleOAuthService.get_user_info(access_token)

    # Find or create user
    user = db.execute(
        select(User).where(User.email == user_info.email.lower())
    ).scalar_one_or_none()

    device_info, ip_address = _get_client_info(request)

    if user:
        # Existing user - update OAuth info if needed
        if user.oauth_provider is None:
            user.oauth_provider = "google"
            user.oauth_provider_id = user_info.id

        # Update profile info from Google
        if user_info.name and not user.full_name:
            user.full_name = user_info.name
        if user_info.picture and not user.picture_url:
            user.picture_url = user_info.picture

        # Google users are always email-verified
        if not user.is_email_verified:
            user.is_email_verified = True
            user.email_verified_at = datetime.now(timezone.utc)

        db.commit()
    else:
        # Create new user
        user = User(
            email=user_info.email.lower(),
            full_name=user_info.name,
            picture_url=user_info.picture,
            oauth_provider="google",
            oauth_provider_id=user_info.id,
            is_email_verified=True,  # Google verifies email
            email_verified_at=datetime.now(timezone.utc),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # Create tokens
    tokens = auth_service._create_token_pair(
        db=db,
        user=user,
        device_info=device_info,
        ip_address=ip_address,
    )

    return _token_pair_to_response(tokens)
