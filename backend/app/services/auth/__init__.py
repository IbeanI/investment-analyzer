"""
Authentication services for the Investment Portfolio Analyzer.

This module provides:
- Password hashing and verification (bcrypt)
- JWT token creation and validation
- OAuth2 integration (Google)
- Email verification and password reset
- Core authentication service (AuthService)

Usage:
    from app.services.auth import AuthService, PasswordService, JWTHandler

    # Hash a password
    hashed = PasswordService.hash_password("mypassword")

    # Verify a password
    is_valid = PasswordService.verify_password("mypassword", hashed)

    # Create access token
    token = JWTHandler.create_access_token(user_id=1, email="user@example.com")

    # Validate token
    payload = JWTHandler.validate_access_token(token)
"""

from app.services.auth.password import PasswordService
from app.services.auth.jwt_handler import JWTHandler
from app.services.auth.service import AuthService
from app.services.auth.email_service import EmailService
from app.services.auth.oauth_google import GoogleOAuthService, get_oauth_state_store

__all__ = [
    "PasswordService",
    "JWTHandler",
    "AuthService",
    "EmailService",
    "GoogleOAuthService",
    "get_oauth_state_store",
]
