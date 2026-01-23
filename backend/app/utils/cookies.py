"""
HTTP cookie utilities for secure token management.

Provides consistent cookie settings for authentication tokens.
Refresh tokens are stored in httpOnly cookies to prevent XSS attacks.
"""

from fastapi import Response

from app.config import settings


# Cookie name for refresh token
REFRESH_TOKEN_COOKIE = "refresh_token"


def set_refresh_token_cookie(
    response: Response,
    refresh_token: str,
    max_age_days: int | None = None,
) -> None:
    """
    Set the refresh token as an httpOnly cookie.

    Args:
        response: FastAPI Response object
        refresh_token: The refresh token value
        max_age_days: Cookie max age in days (defaults to jwt_refresh_token_expire_days)
    """
    if max_age_days is None:
        max_age_days = settings.jwt_refresh_token_expire_days

    max_age_seconds = max_age_days * 24 * 60 * 60

    # Determine if we're in a secure context (HTTPS)
    # In production, always use Secure cookies
    # In development (localhost), browsers allow non-Secure cookies
    is_secure = settings.is_production

    # SameSite=Lax allows the cookie to be sent on top-level navigations
    # (e.g., clicking a link) but not on cross-site POST requests.
    # This provides CSRF protection while allowing the refresh flow to work.
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=refresh_token,
        max_age=max_age_seconds,
        httponly=True,  # Not accessible via JavaScript
        secure=is_secure,  # Only sent over HTTPS in production
        samesite="lax",  # CSRF protection
        path="/auth",  # Only sent to /auth/* endpoints
    )


def clear_refresh_token_cookie(response: Response) -> None:
    """
    Clear the refresh token cookie.

    Args:
        response: FastAPI Response object
    """
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE,
        path="/auth",  # Must match the path used when setting
    )


def get_refresh_token_from_cookie(cookies: dict[str, str]) -> str | None:
    """
    Extract refresh token from request cookies.

    Args:
        cookies: Request cookies dictionary

    Returns:
        Refresh token string or None if not present
    """
    return cookies.get(REFRESH_TOKEN_COOKIE)
