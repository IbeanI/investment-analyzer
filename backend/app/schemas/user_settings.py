# backend/app/schemas/user_settings.py
"""
User settings request/response schemas.

Defines Pydantic models for:
- User display preferences (theme, date/number format)
- Portfolio defaults (currency, benchmark)
- Regional settings (timezone)
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# CONSTANTS
# =============================================================================

VALID_THEMES = ("light", "dark", "system")
VALID_DATE_FORMATS = ("YYYY-MM-DD", "MM/DD/YYYY", "DD/MM/YYYY")
VALID_NUMBER_FORMATS = ("US", "EU")


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================


class UserSettingsResponse(BaseModel):
    """Response containing user settings."""

    model_config = ConfigDict(from_attributes=True)

    theme: str = Field(
        ...,
        description="UI theme preference",
        examples=["system", "light", "dark"],
    )
    date_format: str = Field(
        ...,
        description="Date display format",
        examples=["YYYY-MM-DD", "MM/DD/YYYY", "DD/MM/YYYY"],
    )
    number_format: str = Field(
        ...,
        description="Number display format (US: 1,234.56, EU: 1.234,56)",
        examples=["US", "EU"],
    )
    default_currency: str = Field(
        ...,
        description="Default currency for new portfolios",
        examples=["EUR", "USD", "GBP"],
    )
    default_benchmark: str | None = Field(
        None,
        description="Default benchmark ticker for new portfolios",
        examples=["^GSPC", "^STOXX50E", "^FTSE"],
    )
    timezone: str = Field(
        ...,
        description="User's timezone (IANA format)",
        examples=["UTC", "Europe/Rome", "America/New_York"],
    )


# =============================================================================
# REQUEST SCHEMAS
# =============================================================================


class UserSettingsUpdate(BaseModel):
    """Request body for updating user settings (partial update)."""

    theme: Literal["light", "dark", "system"] | None = Field(
        None,
        description="UI theme preference",
        examples=["dark"],
    )
    date_format: Literal["YYYY-MM-DD", "MM/DD/YYYY", "DD/MM/YYYY"] | None = Field(
        None,
        description="Date display format",
        examples=["YYYY-MM-DD"],
    )
    number_format: Literal["US", "EU"] | None = Field(
        None,
        description="Number display format",
        examples=["US"],
    )
    default_currency: str | None = Field(
        None,
        min_length=3,
        max_length=3,
        description="Default currency for new portfolios (3-letter code)",
        examples=["EUR"],
    )
    default_benchmark: str | None = Field(
        None,
        max_length=20,
        description="Default benchmark ticker for new portfolios (null to clear)",
        examples=["^GSPC"],
    )
    timezone: str | None = Field(
        None,
        max_length=50,
        description="User's timezone (IANA format)",
        examples=["Europe/Rome"],
    )

    @field_validator("default_currency")
    @classmethod
    def validate_currency_uppercase(cls, v: str | None) -> str | None:
        """Ensure currency is uppercase."""
        if v is not None:
            return v.upper()
        return v
