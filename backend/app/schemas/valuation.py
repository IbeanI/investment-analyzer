# backend/app/schemas/valuation.py
"""
Pydantic schemas for Portfolio Valuation.

These schemas handle:
- Portfolio valuation (current and historical)
- Holdings breakdown
- P&L calculations
- Valuation history (time series)
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


# =============================================================================
# COST BASIS SCHEMAS
# =============================================================================

class CostBasisDetail(BaseModel):
    """Cost basis details for a holding."""

    local_currency: str = Field(
        ...,
        description="Currency the asset trades in"
    )
    local_amount: Decimal = Field(
        ...,
        description="Total cost in asset's trading currency"
    )
    portfolio_currency: str = Field(
        ...,
        description="Portfolio base currency"
    )
    portfolio_amount: Decimal = Field(
        ...,
        description="Total cost in portfolio currency (using transaction FX rates)"
    )
    avg_cost_per_share: Decimal = Field(
        ...,
        description="Average cost per share in local currency"
    )


# =============================================================================
# CURRENT VALUE SCHEMAS
# =============================================================================

class CurrentValueDetail(BaseModel):
    """Current value details for a holding."""

    price_per_share: Decimal | None = Field(
        ...,
        description="Current market price per share (None if no data)"
    )
    price_date: date | None = Field(
        ...,
        description="Date of the price (None if no data)"
    )
    local_currency: str = Field(
        ...,
        description="Currency the asset trades in"
    )
    local_amount: Decimal | None = Field(
        ...,
        description="Total value in asset's trading currency (None if no price)"
    )
    portfolio_currency: str = Field(
        ...,
        description="Portfolio base currency"
    )
    portfolio_amount: Decimal | None = Field(
        ...,
        description="Total value in portfolio currency (None if no price/FX)"
    )
    fx_rate_used: Decimal | None = Field(
        ...,
        description="FX rate used for conversion (historical rate at price_date)"
    )


# =============================================================================
# P&L SCHEMAS
# =============================================================================

class PnLDetail(BaseModel):
    """Profit and Loss details for a holding."""

    amount: Decimal | None = Field(
        ...,
        description="P&L in portfolio currency (None if value unknown)"
    )
    percentage: Decimal | None = Field(
        ...,
        description="P&L as percentage of cost basis (None if value unknown)"
    )


# =============================================================================
# HOLDING VALUATION SCHEMAS
# =============================================================================

class HoldingValuation(BaseModel):
    """Complete valuation for a single holding (position)."""

    # Asset identification
    asset_id: int
    ticker: str
    exchange: str
    asset_name: str | None = None
    asset_currency: str = Field(..., description="Currency the asset trades in")

    # Position size
    quantity: Decimal = Field(..., description="Number of shares/units held")

    # Valuation components
    cost_basis: CostBasisDetail
    current_value: CurrentValueDetail
    pnl: PnLDetail

    # Data quality
    warnings: list[str] = Field(
        default_factory=list,
        description="Warnings about this holding (e.g., missing data)"
    )
    has_complete_data: bool = Field(
        default=True,
        description="False if price or FX data is missing"
    )


# =============================================================================
# PORTFOLIO VALUATION SCHEMAS
# =============================================================================

class PortfolioValuationSummary(BaseModel):
    """Summary totals for portfolio valuation."""

    total_cost_basis: Decimal = Field(
        ...,
        description="Total cost basis in portfolio currency"
    )
    total_value: Decimal | None = Field(
        ...,
        description="Total current value in portfolio currency (None if incomplete)"
    )
    total_pnl: Decimal | None = Field(
        ...,
        description="Total P&L in portfolio currency (None if incomplete)"
    )
    total_pnl_percentage: Decimal | None = Field(
        ...,
        description="Total P&L as percentage (None if incomplete)"
    )


class PortfolioValuationResponse(BaseModel):
    """Complete portfolio valuation response."""

    portfolio_id: int
    portfolio_name: str
    portfolio_currency: str = Field(..., description="Base currency for valuation")
    valuation_date: date = Field(..., description="Date of valuation")

    # Summary
    summary: PortfolioValuationSummary

    # Holdings breakdown
    holdings: list[HoldingValuation] = Field(
        ...,
        description="Individual holding valuations"
    )

    # Data quality
    has_complete_data: bool = Field(
        ...,
        description="True if all holdings have complete price/FX data"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Portfolio-level warnings"
    )


# =============================================================================
# VALUATION HISTORY SCHEMAS
# =============================================================================

class ValuationHistoryPoint(BaseModel):
    """A single point in valuation history."""

    date: date
    value: Decimal | None = Field(
        ...,
        description="Portfolio value (None if incomplete data)"
    )
    cost_basis: Decimal
    pnl: Decimal | None
    pnl_percentage: Decimal | None
    has_complete_data: bool


class PortfolioHistoryResponse(BaseModel):
    """Portfolio valuation history (time series)."""

    portfolio_id: int
    portfolio_currency: str
    from_date: date
    to_date: date
    interval: str = Field(
        ...,
        description="Data interval: daily, weekly, monthly"
    )

    # Time series data
    data: list[ValuationHistoryPoint]
    total_points: int

    # Data quality
    warnings: list[str] = Field(
        default_factory=list,
        description="Warnings about data gaps or missing prices"
    )


# =============================================================================
# REQUEST SCHEMAS
# =============================================================================

class ValuationRequest(BaseModel):
    """Request parameters for valuation endpoint."""

    date: date | None = Field(
        default=None,
        description="Valuation date (default: today)"
    )


class ValuationHistoryRequest(BaseModel):
    """Request parameters for valuation history endpoint."""

    from_date: date = Field(..., description="Start date for history")
    to_date: date = Field(..., description="End date for history")
    interval: str = Field(
        default="daily",
        pattern=r"^(daily|weekly|monthly)$",
        description="Data interval: daily, weekly, monthly"
    )
