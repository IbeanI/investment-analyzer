# backend/app/schemas/portfolio_settings.py
"""
Pydantic schemas for Portfolio Settings.

These schemas handle user preferences for a portfolio,
including the proxy backcasting opt-in.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# ENUMS
# =============================================================================

class BackcastingMethod(str, Enum):
    """
    Backcasting method preference for portfolio synthetic data.

    - PROXY_PREFERRED: Use proxy backcasting when available, fall back to cost carry
    - COST_CARRY_ONLY: Always use cost carry, never use proxy data
    - DISABLED: No backcasting, leave historical gaps unfilled
    """
    PROXY_PREFERRED = "proxy_preferred"
    COST_CARRY_ONLY = "cost_carry_only"
    DISABLED = "disabled"


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================

class PortfolioSettingsResponse(BaseModel):
    """Schema for portfolio settings response."""

    id: int
    portfolio_id: int
    enable_proxy_backcasting: bool = Field(
        ...,
        description="Whether proxy backcasting is enabled (Beta feature) - DEPRECATED"
    )
    backcasting_method: BackcastingMethod = Field(
        default=BackcastingMethod.PROXY_PREFERRED,
        description="Backcasting method preference: proxy_preferred, cost_carry_only, or disabled"
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
        description="Enable/disable proxy backcasting (Beta feature) - DEPRECATED, use backcasting_method"
    )
    backcasting_method: BackcastingMethod | None = Field(
        default=None,
        description="Backcasting method preference: proxy_preferred, cost_carry_only, or disabled"
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
