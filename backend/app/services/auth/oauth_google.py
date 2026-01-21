"""
Google OAuth2 integration.

Handles:
- OAuth authorization URL generation
- Token exchange
- User info retrieval
- User creation/login via OAuth

Uses httpx for async HTTP requests to Google's OAuth endpoints.
"""

import logging
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.services.exceptions import OAuthError


logger = logging.getLogger(__name__)


# Google OAuth endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


@dataclass
class GoogleUserInfo:
    """User information from Google OAuth."""
    id: str
    email: str
    verified_email: bool
    name: str | None = None
    picture: str | None = None


class GoogleOAuthService:
    """
    Service for Google OAuth2 authentication.

    Flow:
    1. get_authorization_url() - Returns URL to redirect user to Google
    2. User authorizes on Google, redirected back with code
    3. exchange_code_for_tokens() - Exchange code for access token
    4. get_user_info() - Get user info from Google
    """

    @staticmethod
    def get_authorization_url(state: str | None = None) -> tuple[str, str]:
        """
        Generate Google OAuth authorization URL.

        Args:
            state: Optional state parameter for CSRF protection.
                  If not provided, a random one will be generated.

        Returns:
            Tuple of (authorization_url, state)

        Raises:
            OAuthError: If Google OAuth is not configured
        """
        if not settings.is_google_oauth_configured:
            raise OAuthError("google", "Google OAuth is not configured")

        if state is None:
            state = secrets.token_urlsafe(32)

        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",  # Get refresh token
            "prompt": "consent",  # Always show consent screen
        }

        url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
        return url, state

    @staticmethod
    async def exchange_code_for_tokens(code: str) -> dict:
        """
        Exchange authorization code for tokens.

        Args:
            code: Authorization code from Google callback

        Returns:
            Dict containing access_token, refresh_token, etc.

        Raises:
            OAuthError: If token exchange fails
        """
        if not settings.is_google_oauth_configured:
            raise OAuthError("google", "Google OAuth is not configured")

        data = {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.google_redirect_uri,
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    GOOGLE_TOKEN_URL,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

                if response.status_code != 200:
                    error_data = response.json()
                    error_msg = error_data.get("error_description", error_data.get("error", "Unknown error"))
                    raise OAuthError("google", f"Token exchange failed: {error_msg}")

                return response.json()

            except httpx.RequestError as e:
                raise OAuthError("google", f"Network error during token exchange: {str(e)}")

    @staticmethod
    async def get_user_info(access_token: str) -> GoogleUserInfo:
        """
        Get user information from Google.

        Args:
            access_token: Google access token

        Returns:
            GoogleUserInfo dataclass with user details

        Raises:
            OAuthError: If user info retrieval fails
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )

                if response.status_code != 200:
                    raise OAuthError("google", f"Failed to get user info: {response.text}")

                data = response.json()

                return GoogleUserInfo(
                    id=data["id"],
                    email=data["email"],
                    verified_email=data.get("verified_email", False),
                    name=data.get("name"),
                    picture=data.get("picture"),
                )

            except httpx.RequestError as e:
                raise OAuthError("google", f"Network error getting user info: {str(e)}")

    @staticmethod
    def validate_state(received_state: str, expected_state: str) -> bool:
        """
        Validate OAuth state parameter for CSRF protection.

        Args:
            received_state: State received in callback
            expected_state: State that was sent in authorization URL

        Returns:
            True if states match

        Raises:
            OAuthError: If states don't match
        """
        if not secrets.compare_digest(received_state, expected_state):
            raise OAuthError("google", "Invalid state parameter (possible CSRF attack)")
        return True
