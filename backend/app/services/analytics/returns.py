# backend/app/services/analytics/returns.py
"""
Return calculation functions for the Analytics Service.

This module contains pure functions for calculating various return metrics:
- Simple Return: Basic (End - Start) / Start
- Time-Weighted Return (TWR): Removes cash flow bias (Daily Linking Method)
- Compound Annual Growth Rate (CAGR): Annualized growth
- Internal Rate of Return (IRR): Money-weighted return
- Extended IRR (XIRR): IRR with exact dates (Newton-Raphson solver)

All functions are stateless. No external dependencies (scipy, numpy) - pure Python only.

Formulas:
    Simple Return = (End - Start) / Start

    TWR (Daily Linking Method):
        r_daily = (V_end - CF) / V_start - 1
        TWR = ∏(1 + r_daily) - 1

    CAGR = (End / Start)^(365/days) - 1

    XIRR solves: Σ CF_i / (1 + r)^((d_i - d_0) / 365) = 0

Precision Note (Decimal vs Float):
    This module uses Decimal for most arithmetic to maintain precision in financial
    calculations. However, certain operations require float conversion:

    1. Exponentiation (CAGR, annualization): Python's Decimal doesn't support
       non-integer exponents. We convert to float for x^y operations.
       Precision impact: ~15 significant digits retained, negligible for returns.

    2. XIRR Newton-Raphson solver: The iterative solver operates entirely in float
       for performance (100+ iterations with exponentials). Final result is
       converted back to Decimal with 8 decimal places.
       Precision impact: XIRR accurate to 0.00000001 (0.000001%), sufficient for
       any practical investment return calculation.

    This trade-off is industry-standard. Financial libraries (numpy-financial,
    scipy) use float64 for IRR calculations. Our approach provides equivalent
    precision while avoiding external dependencies.
"""

import logging
from datetime import date
import decimal
from decimal import Decimal, ROUND_HALF_UP

from app.services.analytics.types import CashFlow, DailyValue, PerformanceMetrics
from app.services.constants import (
    TRADING_DAYS_PER_YEAR,
    CALENDAR_DAYS_PER_YEAR,
    IRR_MAX_ITERATIONS,
    IRR_TOLERANCE,
    IRR_INITIAL_GUESS,
    ZERO,
)

logger = logging.getLogger(__name__)


# =============================================================================
# SIMPLE RETURN
# =============================================================================

def calculate_simple_return(
        start_value: Decimal,
        end_value: Decimal,
) -> Decimal | None:
    """
    Calculate simple return (holding period return) - NO cash flow adjustment.

    Formula: (End - Start) / Start

    WARNING: This function does NOT adjust for cash flows. Use only when:
    - There are no deposits/withdrawals during the period, OR
    - You want the raw value change (e.g., for benchmarks)

    For portfolios with cash flows, use the adjusted formula:
        simple_return = total_gain / start_value
        where total_gain = end_value - start_value - net_cash_flows

    Args:
        start_value: Portfolio value at start of period
        end_value: Portfolio value at end of period

    Returns:
        Return as decimal (e.g., 0.15 = 15%), or None if start_value is 0
    """
    if start_value == ZERO:
        return None

    return (end_value - start_value) / start_value


def calculate_series_returns(values: list[Decimal]) -> list[Decimal]:
    """
    Calculate period-over-period returns from a series of values.

    This is a utility function for computing simple returns between consecutive
    values in a time series. Used for benchmark comparisons and correlation
    calculations.

    Formula: r_i = (V_i - V_{i-1}) / V_{i-1}

    Args:
        values: List of values (e.g., daily prices or portfolio values)

    Returns:
        List of returns (one fewer than input values)

    Example:
        >>> values = [Decimal("100"), Decimal("105"), Decimal("103")]
        >>> calculate_series_returns(values)
        [Decimal("0.05"), Decimal("-0.019047619047619")]
    """
    if len(values) < 2:
        return []

    returns = []
    for i in range(1, len(values)):
        if values[i - 1] != ZERO:
            ret = (values[i] - values[i - 1]) / values[i - 1]
            returns.append(ret)

    return returns


def annualize_return(
        total_return: Decimal,
        days: int,
        use_trading_days: bool = False,
) -> Decimal | None:
    """
    Annualize a return over a given number of days.

    Formula: (1 + r)^(365/days) - 1

    Uses Python's Decimal.__pow__() which supports non-integer exponents,
    maintaining full precision without float conversion.

    Args:
        total_return: Total return as decimal (e.g., 0.15 = 15%)
        days: Number of days in the period
        use_trading_days: If True, use 252 days/year instead of 365

    Returns:
        Annualized return as decimal, or None if days <= 0
    """
    if days <= 0:
        return None

    days_per_year = TRADING_DAYS_PER_YEAR if use_trading_days else CALENDAR_DAYS_PER_YEAR

    # Handle negative returns
    base = Decimal("1") + total_return
    if base <= 0:
        return Decimal("-1")  # Total loss

    # (1 + r)^(365/days) - 1
    exponent = Decimal(str(days_per_year)) / Decimal(str(days))

    # Use Decimal power operation for full precision.
    # Decimal.__pow__() supports non-integer exponents.
    try:
        annualized = base ** exponent - Decimal("1")
    except decimal.InvalidOperation:
        # Fallback to float for edge cases (extremely large/small values)
        annualized = Decimal(str(float(base) ** float(exponent))) - Decimal("1")

    return annualized


# =============================================================================
# TIME-WEIGHTED RETURN (TWR)
# =============================================================================

def calculate_twr(daily_values: list[DailyValue]) -> Decimal | None:
    """
    Calculate Time-Weighted Return using the Daily Linking Method.

    TWR removes the impact of cash flows, showing pure investment performance.
    This is the industry standard for comparing fund managers (GIPS-compliant).

    Formula (Daily Linking Method):
        r_daily = (V_end - CF) / V_start - 1
        TWR = ∏(1 + r_daily) - 1

    Where:
        V_end = Portfolio value at end of day
        V_start = Portfolio value at start of day (previous day's end value)
        CF = Cash flow on that day (positive = deposit, negative = withdrawal)

    Gap Period Handling (GIPS-compliant):
        When a portfolio has gap periods (full liquidation then reinvestment),
        we identify each investment period separately and chain-link their returns.
        This prevents incorrect daily returns when transitioning across gaps.

        Example: Period 1 (10% return) -> Gap -> Period 2 (5% return)
        TWR = (1.10)(1.05) - 1 = 15.5%

    Args:
        daily_values: List of DailyValue with date, value, and cash_flow

    Returns:
        TWR as decimal (e.g., 0.15 = 15%), or None if insufficient data
    """
    if len(daily_values) < 2:
        return None

    # Sort by date
    sorted_values = sorted(daily_values, key=lambda x: x.date)

    # Identify investment periods (contiguous runs of positive equity)
    # A gap period is when value <= 0 (full liquidation)
    periods: list[list[DailyValue]] = []
    current_period: list[DailyValue] = []

    for dv in sorted_values:
        if dv.value > 0:
            current_period.append(dv)
        else:
            # End of an investment period - save it if it has enough data
            if len(current_period) >= 2:
                periods.append(current_period)
            current_period = []

    # Don't forget the last period if it's still active
    if len(current_period) >= 2:
        periods.append(current_period)

    if not periods:
        return None

    # Calculate TWR for each period and chain-link them together
    cumulative = Decimal("1")
    total_periods_used = 0

    for period in periods:
        period_twr = _calculate_period_twr(period)
        if period_twr is not None:
            cumulative *= (Decimal("1") + period_twr)
            total_periods_used += 1

    if total_periods_used == 0:
        return None

    if len(periods) > 1:
        logger.debug(
            f"TWR: Chain-linked {len(periods)} investment periods "
            f"(gap periods detected)"
        )

    return cumulative - Decimal("1")


def _calculate_period_twr(period_values: list[DailyValue]) -> Decimal | None:
    """
    Calculate TWR for a single contiguous investment period.

    This is the inner calculation for a period with no gaps.
    All values in period_values should be > 0.

    Args:
        period_values: List of DailyValue for a contiguous investment period

    Returns:
        TWR for this period as decimal, or None if insufficient data
    """
    if len(period_values) < 2:
        return None

    cumulative = Decimal("1")

    for i in range(1, len(period_values)):
        prev_value = period_values[i - 1].value
        curr_value = period_values[i].value
        cash_flow = period_values[i].cash_flow

        # Safety check (should not happen as we filtered for value > 0)
        if prev_value <= 0:
            continue

        # Daily Linking Method: r = (V_end - CF) / V_start - 1
        # This removes the cash flow from today's value before calculating return
        r_daily = (curr_value - cash_flow) / prev_value - Decimal("1")

        cumulative *= (Decimal("1") + r_daily)

    return cumulative - Decimal("1")


def calculate_twr_from_sub_periods(
        sub_period_returns: list[Decimal],
) -> Decimal:
    """
    Calculate TWR from pre-calculated sub-period returns.

    Formula: TWR = ∏(1 + r_i) - 1

    Args:
        sub_period_returns: List of returns for each sub-period

    Returns:
        TWR as decimal
    """
    cumulative = Decimal("1")

    for r in sub_period_returns:
        cumulative *= (Decimal("1") + r)

    return cumulative - Decimal("1")


# =============================================================================
# COMPOUND ANNUAL GROWTH RATE (CAGR)
# =============================================================================

def calculate_cagr(
        start_value: Decimal,
        end_value: Decimal,
        days: int,
) -> Decimal | None:
    """
    Calculate Compound Annual Growth Rate (traditional formula).

    Formula: CAGR = (End / Start)^(365/days) - 1

    Uses Python's Decimal.__pow__() which supports non-integer exponents,
    maintaining full precision without float conversion.

    WARNING: This function does NOT adjust for cash flows.
    For portfolios with deposits/withdrawals, use:
        cagr = annualize_return(simple_return, days)
    where simple_return = total_gain / start_value

    This function is useful for:
    - Benchmarks (no cash flows)
    - Quick comparison of raw value changes

    Args:
        start_value: Portfolio value at start
        end_value: Portfolio value at end
        days: Number of calendar days

    Returns:
        CAGR as decimal (e.g., 0.12 = 12%), or None if invalid inputs
    """
    if start_value <= 0 or days <= 0:
        return None

    if end_value <= 0:
        return Decimal("-1")  # Total loss

    ratio = end_value / start_value
    exponent = Decimal(str(CALENDAR_DAYS_PER_YEAR)) / Decimal(str(days))

    # Use Decimal power operation for full precision.
    # Decimal.__pow__() supports non-integer exponents.
    try:
        cagr = ratio ** exponent - Decimal("1")
    except decimal.InvalidOperation:
        # Fallback to float for edge cases (extremely large/small values)
        cagr = Decimal(str(float(ratio) ** float(exponent))) - Decimal("1")

    return cagr


# =============================================================================
# INTERNAL RATE OF RETURN (IRR / XIRR)
# =============================================================================

def calculate_xirr(
        cash_flows: list[CashFlow],
        max_iterations: int = IRR_MAX_ITERATIONS,
        tolerance: Decimal = IRR_TOLERANCE,
) -> Decimal | None:
    """
    Calculate Extended Internal Rate of Return (XIRR).

    XIRR is the money-weighted return that accounts for the timing
    and size of cash flows. It's the discount rate that makes the
    NPV of all cash flows equal to zero.

    Formula:
        Solve for r: Σ CF_i / (1 + r)^((d_i - d_0) / 365) = 0

    Uses Newton-Raphson method for iterative solving.

    Args:
        cash_flows: List of CashFlow (date, amount)
                   - Positive = money into investment (deposit)
                   - Negative = money out of investment (withdrawal, final value)
        max_iterations: Maximum solver iterations
        tolerance: Convergence tolerance

    Returns:
        XIRR as decimal (e.g., 0.15 = 15%), or None if no solution found

    Note:
        The Newton-Raphson solver operates in float for performance (exponentials
        in each iteration). Final result is converted to Decimal with 8 decimal
        places (0.00000001 precision). This matches industry-standard IRR solvers.

    Example:
        cash_flows = [
            CashFlow(date(2024, 1, 1), Decimal("10000")),   # Initial investment
            CashFlow(date(2024, 6, 1), Decimal("5000")),    # Additional deposit
            CashFlow(date(2024, 12, 31), Decimal("-16500")) # Final value (negative)
        ]
        xirr = calculate_xirr(cash_flows)  # Returns ~0.10 (10% return)
    """
    if len(cash_flows) < 2:
        return None

    # Sort by date
    sorted_flows = sorted(cash_flows, key=lambda x: x.date)
    base_date = sorted_flows[0].date

    # Convert to (days, amount) tuples for calculation
    flows = [
        (
            (cf.date - base_date).days,
            float(cf.amount),
        )
        for cf in sorted_flows
    ]

    # Check if we have both positive and negative cash flows
    has_positive = any(f[1] > 0 for f in flows)
    has_negative = any(f[1] < 0 for f in flows)

    if not (has_positive and has_negative):
        logger.warning("XIRR requires both positive and negative cash flows")
        return None

    # Newton-Raphson iterative solver (operates in float for performance).
    # Float64 provides ~15 significant digits, more than sufficient for IRR.
    # Result is converted back to Decimal at convergence.
    rate = float(IRR_INITIAL_GUESS)

    for iteration in range(max_iterations):
        # Calculate NPV and its derivative at current rate
        npv = 0.0
        npv_derivative = 0.0

        for days, amount in flows:
            years = days / 365.0

            if rate <= -1:
                # Avoid division by zero or negative base
                rate = -0.99

            discount = (1 + rate) ** years

            if discount == 0:
                continue

            npv += amount / discount

            # Derivative: d/dr [CF / (1+r)^t] = -t * CF / (1+r)^(t+1)
            if years > 0:
                npv_derivative -= years * amount / ((1 + rate) ** (years + 1))

        # Check convergence
        if abs(npv) < float(tolerance):
            return Decimal(str(rate)).quantize(
                Decimal("0.00000001"), rounding=ROUND_HALF_UP
            )

        # Newton-Raphson step
        if npv_derivative == 0:
            # Derivative is zero, can't continue
            break

        rate = rate - npv / npv_derivative

        # Bound the rate to reasonable values
        if rate < -0.99:
            rate = -0.99
        elif rate > 10:  # 1000% return
            rate = 10

    logger.warning(f"XIRR did not converge after {max_iterations} iterations")
    return None


def calculate_irr_periodic(
        cash_flows: list[Decimal],
) -> Decimal | None:
    """
    Calculate IRR for periodic (equal interval) cash flows.

    This is simpler than XIRR as it assumes equal time periods.

    Formula:
        Solve for r: Σ CF_i / (1 + r)^i = 0

    Args:
        cash_flows: List of cash flows at equal intervals
                   First value is typically negative (initial investment)
                   Last value includes final portfolio value (negative)

    Returns:
        IRR as decimal, or None if no solution found
    """
    if len(cash_flows) < 2:
        return None

    # Convert to XIRR format with synthetic dates (1 year apart)
    xirr_flows = [
        CashFlow(date=date(2000 + i, 1, 1), amount=cf)
        for i, cf in enumerate(cash_flows)
    ]

    return calculate_xirr(xirr_flows)


# =============================================================================
# COMBINED PERFORMANCE CALCULATOR
# =============================================================================

class ReturnsCalculator:
    """
    Calculator for all return-based performance metrics.

    This class provides a convenient interface to calculate all
    return metrics at once.
    """

    @staticmethod
    def calculate_all(
            daily_values: list[DailyValue],
            cash_flows: list[CashFlow] | None = None,
            cost_basis: Decimal | None = None,
            realized_pnl: Decimal | None = None,
            net_invested: Decimal | None = None,
    ) -> PerformanceMetrics:
        """
        Calculate all return metrics.

        Args:
            daily_values: Daily portfolio values with cash flows
            cash_flows: Optional separate list of cash flows for XIRR
                       If None, extracted from daily_values
            cost_basis: Optional cost basis from valuation service.
                       If provided, used for total_gain calculation
            realized_pnl: Optional realized P&L from valuation service.
            net_invested: Optional net invested from valuation service.
                       If provided, used as denominator for simple_return
                       to match Overview page calculation.

        Returns:
            PerformanceMetrics with all available metrics
        """
        result = PerformanceMetrics()

        if len(daily_values) < 2:
            result.has_sufficient_data = False
            result.warnings.append("Insufficient data: need at least 2 data points")
            return result

        # Sort by date
        sorted_values = sorted(daily_values, key=lambda x: x.date)

        # Basic info
        result.start_value = sorted_values[0].value
        result.end_value = sorted_values[-1].value
        result.trading_days = len(sorted_values)
        # Inclusive day count: counts from close of day before first data point
        # E.g., Jan 1 to Jan 25 = 25 days (not 24), per institutional standard
        result.calendar_days = (sorted_values[-1].date - sorted_values[0].date).days + 1

        # Calculate deposits and withdrawals DURING the period
        # IMPORTANT: Exclude the first day's cash flow - that's the initial investment,
        # which is already reflected in start_value. Only count subsequent cash flows.
        # This prevents double-counting the initial investment.
        subsequent_values = sorted_values[1:] if len(sorted_values) > 1 else []

        # Use Decimal("0") as start to ensure sum returns Decimal, not int
        result.total_deposits = sum(
            (dv.cash_flow for dv in subsequent_values if dv.cash_flow > 0),
            Decimal("0")
        )
        result.total_withdrawals = abs(sum(
            (dv.cash_flow for dv in subsequent_values if dv.cash_flow < 0),
            Decimal("0")
        ))

        # =====================================================================
        # SIMPLE RETURN CALCULATION
        # =====================================================================
        #
        # Simple Return measures the return on capital during the period.
        #
        # Two cases:
        # 1. "All" / inception period (start_value is small, most capital came from deposits):
        #    Use net_invested as denominator for consistency with Overview page
        #    simple_return = total_pnl / net_invested
        #
        # 2. Shorter periods (1M, 3M, YTD, 1Y) where start_value is meaningful:
        #    Use period-based formula with start_value as base
        #    simple_return = (end_value - start_value - net_cash_flows) / start_value
        #
        # =====================================================================

        # Store cost_basis and realized_pnl
        if cost_basis is not None and cost_basis > 0:
            result.cost_basis = cost_basis
            result.total_realized_pnl = realized_pnl if realized_pnl is not None else Decimal("0")

        # Determine if this is an "inception" period (start_value is small relative to deposits)
        # This happens when the period starts before/at the first investment
        is_inception_period = (
            result.start_value < result.total_deposits * Decimal("0.5")
            if result.total_deposits > 0
            else result.start_value == 0
        )

        # Net invested from valuation service (for inception period)
        # or deposits - withdrawals during period (for shorter periods)
        if is_inception_period and net_invested is not None and net_invested > 0:
            result.net_invested = net_invested
        else:
            result.net_invested = result.total_deposits - result.total_withdrawals

        if is_inception_period:
            # Use valuation-based formula (matches Overview page calculation)
            if cost_basis is not None and cost_basis > 0:
                # total_pnl = unrealized_pnl + realized_pnl
                # unrealized_pnl = end_value - cost_basis
                unrealized_pnl = result.end_value - cost_basis
                total_realized = realized_pnl if realized_pnl is not None else Decimal("0")
                result.total_gain = unrealized_pnl + total_realized
            else:
                # Fallback: total_gain = end_value - net_invested
                result.total_gain = result.end_value - (result.net_invested or Decimal("0"))

            # Use net_invested as denominator (same as Overview page pnl_percentage)
            if net_invested is not None and net_invested > 0:
                result.roi = result.total_gain / net_invested
            elif cost_basis is not None and cost_basis > 0:
                result.roi = result.total_gain / cost_basis
            elif result.net_invested is not None and result.net_invested > 0:
                # Final fallback to calculated net_invested
                result.roi = result.total_gain / result.net_invested
            else:
                result.roi = Decimal("0")  # No investment = 0% return
        else:
            # Use period-based formula for shorter periods
            # Formula: (end_value - start_value - net_cash_flows) / start_value
            net_cash_flow = result.total_deposits - result.total_withdrawals
            result.total_gain = result.end_value - result.start_value - net_cash_flow

            if result.start_value > 0:
                result.roi = result.total_gain / result.start_value
            else:
                # For periods starting at 0, use net_invested as denominator
                if result.net_invested is not None and result.net_invested > 0:
                    result.roi = result.total_gain / result.net_invested
                else:
                    result.roi = Decimal("0")  # No investment = 0% return

        if result.roi is not None and result.calendar_days >= 365:
            result.roi_annualized = annualize_return(
                result.roi, result.calendar_days
            )

        # TWR
        result.twr = calculate_twr(sorted_values)

        if result.twr is not None and result.calendar_days >= 365:
            result.twr_annualized = annualize_return(
                result.twr, result.calendar_days
            )

        # XIRR
        if cash_flows is not None and len(cash_flows) >= 2:
            result.xirr = calculate_xirr(cash_flows)
            result.mwr = result.xirr  # MWR is the same as IRR
            result.irr = result.xirr

        return result
