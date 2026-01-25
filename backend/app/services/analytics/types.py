# backend/app/services/analytics/types.py
"""
Data types for the Analytics Service.

This module defines the data structures used throughout the analytics
calculations. All types use Decimal for financial precision.

Architecture:
    - CashFlow: Represents money in/out of portfolio
    - PerformanceMetrics: Return calculations (TWR, IRR, CAGR)
    - RiskMetrics: Risk measurements (Volatility, Sharpe, Drawdown)
    - BenchmarkMetrics: Comparison with market index (Beta, Alpha)
    - DrawdownPeriod: Details of a single drawdown event
    - AnalyticsResult: Combined result from all calculators
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


class AnalysisScope(str, Enum):
    """
    Scope for analytics calculations.

    Attributes:
        CURRENT_PERIOD: Calculate metrics for active investment period only (GIPS-compliant)
        FULL_HISTORY: Chain all periods together, skip zero-equity days
    """
    CURRENT_PERIOD = "current_period"
    FULL_HISTORY = "full_history"


# =============================================================================
# INPUT TYPES
# =============================================================================

@dataclass
class CashFlow:
    """
    Represents a cash flow event for IRR/XIRR calculations.

    Attributes:
        date: When the cash flow occurred
        amount: Positive = deposit/inflow, Negative = withdrawal/outflow

    Note:
        For XIRR, the final portfolio value is treated as a negative cash flow
        (money "leaving" the investment back to the investor).
    """
    date: date
    amount: Decimal


@dataclass
class DailyValue:
    """
    A single day's portfolio value for time series calculations.

    Attributes:
        date: The valuation date
        value: Total portfolio value (equity + cash if tracked)
        cash_flow: Any deposit/withdrawal on this day (default 0)
    """
    date: date
    value: Decimal
    cash_flow: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class InvestmentPeriod:
    """
    A continuous period where the portfolio had holdings.

    GIPS defines a measurement period as ending when:
    - Full liquidation occurs (equity → 0)
    - Significant cash flow (>10% of portfolio) - optional
    - Client-defined period end

    Attributes:
        period_number: Sequential identifier (1, 2, 3, ...)
        start_date: First day with holdings
        end_date: Last day with holdings (or current if active)
        start_value: Portfolio value at period start
        end_value: Portfolio value at period end
        end_reason: Why the period ended
        is_active: True if this is the current active period
        trading_days: Number of trading days with data
    """
    period_number: int
    start_date: date
    end_date: date
    start_value: Decimal
    end_value: Decimal
    end_reason: str  # "full_liquidation", "active", "data_gap"
    is_active: bool = False
    trading_days: int = 0


@dataclass
class MeasurementPeriodInfo:
    """
    Information about the measurement period used for metrics calculation.

    Attributes:
        start_date: Start of the measurement period
        end_date: End of the measurement period
        trading_days: Number of trading days in the period
        period_number: Which investment period this corresponds to
    """
    start_date: date
    end_date: date
    trading_days: int
    period_number: int


# =============================================================================
# PERFORMANCE METRICS
# =============================================================================

@dataclass
class PerformanceMetrics:
    """
    Return-based performance metrics.

    All percentages are expressed as decimals (0.15 = 15%).

    Attributes:
        roi: Return on Investment (total_gain / invested_capital)
        roi_annualized: ROI scaled to 1 year
        twr: Time-Weighted Return (removes cash flow bias)
        twr_annualized: TWR scaled to 1 year
        mwr: Money-Weighted Return (same as IRR)
        irr: Internal Rate of Return (periodic)
        xirr: Extended IRR (exact dates)

        total_gain: Absolute gain in portfolio currency
        start_value: Portfolio value at period start
        end_value: Portfolio value at period end
        total_deposits: Sum of all deposits
        total_withdrawals: Sum of all withdrawals (positive number)

        trading_days: Number of trading days in period
        calendar_days: Number of calendar days in period
    """
    # Return metrics (as decimals, e.g., 0.15 = 15%)
    roi: Decimal | None = None
    roi_annualized: Decimal | None = None
    twr: Decimal | None = None
    twr_annualized: Decimal | None = None
    mwr: Decimal | None = None  # Same as IRR
    irr: Decimal | None = None
    xirr: Decimal | None = None

    # Absolute values
    total_gain: Decimal | None = None
    start_value: Decimal | None = None
    end_value: Decimal | None = None
    cost_basis: Decimal | None = None  # Total invested in current positions
    total_realized_pnl: Decimal | None = None
    total_deposits: Decimal = field(default_factory=lambda: Decimal("0"))
    total_withdrawals: Decimal = field(default_factory=lambda: Decimal("0"))
    net_invested: Decimal | None = None  # Actual capital invested (= cost_basis for portfolios without cash tracking)

    # Period info
    trading_days: int = 0
    calendar_days: int = 0

    # Data quality
    has_sufficient_data: bool = True
    warnings: list[str] = field(default_factory=list)


# =============================================================================
# RISK METRICS
# =============================================================================

@dataclass
class DrawdownPeriod:
    """
    Details of a single drawdown event.

    A drawdown is the decline from a peak to a trough before a new peak is reached.

    Attributes:
        start_date: When the drawdown began (peak date)
        trough_date: When the lowest point was reached
        end_date: When the drawdown ended (recovery date), None if ongoing
        depth: Maximum percentage decline (negative number, e.g., -0.15 = -15%)
        duration_days: Days from start to end (or to current if ongoing)
        recovery_days: Days from trough to recovery (None if ongoing)
    """
    start_date: date
    trough_date: date
    end_date: date | None  # None if not yet recovered
    depth: Decimal  # Negative percentage, e.g., -0.15 = -15%
    duration_days: int
    recovery_days: int | None = None


@dataclass
class RiskMetrics:
    """
    Risk and volatility metrics.

    All percentages are expressed as decimals.

    Attributes:
        volatility_daily: Daily standard deviation of returns
        volatility_annualized: Annualized volatility (daily * sqrt(252))
        downside_deviation: Std dev of negative returns only

        sharpe_ratio: (Return - RiskFree) / Volatility
        sortino_ratio: (Return - RiskFree) / Downside Deviation
        calmar_ratio: CAGR / |Max Drawdown|

        max_drawdown: Largest peak-to-trough decline (negative decimal)
        max_drawdown_start: When the worst drawdown began
        max_drawdown_end: When the worst drawdown ended (None if ongoing)
        current_drawdown: Current drawdown from most recent peak

        var_95: Value at Risk at 95% confidence (daily)
        cvar_95: Conditional VaR (Expected Shortfall) at 95%

        positive_days: Number of days with positive returns
        negative_days: Number of days with negative returns
        win_rate: positive_days / total_days

        best_day: Highest single-day return
        worst_day: Lowest single-day return

        drawdown_periods: List of all significant drawdowns
    """
    # Volatility metrics
    volatility_daily: Decimal | None = None
    volatility_annualized: Decimal | None = None
    downside_deviation: Decimal | None = None

    # Risk-adjusted returns
    sharpe_ratio: Decimal | None = None
    sortino_ratio: Decimal | None = None
    calmar_ratio: Decimal | None = None

    # Drawdown metrics
    max_drawdown: Decimal | None = None  # Negative decimal
    max_drawdown_start: date | None = None
    max_drawdown_end: date | None = None
    current_drawdown: Decimal | None = None

    # Value at Risk
    var_95: Decimal | None = None
    cvar_95: Decimal | None = None

    # Win/Loss statistics
    positive_days: int = 0
    negative_days: int = 0
    win_rate: Decimal | None = None
    best_day: Decimal | None = None
    best_day_date: date | None = None
    worst_day: Decimal | None = None
    worst_day_date: date | None = None

    # Detailed drawdown history
    drawdown_periods: list[DrawdownPeriod] = field(default_factory=list)

    measurement_period: MeasurementPeriodInfo | None = None
    investment_periods: list[InvestmentPeriod] = field(default_factory=list)
    total_periods: int = 0
    scope: str = "current_period"  # "current_period" or "full_history"

    # Data quality
    has_sufficient_data: bool = True
    warnings: list[str] = field(default_factory=list)


# =============================================================================
# BENCHMARK METRICS
# =============================================================================

@dataclass
class BenchmarkMetrics:
    """
    Comparison metrics against a benchmark index.

    Attributes:
        benchmark_symbol: The benchmark ticker (e.g., "SPY")
        benchmark_name: Full name of the benchmark

        portfolio_return: Portfolio return over the period
        benchmark_return: Benchmark return over the period
        excess_return: Portfolio return - Benchmark return

        beta: Systematic risk (Cov(Rp,Rm) / Var(Rm))
              β > 1: More volatile than market
              β < 1: Less volatile than market
              β = 1: Moves with market

        alpha: Excess return above expected (Jensen's Alpha)
               α = Rp - [Rf + β(Rm - Rf)]

        correlation: Pearson correlation coefficient (-1 to 1)
        r_squared: Coefficient of determination (0 to 1)

        tracking_error: Std dev of return differences
        information_ratio: Excess return / Tracking error

        up_capture: Performance in up markets vs benchmark
        down_capture: Performance in down markets vs benchmark
    """
    # Benchmark identification
    benchmark_symbol: str
    benchmark_name: str | None = None

    # Returns comparison
    portfolio_return: Decimal | None = None
    benchmark_return: Decimal | None = None
    excess_return: Decimal | None = None

    # CAPM metrics
    beta: Decimal | None = None
    alpha: Decimal | None = None

    # Correlation metrics
    correlation: Decimal | None = None
    r_squared: Decimal | None = None

    # Tracking metrics
    tracking_error: Decimal | None = None
    information_ratio: Decimal | None = None

    # Capture ratios
    up_capture: Decimal | None = None
    down_capture: Decimal | None = None

    # Data quality
    has_sufficient_data: bool = True
    warnings: list[str] = field(default_factory=list)


# =============================================================================
# COMBINED RESULT
# =============================================================================

@dataclass
class AnalyticsPeriod:
    """
    Time period for analytics calculations.
    """
    from_date: date
    to_date: date
    trading_days: int
    calendar_days: int


@dataclass
class AnalyticsResult:
    """
    Combined result from all analytics calculations.

    This is the main response type returned by AnalyticsService.
    """
    portfolio_id: int
    portfolio_currency: str
    period: AnalyticsPeriod

    performance: PerformanceMetrics
    risk: RiskMetrics
    benchmark: BenchmarkMetrics | None = None  # None if no benchmark requested

    # Overall data quality
    has_complete_data: bool = True
    warnings: list[str] = field(default_factory=list)

    # Data quality from valuation (transparency)
    has_synthetic_data: bool = False
    synthetic_data_percentage: Decimal | None = None
    synthetic_holdings: dict[str, str | None] = field(default_factory=dict)  # {ticker: proxy_ticker}
    synthetic_date_range: tuple[date, date] | None = None
    synthetic_details: dict[str, dict] = field(default_factory=dict)  # Per-asset details
    reliability_notes: list[str] = field(default_factory=list)
