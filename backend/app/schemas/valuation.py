# backend/app/schemas/valuation.py
"""
Pydantic schemas for Portfolio Valuation.

These schemas handle:
- Portfolio valuation (current and historical)
- Holdings breakdown
- P&L calculations
- Valuation history (time series)
"""

import datetime as dt
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# COST BASIS SCHEMAS
# =============================================================================

class CostBasisDetail(BaseModel):
    """Cost basis details for a holding."""

    model_config = ConfigDict(from_attributes=True)

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

    model_config = ConfigDict(from_attributes=True)

    price_per_share: Decimal | None = Field(
        ...,
        description="Current market price per share (None if no data)"
    )
    price_date: dt.date | None = Field(
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

    model_config = ConfigDict(from_attributes=True)

    # Unrealized (open positions)
    unrealized_amount: Decimal | None = Field(
        ...,
        description="Unrealized P&L in portfolio currency (None if value unknown)"
    )
    unrealized_percentage: Decimal | None = Field(
        ...,
        description="Unrealized P&L as percentage of cost basis"
    )

    # Realized (closed positions)
    realized_amount: Decimal = Field(
        ...,
        description="Realized P&L from sales in portfolio currency"
    )
    realized_percentage: Decimal | None = Field(
        ...,
        description="Realized P&L as percentage of cost of sold shares"
    )

    # Total
    total_amount: Decimal | None = Field(
        ...,
        description="Total P&L (unrealized + realized)"
    )
    total_percentage: Decimal | None = Field(
        ...,
        description="Total P&L as percentage of cost basis"
    )


# =============================================================================
# HOLDING VALUATION SCHEMAS
# =============================================================================

class HoldingValuation(BaseModel):
    """Complete valuation for a single holding (position)."""

    model_config = ConfigDict(from_attributes=True)

    # Asset identification
    asset_id: int
    ticker: str
    exchange: str
    asset_name: str | None = None
    asset_class: str = Field(default="OTHER", description="Asset class (STOCK, ETF, BOND, etc.)")
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

    # Synthetic data tracking (all optional for backwards compatibility)
    price_is_synthetic: bool = Field(
        default=False,
        description="True if price was derived from proxy backcasting"
    )
    price_source: str = Field(
        default="market",
        description="Price source: 'market', 'proxy_backcast', or 'unavailable'"
    )
    proxy_ticker: str | None = Field(
        default=None,
        description="Ticker of proxy asset used for synthetic price"
    )
    proxy_exchange: str | None = Field(
        default=None,
        description="Exchange of proxy asset used for synthetic price"
    )


# =============================================================================
# PORTFOLIO VALUATION SCHEMAS
# =============================================================================

class CashBalanceDetail(BaseModel):
    """Cash balance in a specific currency."""

    model_config = ConfigDict(from_attributes=True)

    currency: str = Field(..., description="Currency code (e.g., 'EUR', 'USD')")
    amount: Decimal = Field(..., description="Cash amount in this currency")
    amount_portfolio: Decimal | None = Field(
        ...,
        description="Amount converted to portfolio currency (None if FX unavailable)"
    )
    fx_rate_used: Decimal | None = Field(
        ...,
        description="FX rate used for conversion (None if same as portfolio currency)"
    )


class PortfolioValuationSummary(BaseModel):
    """Summary totals for portfolio valuation."""

    model_config = ConfigDict(from_attributes=True)

    total_cost_basis: Decimal = Field(
        ...,
        description="Total cost basis in portfolio currency"
    )
    total_net_invested: Decimal = Field(
        ...,
        description="Total net invested capital (deposits minus withdrawals)"
    )
    total_value: Decimal | None = Field(
        ...,
        description="Total securities value in portfolio currency (None if incomplete)"
    )
    total_cash: Decimal | None = Field(
        default=None,
        description="Total cash in portfolio currency (None if not tracking or FX incomplete)"
    )
    total_equity: Decimal | None = Field(
        ...,
        description="Total equity (securities + cash) in portfolio currency"
    )
    total_unrealized_pnl: Decimal | None = Field(
        ...,
        description="Total unrealized P&L (None if incomplete)"
    )
    total_realized_pnl: Decimal = Field(
        ...,
        description="Total realized P&L from sales"
    )
    total_pnl: Decimal | None = Field(
        ...,
        description="Total P&L (unrealized + realized, None if incomplete)"
    )
    total_pnl_percentage: Decimal | None = Field(
        ...,
        description="Total P&L as percentage (None if incomplete)"
    )
    day_change: Decimal | None = Field(
        default=None,
        description="Change since previous trading day"
    )
    day_change_percentage: Decimal | None = Field(
        default=None,
        description="% change since previous trading day"
    )


class PortfolioValuationResponse(BaseModel):
    """Complete portfolio valuation response."""

    model_config = ConfigDict(from_attributes=True)

    portfolio_id: int
    portfolio_name: str
    portfolio_currency: str = Field(..., description="Base currency for valuation")
    valuation_date: dt.date = Field(..., description="Date of valuation")

    # Summary
    summary: PortfolioValuationSummary

    # Holdings breakdown
    holdings: list[HoldingValuation] = Field(
        ...,
        description="Individual holding valuations"
    )

    # Cash tracking
    tracks_cash: bool = Field(
        default=False,
        description="True if portfolio has DEPOSIT/WITHDRAWAL transactions"
    )
    cash_balances: list[CashBalanceDetail] = Field(
        default_factory=list,
        description="Cash balances by currency (empty if tracks_cash=False)"
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

    # Synthetic data summary
    has_synthetic_data: bool = Field(
        default=False,
        description="True if any holding uses synthetic (proxy-backcast) prices"
    )
    synthetic_holdings_count: int = Field(
        default=0,
        description="Number of holdings with synthetic prices"
    )


# =============================================================================
# VALUATION HISTORY SCHEMAS
# =============================================================================

class ValuationHistoryPoint(BaseModel):
    """A single point in valuation history."""

    model_config = ConfigDict(from_attributes=True)

    date: dt.date
    value: Decimal | None = Field(
        ...,
        description="Portfolio securities value (None if incomplete data)"
    )
    cash: Decimal | None = Field(
        default=None,
        description="Total cash in portfolio currency (None if not tracking)"
    )
    equity: Decimal | None = Field(
        ...,
        description="Total equity (value + cash, None if incomplete)"
    )
    cost_basis: Decimal
    net_invested: Decimal = Field(
        ...,
        description="Cumulative net invested as of this date"
    )
    unrealized_pnl: Decimal | None = Field(
        ...,
        description="Unrealized P&L (None if value unknown)"
    )
    realized_pnl: Decimal = Field(
        ...,
        description="Realized P&L from sales up to this date"
    )
    total_pnl: Decimal | None = Field(
        ...,
        description="Total P&L (unrealized + realized, None if incomplete)"
    )
    pnl_percentage: Decimal | None = Field(
        ...,
        description="Total P&L as percentage of net invested (None during gap periods)"
    )
    has_complete_data: bool
    is_gap_period: bool = Field(
        default=False,
        description="True if this date is in a gap period (no holdings, zero equity)"
    )

    # Synthetic data tracking
    has_synthetic_data: bool = Field(
        default=False,
        description="True if any holding on this date uses synthetic prices"
    )
    synthetic_holdings: list[str] = Field(
        default_factory=list,
        description="Tickers of holdings with synthetic prices on this date"
    )

    # TWR-based drawdown
    drawdown: Decimal | None = Field(
        default=None,
        description="TWR-based drawdown as decimal (e.g., -0.0385 for -3.85%)"
    )


class PortfolioHistoryResponse(BaseModel):
    """Portfolio valuation history (time series)."""

    model_config = ConfigDict(from_attributes=True)

    portfolio_id: int
    portfolio_currency: str
    from_date: dt.date
    to_date: dt.date
    interval: str = Field(
        ...,
        description="Data interval: daily, weekly, monthly"
    )

    # Cash tracking
    tracks_cash: bool = Field(
        default=False,
        description="True if portfolio tracks cash (has DEPOSIT/WITHDRAWAL)"
    )

    # Time series data
    data: list[ValuationHistoryPoint]
    total_points: int

    # Data quality
    warnings: list[str] = Field(
        default_factory=list,
        description="Warnings about data gaps or missing prices"
    )

    # Synthetic data summary
    has_synthetic_data: bool = Field(
        default=False,
        description="True if any data points include synthetic prices"
    )
    synthetic_holdings: dict[str, str | None] = Field(
        default_factory=dict,
        description="Holdings with synthetic data: {ticker: proxy_ticker_used}"
    )
    synthetic_date_range: tuple[date, date] | None = Field(
        default=None,
        description="Date range where synthetic data was used"
    )
    synthetic_data_percentage: Decimal = Field(
        default=Decimal("0"),
        description="Percentage of price lookups that used synthetic data"
    )


# =============================================================================
# REQUEST SCHEMAS
# =============================================================================

class ValuationRequest(BaseModel):
    """Request parameters for valuation endpoint."""

    date: dt.date | None = Field(
        default=None,
        description="Valuation date (default: today)"
    )


class ValuationHistoryRequest(BaseModel):
    """Request parameters for valuation history endpoint."""

    from_date: dt.date = Field(..., description="Start date for history")
    to_date: dt.date = Field(..., description="End date for history")
    interval: str = Field(
        default="daily",
        pattern=r"^(daily|weekly|monthly)$",
        description="Data interval: daily, weekly, monthly"
    )
