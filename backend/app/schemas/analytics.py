# backend/app/schemas/analytics.py
"""
Pydantic schemas for Analytics API.

These schemas define the request/response formats for portfolio analytics:
- Performance metrics (TWR, XIRR, CAGR, simple return)
- Risk metrics (Volatility, Sharpe, Sortino, Drawdown, VaR)
- Benchmark comparison (Beta, Alpha, Correlation, Tracking Error)

Design decisions:
- All numeric values are serialized as STRINGS to preserve Decimal precision
- Return values are in decimal form (0.155 = 15.5%), frontend formats for display
- Null is returned when a metric cannot be calculated (insufficient data)
- Drawdown periods limited to top 5 most significant
- All responses include a wrapper with portfolio context and period info
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# PERIOD INFO
# =============================================================================

class PeriodInfo(BaseModel):
    """Time period information for analytics calculations."""

    model_config = ConfigDict(from_attributes=True)

    from_date: date = Field(..., description="Start date of analysis period")
    to_date: date = Field(..., description="End date of analysis period")
    trading_days: int = Field(..., description="Number of trading days with data")
    calendar_days: int = Field(..., description="Number of calendar days in period")


# =============================================================================
# PERFORMANCE SCHEMAS
# =============================================================================

class PerformanceMetricsResponse(BaseModel):
    """
    Performance metrics response.

    All return values are decimals (0.155 = 15.5%).
    All numeric values are strings to preserve precision.
    """

    model_config = ConfigDict(from_attributes=True)

    # Return metrics (as decimal strings, e.g., "0.1550" = 15.5%)
    simple_return: str | None = Field(
        None,
        description="Cash-flow adjusted return: total_gain / start_value"
    )
    simple_return_annualized: str | None = Field(
        None,
        description="Simple return annualized to 1 year"
    )
    total_realized_pnl: str | None = Field(
        None,
        description="Total realized P&L from closed positions"
    )
    twr: str | None = Field(
        None,
        description="Time-Weighted Return (removes cash flow timing bias)"
    )
    twr_annualized: str | None = Field(
        None,
        description="TWR annualized to 1 year"
    )
    cagr: str | None = Field(
        None,
        description="Compound Annual Growth Rate"
    )
    xirr: str | None = Field(
        None,
        description="Extended Internal Rate of Return (money-weighted)"
    )

    # Absolute values (as decimal strings in portfolio currency)
    total_gain: str | None = Field(
        None,
        description="Absolute gain in portfolio currency (end - start - net_cash_flows)"
    )
    start_value: str | None = Field(
        None,
        description="Portfolio value at start of period"
    )
    end_value: str | None = Field(
        None,
        description="Portfolio value at end of period"
    )
    cost_basis: str | None = Field(
        None,
        description="Total cost basis of current positions (from valuation)"
    )
    total_deposits: str = Field(
        "0",
        description="Sum of all deposits during period"
    )
    total_withdrawals: str = Field(
        "0",
        description="Sum of all withdrawals during period (positive number)"
    )
    net_invested: str | None = Field(
        None,
        description="Actual capital invested by user (equals cost_basis). "
                    "Use this instead of total_deposits to see real money invested. "
                    "total_deposits may be inflated by broker swaps/restructures."
    )

    # Data quality
    has_sufficient_data: bool = Field(
        True,
        description="False if insufficient data for calculations"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Warnings about data quality or calculation limitations"
    )


class PerformanceResponse(BaseModel):
    """Wrapped performance response with context."""

    model_config = ConfigDict(from_attributes=True)

    portfolio_id: int
    portfolio_currency: str
    period: PeriodInfo
    performance: PerformanceMetricsResponse


# =============================================================================
# RISK SCHEMAS
# =============================================================================

class DrawdownPeriodResponse(BaseModel):
    """Details of a single drawdown event."""

    model_config = ConfigDict(from_attributes=True)

    start_date: date = Field(..., description="When the drawdown began (peak date)")
    trough_date: date = Field(..., description="When the lowest point was reached")
    end_date: date | None = Field(
        None,
        description="When the drawdown ended (recovery date), null if ongoing"
    )
    depth: str = Field(
        ...,
        description="Maximum decline as decimal (e.g., '-0.15' = -15%)"
    )
    duration_days: int = Field(..., description="Days from start to end (or current)")
    recovery_days: int | None = Field(
        None,
        description="Days from trough to recovery (null if ongoing)"
    )


class InvestmentPeriodResponse(BaseModel):
    """Details of an investment period (GIPS compliance)."""

    model_config = ConfigDict(from_attributes=True)

    period_index: int = Field(..., description="Period number (1-indexed)")
    start_date: date = Field(..., description="Start of investment period")
    end_date: date | None = Field(None, description="End of period (null if current)")
    is_active: bool = Field(..., description="True if this is the current active period")

    # Contribution tracking
    contribution_date: date | None = Field(None, description="Date of contribution")
    contribution_value: str | None = Field(None, description="Value contributed")

    # Period values
    start_value: str | None = Field(None, description="Value at period start")
    end_value: str | None = Field(None, description="Value at period end")
    trading_days: int = Field(0, description="Trading days in this period")


class MeasurementPeriodResponse(BaseModel):
    """Measurement period info for risk calculations (GIPS compliance)."""

    model_config = ConfigDict(from_attributes=True)

    period_type: str = Field(..., description="Type: 'active', 'historical', or 'full'")
    start_date: date = Field(..., description="Measurement start date")
    end_date: date = Field(..., description="Measurement end date")
    trading_days: int = Field(0, description="Number of trading days")
    description: str | None = Field(None, description="Human-readable description")


class RiskMetricsResponse(BaseModel):
    """
    Risk metrics response.

    All percentages are decimals (0.155 = 15.5%).
    All numeric values are strings to preserve precision.
    """

    model_config = ConfigDict(from_attributes=True)

    # Volatility metrics
    volatility_daily: str | None = Field(
        None,
        description="Daily standard deviation of returns"
    )
    volatility_annualized: str | None = Field(
        None,
        description="Annualized volatility (daily * sqrt(252))"
    )
    downside_deviation: str | None = Field(
        None,
        description="Standard deviation of negative returns only"
    )

    # Risk-adjusted returns
    sharpe_ratio: str | None = Field(
        None,
        description="(Return - RiskFree) / Volatility"
    )
    sortino_ratio: str | None = Field(
        None,
        description="(Return - RiskFree) / Downside Deviation"
    )
    calmar_ratio: str | None = Field(
        None,
        description="CAGR / |Max Drawdown|"
    )

    # Drawdown metrics
    max_drawdown: str | None = Field(
        None,
        description="Largest peak-to-trough decline (e.g., '-0.25' = -25%)"
    )
    max_drawdown_start: date | None = Field(
        None,
        description="Start date of worst drawdown"
    )
    max_drawdown_end: date | None = Field(
        None,
        description="End date of worst drawdown (null if ongoing)"
    )
    current_drawdown: str | None = Field(
        None,
        description="Current drawdown from most recent peak"
    )

    # Value at Risk
    var_95: str | None = Field(
        None,
        description="Value at Risk at 95% confidence (daily)"
    )
    cvar_95: str | None = Field(
        None,
        description="Conditional VaR / Expected Shortfall at 95%"
    )

    # Win/Loss statistics
    positive_days: int = Field(0, description="Number of days with positive returns")
    negative_days: int = Field(0, description="Number of days with negative returns")
    win_rate: str | None = Field(
        None,
        description="Percentage of positive days (e.g., '0.55' = 55%)"
    )
    best_day: str | None = Field(
        None,
        description="Highest single-day return"
    )
    best_day_date: date | None = Field(None, description="Date of best day")
    worst_day: str | None = Field(
        None,
        description="Lowest single-day return"
    )
    worst_day_date: date | None = Field(None, description="Date of worst day")

    # Top 5 drawdown periods (sorted by depth)
    drawdown_periods: list[DrawdownPeriodResponse] = Field(
        default_factory=list,
        description="Top 5 most significant drawdown periods"
    )

    measurement_period: MeasurementPeriodResponse | None = Field(
        None,
        description="The period used for calculating metrics"
    )
    investment_periods: list[InvestmentPeriodResponse] = Field(
        default_factory=list,
        description="All detected investment periods"
    )
    total_periods: int = Field(
        default=1,
        description="Total number of investment periods detected"
    )
    scope: str = Field(
        default="current_period",
        description="Scope used: 'current_period' or 'full_history'"
    )

    # Data quality
    has_sufficient_data: bool = Field(
        True,
        description="False if insufficient data for calculations"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Warnings about data quality or calculation limitations"
    )


class RiskResponse(BaseModel):
    """Wrapped risk response with context."""

    model_config = ConfigDict(from_attributes=True)

    portfolio_id: int
    portfolio_currency: str
    period: PeriodInfo
    risk: RiskMetricsResponse


# =============================================================================
# BENCHMARK SCHEMAS
# =============================================================================

class BenchmarkMetricsResponse(BaseModel):
    """
    Benchmark comparison metrics response.

    All percentages are decimals (0.155 = 15.5%).
    All numeric values are strings to preserve precision.
    """

    model_config = ConfigDict(from_attributes=True)

    # Benchmark identification
    benchmark_symbol: str = Field(..., description="Benchmark ticker (e.g., '^SPX')")
    benchmark_name: str | None = Field(None, description="Full name of benchmark")

    # Returns comparison
    portfolio_return: str | None = Field(
        None,
        description="Portfolio return over the period"
    )
    benchmark_return: str | None = Field(
        None,
        description="Benchmark return over the period"
    )
    excess_return: str | None = Field(
        None,
        description="Portfolio return minus benchmark return"
    )

    # CAPM metrics
    beta: str | None = Field(
        None,
        description="Systematic risk: Cov(Rp,Rm)/Var(Rm). β>1 more volatile than market"
    )
    alpha: str | None = Field(
        None,
        description="Jensen's Alpha: excess return above expected (Rp - [Rf + β(Rm-Rf)])"
    )

    # Correlation metrics
    correlation: str | None = Field(
        None,
        description="Pearson correlation coefficient (-1 to 1)"
    )
    r_squared: str | None = Field(
        None,
        description="Coefficient of determination (0 to 1)"
    )

    # Tracking metrics
    tracking_error: str | None = Field(
        None,
        description="Standard deviation of return differences"
    )
    information_ratio: str | None = Field(
        None,
        description="Excess return / Tracking error"
    )

    # Capture ratios
    up_capture: str | None = Field(
        None,
        description="Performance in up markets vs benchmark"
    )
    down_capture: str | None = Field(
        None,
        description="Performance in down markets vs benchmark"
    )

    # Data quality
    has_sufficient_data: bool = Field(
        True,
        description="False if insufficient overlapping data"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Warnings about data quality"
    )


class BenchmarkResponse(BaseModel):
    """Wrapped benchmark response with context."""

    model_config = ConfigDict(from_attributes=True)

    portfolio_id: int
    portfolio_currency: str
    period: PeriodInfo
    benchmark: BenchmarkMetricsResponse


# =============================================================================
# COMBINED ANALYTICS RESPONSE
# =============================================================================

class AnalyticsResponse(BaseModel):
    """
    Complete analytics response combining all metrics.

    This is the response for GET /portfolios/{id}/analytics
    """

    model_config = ConfigDict(from_attributes=True)

    portfolio_id: int
    portfolio_currency: str
    period: PeriodInfo

    performance: PerformanceMetricsResponse
    risk: RiskMetricsResponse
    benchmark: BenchmarkMetricsResponse | None = Field(
        None,
        description="Benchmark comparison (null if no benchmark requested)"
    )

    # Overall data quality
    has_complete_data: bool = Field(
        True,
        description="True if all requested metrics have complete data"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Aggregated warnings from all calculations"
    )


# =============================================================================
# REQUEST VALIDATION (Query Parameters)
# =============================================================================

class AnalyticsQueryParams(BaseModel):
    """
    Query parameters for analytics endpoints.

    Note: FastAPI will use Query() for these in the router.
    This model is for documentation and validation reference.
    """

    from_date: date = Field(..., description="Start date of analysis period")
    to_date: date = Field(..., description="End date of analysis period")
    benchmark_symbol: str | None = Field(
        None,
        description="Benchmark ticker (e.g., '^SPX', 'IWDA.AS'). Uses default if not provided."
    )
    risk_free_rate: Decimal = Field(
        default=Decimal("0.02"),
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Annual risk-free rate as decimal (0.02 = 2%)"
    )
