# backend/app/schemas/portfolio_settings.py
"""
Pydantic schemas for Portfolio Settings.

These schemas handle user preferences for a portfolio,
including the proxy backcasting opt-in.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================

class PortfolioSettingsResponse(BaseModel):
    """Schema for portfolio settings response."""

    id: int
    portfolio_id: int
    enable_proxy_backcasting: bool = Field(
        ...,
        description="Whether proxy backcasting is enabled (Beta feature)"
    )
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# UPDATE SCHEMAS
# =============================================================================

class PortfolioSettingsUpdate(BaseModel):
    """
    Schema for updating portfolio settings.

    All fields are optional - only send what you want to change.
    """

    enable_proxy_backcasting: bool | None = Field(
        default=None,
        description="Enable/disable proxy backcasting (Beta feature)"
    )


# =============================================================================
# RESPONSE WITH WARNING (for opt-in confirmation)
# =============================================================================

class PortfolioSettingsUpdateResponse(PortfolioSettingsResponse):
    """
    Response after updating settings.

    Includes a warning message when enabling beta features.
    """

    warning: str | None = Field(
        default=None,
        description="Warning message about enabled features"
    )
