# backend/app/config.py
"""
Application configuration using Pydantic Settings.

Loads configuration from environment variables with validation:
- ENVIRONMENT: Runtime mode (development, test, production)
- DATABASE_URL: PostgreSQL connection string (required except in test)
- DB_POOL_*: Connection pool settings for PostgreSQL

Environment-specific behavior:
- test: Allows SQLite in-memory database for fast isolated tests
- development: Requires DATABASE_URL, warns if using SQLite
- production: Requires PostgreSQL, enforces strict validation

Configuration is validated on application startup. Invalid configuration
will raise a ValueError with a descriptive message.

Usage:
    from app.config import settings

    if settings.is_production:
        # Production-specific logic
        ...
"""
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Find the .env file in project root (parent of backend/)
# This ensures a single .env for both Docker Compose and the app
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Environment variables:
        - ENVIRONMENT: Runtime environment (development, test, production)
        - DATABASE_URL: PostgreSQL connection string (required except in test)
        - APP_NAME: Application name (default: "Investment Portfolio Analyzer")
        - DEBUG: Enable debug mode (default: False)
        - LOG_LEVEL: Logging level (default: "INFO")

    Database Pool Settings (optional, with sensible defaults):
        - DB_POOL_SIZE: Number of persistent connections (default: 5)
        - DB_POOL_MAX_OVERFLOW: Extra connections allowed (default: 10)
        - DB_POOL_RECYCLE: Connection lifetime in seconds (default: 3600)
        - DB_POOL_PRE_PING: Test connections before use (default: True)
    """

    # Environment mode - determines validation strictness
    environment: Literal["development", "test", "production"] = Field(
        default="development",
        description="Runtime environment (development, test, production)"
    )

    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )

    # Database URL - no default, must be explicitly set (except in test mode)
    database_url: str | None = Field(
        default=None,
        description="PostgreSQL connection string (required in production)"
    )

    # Connection pool settings with production-ready defaults
    db_pool_size: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of persistent database connections"
    )
    db_pool_max_overflow: int = Field(
        default=10,
        ge=0,
        le=30,
        description="Maximum overflow connections beyond pool_size"
    )
    db_pool_recycle: int = Field(
        default=3600,
        ge=300,
        description="Connection lifetime in seconds before recycling"
    )
    db_pool_pre_ping: bool = Field(
        default=True,
        description="Test connection health before checkout"
    )

    # Optional - safe defaults
    app_name: str = "Investment Portfolio Analyzer"
    debug: bool = False

    # =========================================================================
    # JWT AUTHENTICATION
    # =========================================================================
    jwt_secret_key: str | None = Field(
        default=None,
        min_length=32,
        description="Secret key for JWT signing (min 32 chars, required in production)"
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="Algorithm for JWT signing"
    )
    jwt_access_token_expire_minutes: int = Field(
        default=15,
        ge=1,
        le=60,
        description="Access token expiration in minutes"
    )
    jwt_refresh_token_expire_days: int = Field(
        default=30,
        ge=1,
        le=90,
        description="Refresh token expiration in days"
    )

    # =========================================================================
    # GOOGLE OAUTH
    # =========================================================================
    google_client_id: str | None = Field(
        default=None,
        description="Google OAuth2 client ID"
    )
    google_client_secret: str | None = Field(
        default=None,
        description="Google OAuth2 client secret"
    )
    google_redirect_uri: str = Field(
        default="http://localhost:8000/auth/google/callback",
        description="Google OAuth2 redirect URI"
    )

    # =========================================================================
    # EMAIL / SMTP
    # =========================================================================
    smtp_host: str | None = Field(
        default=None,
        description="SMTP server host"
    )
    smtp_port: int = Field(
        default=587,
        description="SMTP server port"
    )
    smtp_user: str | None = Field(
        default=None,
        description="SMTP username"
    )
    smtp_password: str | None = Field(
        default=None,
        description="SMTP password"
    )
    smtp_from_email: str | None = Field(
        default=None,
        description="Email address for sending emails"
    )
    smtp_from_name: str = Field(
        default="Investment Portfolio Analyzer",
        description="Display name for sent emails"
    )
    email_verification_expire_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Email verification token expiration in hours"
    )
    password_reset_expire_hours: int = Field(
        default=1,
        ge=1,
        le=24,
        description="Password reset token expiration in hours"
    )

    # =========================================================================
    # FRONTEND
    # =========================================================================
    frontend_url: str = Field(
        default="http://localhost:3000",
        description="Frontend URL for email links"
    )

    # =========================================================================
    # CORS
    # =========================================================================
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed CORS origins (comma-separated in env var)"
    )
    cors_allow_credentials: bool = Field(
        default=True,
        description="Allow credentials in CORS requests"
    )
    cors_allow_methods: list[str] = Field(
        default=["*"],
        description="Allowed HTTP methods for CORS"
    )
    cors_allow_headers: list[str] = Field(
        default=["*"],
        description="Allowed HTTP headers for CORS"
    )

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Allow extra vars (e.g., POSTGRES_* for Docker Compose)
    )

    @model_validator(mode="after")
    def validate_database_config(self) -> "Settings":
        """
        Validate database configuration based on environment.

        Rules:
        - test: SQLite allowed (for fast isolated tests)
        - development: DATABASE_URL required, SQLite allowed with warning
        - production: DATABASE_URL required, must be PostgreSQL
        """
        if self.environment == "test":
            # Test mode: allow SQLite for fast isolated tests
            if self.database_url is None:
                # Provide in-memory SQLite for tests only
                object.__setattr__(self, "database_url", "sqlite:///:memory:")
            # Provide test JWT secret if not set
            if self.jwt_secret_key is None:
                object.__setattr__(self, "jwt_secret_key", "test-secret-key-for-testing-only-32chars")
            return self

        # Development and production require DATABASE_URL
        if self.database_url is None:
            raise ValueError(
                f"DATABASE_URL is required in {self.environment} environment. "
                "Set the DATABASE_URL environment variable to a PostgreSQL connection string. "
                "Example: postgresql://user:password@localhost:5432/dbname"
            )

        # Validate URL format
        url_lower = self.database_url.lower()

        if self.environment == "production":
            # Production: must be PostgreSQL
            if not url_lower.startswith(("postgresql://", "postgresql+psycopg2://")):
                raise ValueError(
                    "Production environment requires PostgreSQL. "
                    f"DATABASE_URL must start with 'postgresql://', got: {self.database_url[:20]}..."
                )
            # Production: JWT secret key is required
            if self.jwt_secret_key is None:
                raise ValueError(
                    "JWT_SECRET_KEY is required in production environment. "
                    "Set JWT_SECRET_KEY to a secure random string (minimum 32 characters)."
                )
        elif self.environment == "development":
            # Development: warn if using SQLite
            if url_lower.startswith("sqlite://"):
                import warnings
                warnings.warn(
                    "Using SQLite in development mode. Some PostgreSQL-specific "
                    "features (ON CONFLICT, DECIMAL precision) may not work correctly. "
                    "Consider using PostgreSQL for development to match production.",
                    UserWarning,
                    stacklevel=2,
                )

        return self

    @property
    def is_sqlite(self) -> bool:
        """Check if using SQLite database."""
        return self.database_url is not None and self.database_url.lower().startswith("sqlite://")

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == "production"

    @property
    def is_test(self) -> bool:
        """Check if running in test environment."""
        return self.environment == "test"

    @property
    def is_email_configured(self) -> bool:
        """Check if email/SMTP is properly configured."""
        return all([
            self.smtp_host,
            self.smtp_user,
            self.smtp_password,
            self.smtp_from_email,
        ])

    @property
    def is_google_oauth_configured(self) -> bool:
        """Check if Google OAuth is properly configured."""
        return all([
            self.google_client_id,
            self.google_client_secret,
        ])


# Create single instance
settings = Settings()
