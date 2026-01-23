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

Security:
- Refresh tokens are stored in httpOnly cookies to prevent XSS attacks
- Access tokens are returned in the response body (short-lived, 15 min)
- Token rotation on each refresh with replay attack detection
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Query, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.middleware.rate_limit import (
    limiter,
    RATE_LIMIT_AUTH_LOGIN,
    RATE_LIMIT_AUTH_REGISTER,
    RATE_LIMIT_AUTH_PASSWORD_RESET,
    RATE_LIMIT_AUTH_EMAIL,
    RATE_LIMIT_AUTH_REFRESH,
)
from app.models import User
from app.schemas.auth import (
    UserRegisterRequest,
    UserLoginRequest,
    VerifyEmailRequest,
    ResendVerificationRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    LogoutRequest,
    AccessTokenResponse,
    TokenResponse,
    UserResponse,
    MessageResponse,
    GoogleAuthUrlResponse,
)
from app.services.auth import AuthService, GoogleOAuthService
from app.services.auth.service import TokenPair
from app.services.auth.oauth_google import get_oauth_state_store
from app.services.exceptions import InvalidCredentialsError
from app.dependencies import get_auth_service, get_current_user
from app.utils.cookies import (
    REFRESH_TOKEN_COOKIE,
    set_refresh_token_cookie,
    clear_refresh_token_cookie,
)


router = APIRouter(prefix="/auth", tags=["Authentication"])


def _token_pair_to_access_response(tokens: TokenPair) -> AccessTokenResponse:
    """Convert TokenPair to AccessTokenResponse (without refresh token in body)."""
    return AccessTokenResponse(
        access_token=tokens.access_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
    )


def _token_pair_to_response(tokens: TokenPair) -> TokenResponse:
    """Convert TokenPair to TokenResponse (legacy, includes refresh token)."""
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
    )


def _get_client_info(request: Request) -> tuple[str | None, str | None]:
    """
    Extract device info and IP address from request.

    Only trusts X-Forwarded-For headers when the immediate client is a
    trusted proxy to prevent IP spoofing attacks.

    Args:
        request: Starlette/FastAPI request object

    Returns:
        Tuple of (device_info, ip_address)
    """
    from app.config import settings

    device_info = request.headers.get("User-Agent")
    ip_address = request.client.host if request.client else None

    # Check if we should trust forwarded headers
    is_trusted = settings.trust_proxy_headers or (ip_address in settings.trusted_proxy_ips)

    # Only use X-Forwarded-For from trusted proxies
    if is_trusted:
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
@limiter.limit(RATE_LIMIT_AUTH_REGISTER)
def register(
    request: Request,  # Required for rate limiter
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
    response_model=AccessTokenResponse,
    summary="Login with email and password",
    description=(
        "Authenticate with email and password. Returns access token in response body. "
        "Refresh token is set as an httpOnly cookie for security."
    ),
)
@limiter.limit(RATE_LIMIT_AUTH_LOGIN)
def login(
    data: UserLoginRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> JSONResponse:
    """Login with email and password."""
    device_info, ip_address = _get_client_info(request)

    tokens = auth_service.login(
        db=db,
        email=data.email,
        password=data.password,
        device_info=device_info,
        ip_address=ip_address,
    )

    # Create response with access token only
    response_data = _token_pair_to_access_response(tokens)
    response = JSONResponse(content=response_data.model_dump())

    # Set refresh token as httpOnly cookie
    set_refresh_token_cookie(response, tokens.refresh_token)

    return response


# =============================================================================
# TOKEN MANAGEMENT
# =============================================================================


@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    summary="Refresh access token",
    description=(
        "Get a new access token using the refresh token from the httpOnly cookie. "
        "The old refresh token is invalidated and a new one is set in the cookie."
    ),
)
@limiter.limit(RATE_LIMIT_AUTH_REFRESH)
def refresh_token(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_TOKEN_COOKIE)] = None,
) -> JSONResponse:
    """Refresh access token using refresh token from cookie."""
    # Get refresh token from cookie
    if not refresh_token:
        raise InvalidCredentialsError("No refresh token provided")

    device_info, ip_address = _get_client_info(request)

    tokens = auth_service.refresh_tokens(
        db=db,
        refresh_token=refresh_token,
        device_info=device_info,
        ip_address=ip_address,
    )

    # Create response with access token only
    response_data = _token_pair_to_access_response(tokens)
    response = JSONResponse(content=response_data.model_dump())

    # Set new refresh token as httpOnly cookie (token rotation)
    set_refresh_token_cookie(response, tokens.refresh_token)

    return response


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Logout (revoke refresh token)",
    description="Revoke the refresh token from the cookie, ending the session.",
)
def logout(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_TOKEN_COOKIE)] = None,
    data: LogoutRequest | None = None,
) -> JSONResponse:
    """Logout by revoking refresh token."""
    # Try to get refresh token from cookie first, then from request body (backwards compat)
    token_to_revoke = refresh_token
    if not token_to_revoke and data and data.refresh_token:
        token_to_revoke = data.refresh_token

    if token_to_revoke:
        auth_service.logout(db=db, refresh_token=token_to_revoke)

    # Create response and clear the cookie
    response = JSONResponse(
        content=MessageResponse(message="Successfully logged out").model_dump()
    )
    clear_refresh_token_cookie(response)

    return response


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
) -> JSONResponse:
    """Logout from all sessions."""
    count = auth_service.logout_all(db=db, user_id=current_user.id)

    # Create response and clear the cookie
    response = JSONResponse(
        content=MessageResponse(
            message=f"Logged out from {count} session(s)"
        ).model_dump()
    )
    clear_refresh_token_cookie(response)

    return response


# =============================================================================
# EMAIL VERIFICATION
# =============================================================================


@router.post(
    "/verify-email",
    response_model=MessageResponse,
    summary="Verify email address",
    description="Verify email address using the token sent via email.",
)
@limiter.limit(RATE_LIMIT_AUTH_EMAIL)
def verify_email(
    request: Request,  # Required for rate limiter
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
@limiter.limit(RATE_LIMIT_AUTH_EMAIL)
def resend_verification(
    request: Request,  # Required for rate limiter
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
@limiter.limit(RATE_LIMIT_AUTH_PASSWORD_RESET)
def forgot_password(
    request: Request,  # Required for rate limiter
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
@limiter.limit(RATE_LIMIT_AUTH_PASSWORD_RESET)
def reset_password(
    request: Request,  # Required for rate limiter
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
    """
    Get Google OAuth authorization URL.

    The state parameter is stored server-side for CSRF validation.
    It must be passed back in the callback for the OAuth flow to succeed.
    """
    url, state = GoogleOAuthService.get_authorization_url()

    # Store state for CSRF validation in callback
    state_store = get_oauth_state_store()
    state_store.store(state)

    return GoogleAuthUrlResponse(authorization_url=url, state=state)


@router.get(
    "/google/callback",
    response_model=AccessTokenResponse,
    summary="Google OAuth callback",
    description=(
        "Handle the callback from Google OAuth. Exchange code for tokens and create/login user. "
        "Returns access token in response body, refresh token is set as httpOnly cookie."
    ),
)
async def google_callback(
    code: Annotated[str, Query(description="Authorization code from Google")],
    state: Annotated[str, Query(description="State parameter for CSRF protection")],
    db: Annotated[Session, Depends(get_db)],
    request: Request,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> JSONResponse:
    """
    Handle Google OAuth callback.

    This endpoint:
    1. Validates the state parameter (CSRF protection)
    2. Exchanges the authorization code for tokens
    3. Retrieves user info from Google
    4. Creates user if they don't exist, or logs them in
    5. Returns access token and sets refresh token as cookie
    """
    # Validate state parameter for CSRF protection
    # This will raise OAuthError if state is invalid or expired
    state_store = get_oauth_state_store()
    state_store.validate_and_consume(state)

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

    device_info, ip_address = _get_client_info(request)
    email_normalized = user_info.email.lower()

    # Find or create user with race condition handling
    # First, try to find existing user
    user = db.execute(
        select(User).where(User.email == email_normalized)
    ).scalar_one_or_none()

    if user:
        # Existing user - update OAuth info if needed
        if user.oauth_provider is None:
            user.oauth_provider = "google"
            user.oauth_provider_id = user_info.id

        # Update profile info from Google (only if not already set)
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
        # Create new user with race condition protection
        # If two requests try to create the same user simultaneously,
        # one will succeed and the other will get an IntegrityError.
        # We handle this by catching the error and fetching the created user.
        try:
            user = User(
                email=email_normalized,
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
        except IntegrityError:
            # Race condition: another request created this user
            # Rollback the failed transaction and fetch the existing user
            db.rollback()
            user = db.execute(
                select(User).where(User.email == email_normalized)
            ).scalar_one_or_none()

            if user is None:
                # This shouldn't happen, but handle it gracefully
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create or find user after OAuth",
                )

    # Create tokens
    tokens = auth_service._create_token_pair(
        db=db,
        user=user,
        device_info=device_info,
        ip_address=ip_address,
    )

    # Create response with access token only
    response_data = _token_pair_to_access_response(tokens)
    response = JSONResponse(content=response_data.model_dump())

    # Set refresh token as httpOnly cookie
    set_refresh_token_cookie(response, tokens.refresh_token)

    return response
