from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Required environment variables:
        - DATABASE_URL: PostgreSQL connection string

    Optional:
        - APP_NAME: Application name (default: "Investment Portfolio Analyzer")
        - DEBUG: Enable debug mode (default: False)
    """

    # Required - no defaults for sensitive data
    database_url: str

    # Optional - safe defaults
    app_name: str = "Investment Portfolio Analyzer"
    debug: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


# Create single instance
settings = Settings()
