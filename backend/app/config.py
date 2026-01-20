# backend/app/config.py
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Find the .env file relative to this config file (backend/.env)
# This ensures it works regardless of the current working directory
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Environment variables:
        - DATABASE_URL: PostgreSQL connection string (required in production,
                        defaults to SQLite for tests)
        - APP_NAME: Application name (default: "Investment Portfolio Analyzer")
        - DEBUG: Enable debug mode (default: False)
        - LOG_LEVEL: Logging level (default: "DEBUG")
    """

    log_level: str = Field(
        default="DEBUG",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )

    # Database URL - defaults to in-memory SQLite for tests
    # In production, always set DATABASE_URL environment variable
    database_url: str = Field(
        default="sqlite:///:memory:",
        description="Database connection string"
    )

    # Optional - safe defaults
    app_name: str = "Investment Portfolio Analyzer"
    debug: bool = False

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


# Create single instance
settings = Settings()
