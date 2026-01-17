# backend/app/services/analytics/returns.py
"""
Return calculation functions for the Analytics Service.

This module contains pure functions for calculating various return metrics:
- Simple Return: Basic (End - Start) / Start
- Time-Weighted Return (TWR): Removes cash flow bias (Daily Linking Method)
- Compound Annual Growth Rate (CAGR): Annualized growth
- Internal Rate of Return (IRR): Money-weighted return
- Extended IRR (XIRR): IRR with exact dates (Newton-Raphson solver)

All functions are stateless and operate on Decimal values for precision.
No external dependencies (scipy, numpy) - pure Python only.

Formulas:
    Simple Return = (End - Start) / Start

    TWR (Daily Linking Method):
        r_daily = (V_end - CF) / V_start - 1
        TWR = ∏(1 + r_daily) - 1

    CAGR = (End / Start)^(365/days) - 1

    XIRR solves: Σ CF_i / (1 + r)^((d_i - d_0) / 365) = 0
"""

import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app.services.analytics.types import CashFlow, DailyValue, PerformanceMetrics

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

TRADING_DAYS_PER_YEAR = 252
CALENDAR_DAYS_PER_YEAR = 365

# IRR solver settings
IRR_MAX_ITERATIONS = 100
IRR_TOLERANCE = Decimal("0.0000001")  # 0.00001% precision
IRR_INITIAL_GUESS = Decimal("0.1")  # Start at 10%


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
    if start_value == 0:
        return None

    return (end_value - start_value) / start_value


def annualize_return(
        total_return: Decimal,
        days: int,
        use_trading_days: bool = False,
) -> Decimal | None:
    """
    Annualize a return over a given number of days.

    Formula: (1 + r)^(365/days) - 1

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

    # Use float for exponentiation, then convert back
    annualized = Decimal(str(float(base) ** float(exponent))) - Decimal("1")

    return annualized


# =============================================================================
# TIME-WEIGHTED RETURN (TWR)
# =============================================================================

def calculate_twr(daily_values: list[DailyValue]) -> Decimal | None:
    """
    Calculate Time-Weighted Return using the Daily Linking Method.

    TWR removes the impact of cash flows, showing pure investment performance.
    This is the industry standard for comparing fund managers.

    Formula (Daily Linking Method):
        r_daily = (V_end - CF) / V_start - 1
        TWR = ∏(1 + r_daily) - 1

    Where:
        V_end = Portfolio value at end of day
        V_start = Portfolio value at start of day (previous day's end value)
        CF = Cash flow on that day (positive = deposit, negative = withdrawal)

    This method is simpler and more robust than breaking into sub-periods.
    Since we have daily valuations, we can calculate the return for each day
    and chain-link them together.

    Args:
        daily_values: List of DailyValue with date, value, and cash_flow

    Returns:
        TWR as decimal (e.g., 0.15 = 15%), or None if insufficient data
    """
    if len(daily_values) < 2:
        return None

    # Sort by date
    sorted_values = sorted(daily_values, key=lambda x: x.date)

    # Calculate chain-linked returns using Daily Linking Method
    cumulative = Decimal("1")

    for i in range(1, len(sorted_values)):
        prev_value = sorted_values[i - 1].value  # V_start (previous day's end value)
        curr_value = sorted_values[i].value  # V_end (today's end value)
        cash_flow = sorted_values[i].cash_flow  # CF (cash flow today)

        # Skip if previous value is zero or negative
        if prev_value <= 0:
            logger.warning(f"TWR: Invalid previous value at {sorted_values[i].date}")
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

    # Use float for exponentiation
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

    # Newton-Raphson method
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
    ) -> PerformanceMetrics:
        """
        Calculate all return metrics.

        Args:
            daily_values: Daily portfolio values with cash flows
            cash_flows: Optional separate list of cash flows for XIRR
                       If None, extracted from daily_values
            cost_basis: Optional cost basis from valuation service.
                       If provided, used for simple_return calculation
                       (crucial for portfolios without cash tracking)

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
        result.calendar_days = (sorted_values[-1].date - sorted_values[0].date).days

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
        # For portfolios WITH cash tracking (has DEPOSIT/WITHDRAWAL):
        #   - start_value is meaningful (initial cash balance)
        #   - total_gain = end_value - start_value - net_cash_flows
        #   - simple_return = total_gain / start_value
        #
        # For portfolios WITHOUT cash tracking (only BUY/SELL):
        #   - start_value is just the first transaction value (not meaningful)
        #   - We should use cost_basis as the denominator
        #   - simple_return = (end_value - cost_basis) / cost_basis
        #   - This equals: unrealized_pnl / cost_basis
        #
        # We detect which case we're in by checking if cost_basis is provided
        # and if it differs significantly from the start_value approach.
        # =====================================================================

        if cost_basis is not None and cost_basis > 0:
            # Unrealized P&L = end_value - cost_basis
            unrealized_pnl = result.end_value - cost_basis

            # Total gain includes both unrealized and realized P&L
            # Realized P&L comes from closed positions (sales)
            total_realized = realized_pnl if realized_pnl is not None else Decimal("0")
            result.total_gain = unrealized_pnl + total_realized
            result.total_realized_pnl = total_realized

            result.simple_return = result.total_gain / cost_basis
            result.cost_basis = cost_basis
            result.net_invested = cost_basis  # Actual capital invested by user
        else:
            # Fallback: traditional calculation using start_value
            # This works for portfolios with explicit cash tracking
            net_cash_flow = result.total_deposits - result.total_withdrawals
            result.total_gain = result.end_value - result.start_value - net_cash_flow

            if result.start_value > 0:
                result.simple_return = result.total_gain / result.start_value
                result.net_invested = result.start_value  # For cash-tracked portfolios
            else:
                result.simple_return = None

        if result.simple_return is not None and result.calendar_days > 0:
            result.simple_return_annualized = annualize_return(
                result.simple_return, result.calendar_days
            )

        # TWR
        result.twr = calculate_twr(sorted_values)

        if result.twr is not None and result.calendar_days > 0:
            result.twr_annualized = annualize_return(
                result.twr, result.calendar_days
            )

        # CAGR - Compound Annual Growth Rate
        # We use the cash-flow-adjusted simple_return to calculate CAGR
        # This gives the true annualized growth rate of the investment
        # Traditional CAGR = (end/start)^(1/years) - 1 ignores cash flows
        # Adjusted CAGR = (1 + simple_return)^(365/days) - 1
        if result.simple_return is not None and result.calendar_days > 0:
            result.cagr = annualize_return(
                result.simple_return, result.calendar_days
            )

        # XIRR
        if cash_flows is not None and len(cash_flows) >= 2:
            result.xirr = calculate_xirr(cash_flows)
            result.mwr = result.xirr  # MWR is the same as IRR
            result.irr = result.xirr

        return result
