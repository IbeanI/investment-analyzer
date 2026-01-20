# backend/app/services/analytics/risk.py
"""
Risk calculation functions for the Analytics Service.

This module contains pure functions for calculating risk metrics:
- Volatility: Standard deviation of returns (daily and annualized)
- Sharpe Ratio: Risk-adjusted return
- Sortino Ratio: Downside risk-adjusted return
- Max Drawdown: Largest peak-to-trough decline
- Value at Risk (VaR): Potential loss at confidence level
- Win Rate: Percentage of positive days

All functions are stateless and operate on Decimal values for precision.
No external dependencies (scipy, numpy) - uses only `statistics` stdlib.

Formulas:
    Volatility (annualized) = std(daily_returns) * √252

    Sharpe Ratio = (R_p - R_f) / σ_p

    Sortino Ratio = (R_p - R_f) / σ_downside

    Max Drawdown = max((Peak - Trough) / Peak)

    Daily Returns use Daily Linking Method (consistent with TWR):
        r_daily = (V_end - CF) / V_start - 1
"""

import logging
import math
from datetime import date, timedelta
from decimal import Decimal

from app.services.analytics.types import (
    DailyValue,
    DrawdownPeriod,
    RiskMetrics,
    InvestmentPeriod,
    MeasurementPeriodInfo
)
from app.services.constants import (
    TRADING_DAYS_PER_YEAR,
    DEFAULT_RISK_FREE_RATE,
    ZERO,
    DRAWDOWN_RECORDING_THRESHOLD,
    MIN_EQUITY_THRESHOLD,
    MIN_DAYS_FOR_VOLATILITY,
    MIN_VAR_SAMPLE_SIZE,
)

logger = logging.getLogger(__name__)


# =============================================================================
# INVESTMENT PERIOD DETECTION (GIPS Compliance)
# =============================================================================

def split_into_investment_periods(
        daily_values: list[DailyValue],
        min_equity_threshold: Decimal = MIN_EQUITY_THRESHOLD,
) -> list[InvestmentPeriod]:
    """
    Split daily values into distinct investment periods.

    A new period starts when:
    - Portfolio transitions from zero/None to having value
    - Gap of more than `max_gap_days` with no valid data

    A period ends when:
    - Portfolio value drops to zero or None (full liquidation)
    - Data ends

    This follows GIPS (Global Investment Performance Standards) guidelines
    where full liquidation events terminate a measurement period.

    Args:
        daily_values: List of daily portfolio values (must be sorted by date)
        min_equity_threshold: Values below this are considered "zero" (default: 1.0)

    Returns:
        List of InvestmentPeriod objects in chronological order
    """
    if not daily_values:
        return []

    # Ensure sorted by date
    sorted_values = sorted(daily_values, key=lambda x: x.date)

    periods: list[InvestmentPeriod] = []
    current_period_values: list[DailyValue] = []
    period_number = 0

    for dv in sorted_values:
        has_value = (
                dv.value is not None
                and dv.value >= min_equity_threshold
        )

        if has_value:
            # Add to current period
            current_period_values.append(dv)
        else:
            # Zero/None value - end current period if any
            if current_period_values:
                period_number += 1
                periods.append(_create_period(
                    current_period_values,
                    period_number,
                    end_reason="full_liquidation"
                ))
                current_period_values = []

    # Don't forget the last period (still active)
    if current_period_values:
        period_number += 1
        periods.append(_create_period(
            current_period_values,
            period_number,
            end_reason="active",
            is_active=True
        ))

    return periods


def _create_period(
        values: list[DailyValue],
        period_number: int,
        end_reason: str,
        is_active: bool = False,
) -> InvestmentPeriod:
    """Helper to create an InvestmentPeriod from a list of values."""
    return InvestmentPeriod(
        period_number=period_number,
        start_date=values[0].date,
        end_date=values[-1].date,
        start_value=values[0].value,
        end_value=values[-1].value,
        end_reason=end_reason,
        is_active=is_active,
        trading_days=len(values),
    )


def get_active_period_values(
        daily_values: list[DailyValue],
        periods: list[InvestmentPeriod],
) -> list[DailyValue]:
    """
    Extract daily values for the current active investment period.

    Args:
        daily_values: All daily values
        periods: List of investment periods

    Returns:
        Daily values for the active period only
    """
    if not periods:
        return []

    # Find the active period
    active_period = next((p for p in periods if p.is_active), None)
    if not active_period:
        # No active period - use the last one
        active_period = periods[-1]

    # Filter daily values to this period
    return [
        dv for dv in daily_values
        if (dv.value is not None
            and dv.value >= MIN_EQUITY_THRESHOLD
            and active_period.start_date <= dv.date <= active_period.end_date)
    ]


def get_all_period_values(
        daily_values: list[DailyValue],
        periods: list[InvestmentPeriod],
) -> list[DailyValue]:
    """
    Extract daily values for ALL investment periods combined.

    Used for full_history scope - chains all periods together,
    excluding zero-equity days between periods.

    Args:
        daily_values: All daily values
        periods: List of investment periods

    Returns:
        Daily values from all periods (zero-equity days excluded)
    """
    if not periods:
        return []

    # Get date ranges from all periods
    valid_dates: set[date] = set()
    for period in periods:
        # Add all dates in this period's range
        current = period.start_date
        while current <= period.end_date:
            valid_dates.add(current)
            current += timedelta(days=1)

    # Filter daily values to only those in valid periods with actual value
    return [
        dv for dv in daily_values
        if (dv.value is not None
            and dv.value >= MIN_EQUITY_THRESHOLD
            and dv.date in valid_dates)
    ]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def calculate_daily_returns(daily_values: list[DailyValue]) -> list[Decimal]:
    """
    Calculate daily returns from portfolio values.

    Uses the Daily Linking Method (consistent with TWR calculation):
        r_daily = (V_end - CF) / V_start - 1

    Where:
        V_end = Portfolio value at end of day
        V_start = Portfolio value at start of day (previous day's end value)
        CF = Cash flow on that day

    Args:
        daily_values: List of DailyValue sorted by date

    Returns:
        List of daily returns (one less than input length)
    """
    if len(daily_values) < MIN_DAYS_FOR_VOLATILITY:
        return []

    returns = []
    sorted_values = sorted(daily_values, key=lambda x: x.date)

    for i in range(1, len(sorted_values)):
        prev_value = sorted_values[i - 1].value  # V_start
        curr_value = sorted_values[i].value  # V_end
        cash_flow = sorted_values[i].cash_flow  # CF

        if prev_value <= ZERO:
            continue

        # Daily Linking Method: r = (V_end - CF) / V_start - 1
        daily_return = (curr_value - cash_flow) / prev_value - Decimal("1")
        returns.append(daily_return)

    return returns


def _decimal_stdev(values: list[Decimal]) -> Decimal | None:
    """
    Calculate standard deviation of Decimal values using pure Decimal arithmetic.

    This avoids float conversion which can cause precision loss for very small
    values (< 0.00001) common in daily return calculations.

    Formula: σ = sqrt(Σ(x - μ)² / (n - 1))  [sample standard deviation]

    Uses Decimal.sqrt() which maintains full precision for the square root
    operation.

    Args:
        values: List of Decimal values

    Returns:
        Standard deviation as Decimal, or None if insufficient data
    """
    if len(values) < MIN_DAYS_FOR_VOLATILITY:
        return None

    n = Decimal(str(len(values)))

    # Calculate mean using pure Decimal
    total = sum(values, Decimal("0"))
    mean_val = total / n

    # Calculate sum of squared differences from mean
    squared_diffs = [(x - mean_val) ** 2 for x in values]
    sum_squared_diffs = sum(squared_diffs, Decimal("0"))

    # Sample variance (divide by n-1)
    variance = sum_squared_diffs / (n - Decimal("1"))

    # Square root using Decimal.sqrt()
    # This maintains precision better than float(variance) ** 0.5
    try:
        std = variance.sqrt()
        return std
    except Exception:
        # Fallback to float only if Decimal.sqrt() fails
        # (shouldn't happen with valid positive variance)
        try:
            return Decimal(str(math.sqrt(float(variance))))
        except Exception:
            return None


def _decimal_mean(values: list[Decimal]) -> Decimal | None:
    """
    Calculate mean of Decimal values using pure Decimal arithmetic.

    Args:
        values: List of Decimal values

    Returns:
        Mean as Decimal, or None if empty list
    """
    if not values:
        return None

    total = sum(values, Decimal("0"))
    return total / Decimal(str(len(values)))


# =============================================================================
# VOLATILITY
# =============================================================================

def calculate_volatility(
        daily_returns: list[Decimal],
        annualize: bool = True,
) -> Decimal | None:
    """
    Calculate volatility (standard deviation of returns) using pure Decimal arithmetic.

    Args:
        daily_returns: List of daily returns
        annualize: If True, multiply by √252 for annualized volatility

    Returns:
        Volatility as decimal (e.g., 0.20 = 20%), or None if insufficient data
    """
    if len(daily_returns) < MIN_DAYS_FOR_VOLATILITY:
        return None

    vol = _decimal_stdev(daily_returns)

    if vol is None:
        return None

    if annualize:
        # Use Decimal.sqrt() for precision in annualization factor
        annualization_factor = Decimal(str(TRADING_DAYS_PER_YEAR)).sqrt()
        vol = vol * annualization_factor

    return vol


def calculate_downside_deviation(
        daily_returns: list[Decimal],
        target_return: Decimal = Decimal("0"),
        annualize: bool = True,
) -> Decimal | None:
    """
    Calculate downside deviation (semi-deviation) using pure Decimal arithmetic.

    Only considers returns below the target (negative returns by default).
    Used in Sortino Ratio calculation.

    Formula: σ_down = sqrt(Σ(r - target)² / n) for all r < target

    Args:
        daily_returns: List of daily returns
        target_return: Minimum acceptable return (default 0)
        annualize: If True, annualize the result

    Returns:
        Downside deviation as decimal, or None if insufficient data
    """
    downside_returns = [r for r in daily_returns if r < target_return]

    if len(downside_returns) < MIN_DAYS_FOR_VOLATILITY:
        return None

    # Calculate deviation from target using pure Decimal
    deviations = [(r - target_return) ** 2 for r in downside_returns]
    sum_deviations = sum(deviations, Decimal("0"))
    mean_sq_deviation = sum_deviations / Decimal(str(len(deviations)))

    # Use Decimal.sqrt() for precision
    try:
        downside_dev = mean_sq_deviation.sqrt()
    except Exception:
        # Fallback to float only if Decimal.sqrt() fails
        downside_dev = Decimal(str(math.sqrt(float(mean_sq_deviation))))

    if annualize:
        # Annualization factor: sqrt(252)
        # Pre-calculate as Decimal for precision
        annualization_factor = Decimal(str(TRADING_DAYS_PER_YEAR)).sqrt()
        downside_dev = downside_dev * annualization_factor

    return downside_dev


# =============================================================================
# SHARPE RATIO
# =============================================================================

def calculate_sharpe_ratio(
        total_return: Decimal,
        volatility: Decimal,
        risk_free_rate: Decimal = DEFAULT_RISK_FREE_RATE,
        period_days: int = TRADING_DAYS_PER_YEAR,
) -> Decimal | None:
    """
    Calculate Sharpe Ratio.

    Formula: Sharpe = (R_p - R_f) / σ_p

    Where:
        R_p = Portfolio return (annualized)
        R_f = Risk-free rate (annualized)
        σ_p = Portfolio volatility (annualized)

    Args:
        total_return: Annualized portfolio return
        volatility: Annualized volatility
        risk_free_rate: Annualized risk-free rate (default 2%)
        period_days: Number of trading days in period

    Returns:
        Sharpe ratio, or None if volatility is zero
    """
    if volatility is None or volatility == ZERO:
        return None

    excess_return = total_return - risk_free_rate
    sharpe = excess_return / volatility

    return sharpe


def calculate_sortino_ratio(
        total_return: Decimal,
        downside_deviation: Decimal,
        risk_free_rate: Decimal = DEFAULT_RISK_FREE_RATE,
) -> Decimal | None:
    """
    Calculate Sortino Ratio.

    Like Sharpe but only penalizes downside volatility.

    Formula: Sortino = (R_p - R_f) / σ_downside

    Args:
        total_return: Annualized portfolio return
        downside_deviation: Annualized downside deviation
        risk_free_rate: Annualized risk-free rate

    Returns:
        Sortino ratio, or None if downside deviation is zero
    """
    if downside_deviation is None or downside_deviation == ZERO:
        return None

    excess_return = total_return - risk_free_rate
    sortino = excess_return / downside_deviation

    return sortino


def calculate_calmar_ratio(
        cagr: Decimal,
        max_drawdown: Decimal,
) -> Decimal | None:
    """
    Calculate Calmar Ratio.

    Formula: Calmar = CAGR / |Max Drawdown|

    Args:
        cagr: Compound Annual Growth Rate
        max_drawdown: Maximum drawdown (as negative decimal)

    Returns:
        Calmar ratio, or None if max_drawdown is zero
    """
    if max_drawdown is None or max_drawdown == ZERO:
        return None

    # Max drawdown is negative, so we use absolute value
    calmar = cagr / abs(max_drawdown)

    return calmar


# =============================================================================
# DRAWDOWN
# =============================================================================

def calculate_drawdowns(
        daily_values: list[DailyValue],
        top_n: int = 5,
) -> tuple[Decimal | None, DrawdownPeriod | None, list[DrawdownPeriod]]:
    """
    Calculate drawdown metrics from daily values.

    IMPORTANT: This function filters out days with zero or None equity.
    Zero-equity days represent intentional liquidations, not losses.
    Metrics are calculated within investment periods, not across them.

    Args:
        daily_values: List of daily portfolio values
        top_n: Number of worst drawdown periods to return

    Returns:
        Tuple of:
        - max_drawdown: Worst drawdown as negative decimal (e.g., -0.25 = -25%)
        - max_drawdown_period: Details of the worst drawdown
        - top_drawdowns: List of top N worst drawdown periods
    """
    # Filter to valid values only (exclude None and zero-equity days)
    valid_values = [
        dv for dv in daily_values
        if dv.value is not None and dv.value >= MIN_EQUITY_THRESHOLD
    ]

    if len(valid_values) < MIN_DAYS_FOR_VOLATILITY:
        return None, None, []

    # Sort by date
    sorted_values = sorted(valid_values, key=lambda x: x.date)

    # Track peak and drawdown periods
    peak_value = sorted_values[0].value
    peak_date = sorted_values[0].date

    current_drawdown_start: date | None = None
    current_trough_date: date | None = None
    current_trough_value: Decimal | None = None

    drawdown_periods: list[DrawdownPeriod] = []
    max_drawdown = Decimal("0")

    for dv in sorted_values:
        if dv.value >= peak_value:
            # New peak - close any open drawdown period
            if current_drawdown_start is not None and current_trough_value is not None:
                depth = (current_trough_value - peak_value) / peak_value
                if depth < DRAWDOWN_RECORDING_THRESHOLD:  # Only record >1% drawdowns
                    period = DrawdownPeriod(
                        start_date=current_drawdown_start,
                        trough_date=current_trough_date,
                        end_date=dv.date,
                        depth=depth.quantize(Decimal("0.0001")),
                        duration_days=(dv.date - current_drawdown_start).days,
                        recovery_days=(dv.date - current_trough_date).days if current_trough_date else None,
                    )
                    drawdown_periods.append(period)

            # Reset for new peak
            peak_value = dv.value
            peak_date = dv.date
            current_drawdown_start = None
            current_trough_date = None
            current_trough_value = None
        else:
            # Below peak - in a drawdown
            if current_drawdown_start is None:
                current_drawdown_start = peak_date
                current_trough_date = dv.date
                current_trough_value = dv.value
            elif dv.value < current_trough_value:
                current_trough_date = dv.date
                current_trough_value = dv.value

            # Track max drawdown
            current_dd = (dv.value - peak_value) / peak_value
            if current_dd < max_drawdown:
                max_drawdown = current_dd

    # Handle ongoing drawdown (not yet recovered)
    if current_drawdown_start is not None and current_trough_value is not None:
        depth = (current_trough_value - peak_value) / peak_value
        if depth < DRAWDOWN_RECORDING_THRESHOLD:
            period = DrawdownPeriod(
                start_date=current_drawdown_start,
                trough_date=current_trough_date,
                end_date=None,  # Ongoing
                depth=depth.quantize(Decimal("0.0001")),
                duration_days=(sorted_values[-1].date - current_drawdown_start).days,
                recovery_days=None,  # Not recovered
            )
            drawdown_periods.append(period)

    # Sort by depth (worst first) and take top N
    drawdown_periods.sort(key=lambda x: x.depth)
    top_drawdowns = drawdown_periods[:top_n]

    # Find the worst drawdown period
    max_dd_period = top_drawdowns[0] if top_drawdowns else None

    return (
        max_drawdown.quantize(Decimal("0.0001")) if max_drawdown < ZERO else None,
        max_dd_period,
        top_drawdowns,
    )


def calculate_current_drawdown(
        daily_values: list[DailyValue],
) -> Decimal | None:
    """
    Calculate current drawdown from most recent peak.

    Args:
        daily_values: List of DailyValue

    Returns:
        Current drawdown as negative decimal, or Decimal("0") if at peak
    """
    if not daily_values:
        return None

    sorted_values = sorted(daily_values, key=lambda x: x.date)

    peak_value = max(dv.value for dv in sorted_values)
    current_value = sorted_values[-1].value

    if peak_value <= ZERO:
        return None

    return (current_value - peak_value) / peak_value


# =============================================================================
# VALUE AT RISK (VaR)
# =============================================================================

def calculate_var(
        daily_returns: list[Decimal],
        confidence_level: Decimal = Decimal("0.95"),
) -> Decimal | None:
    """
    Calculate Value at Risk using historical method.

    VaR is the maximum expected loss at a given confidence level.

    Args:
        daily_returns: List of daily returns
        confidence_level: Confidence level (e.g., 0.95 for 95%)

    Returns:
        VaR as negative decimal (e.g., -0.02 = -2% daily VaR)
    """
    if len(daily_returns) < MIN_VAR_SAMPLE_SIZE:
        return None

    sorted_returns = sorted(daily_returns)

    # Find the percentile
    index = int(len(sorted_returns) * (1 - float(confidence_level)))
    index = max(0, min(index, len(sorted_returns) - 1))

    return sorted_returns[index]


def calculate_cvar(
        daily_returns: list[Decimal],
        confidence_level: Decimal = Decimal("0.95"),
) -> Decimal | None:
    """
    Calculate Conditional Value at Risk (Expected Shortfall).

    CVaR is the expected loss given that the loss exceeds VaR.

    Args:
        daily_returns: List of daily returns
        confidence_level: Confidence level

    Returns:
        CVaR as negative decimal
    """
    var = calculate_var(daily_returns, confidence_level)

    if var is None:
        return None

    # Average of returns worse than VaR
    tail_returns = [r for r in daily_returns if r <= var]

    if not tail_returns:
        return var

    return _decimal_mean(tail_returns)


# =============================================================================
# WIN/LOSS STATISTICS
# =============================================================================

def calculate_win_statistics(
        daily_returns: list[Decimal],
) -> tuple[int, int, Decimal | None, Decimal | None, date | None, Decimal | None, date | None]:
    """
    Calculate win/loss statistics.

    Args:
        daily_returns: List of daily returns

    Returns:
        Tuple of (positive_days, negative_days, win_rate, best_day, best_date, worst_day, worst_date)
    """
    if not daily_returns:
        return 0, 0, None, None, None, None, None

    positive = [r for r in daily_returns if r > ZERO]
    negative = [r for r in daily_returns if r < ZERO]

    positive_days = len(positive)
    negative_days = len(negative)
    total_days = positive_days + negative_days

    win_rate = Decimal(str(positive_days / total_days)) if total_days > 0 else None

    best_day = max(daily_returns) if daily_returns else None
    worst_day = min(daily_returns) if daily_returns else None

    return positive_days, negative_days, win_rate, best_day, None, worst_day, None


# =============================================================================
# COMBINED RISK CALCULATOR
# =============================================================================

class RiskCalculator:
    """
    Calculator for all risk-related metrics.

    This class provides a convenient interface to calculate all
    risk metrics at once.
    """

    @staticmethod
    def calculate_all(
            daily_values: list[DailyValue],
            risk_free_rate: Decimal = Decimal("0.02"),
            annualized_return: Decimal | None = None,
            scope: str = "current_period",  # NEW: "current_period" or "full_history"
    ) -> RiskMetrics:
        """
        Calculate all risk metrics.

        GIPS Compliance:
            - Detects investment periods (separated by full liquidations)
            - scope="current_period": Metrics for active period only (default)
            - scope="full_history": Chain all periods, skip zero-equity days

        Args:
            daily_values: Daily portfolio values with cash flows
            risk_free_rate: Annual risk-free rate (default 2%)
            annualized_return: Pre-calculated annualized return for Sharpe/Sortino
            scope: "current_period" (GIPS default) or "full_history"

        Returns:
            RiskMetrics with all calculated values
        """
        result = RiskMetrics()
        result.scope = scope

        if len(daily_values) < MIN_DAYS_FOR_VOLATILITY:
            result.has_sufficient_data = False
            result.warnings.append("Insufficient data: need at least 2 data points")
            return result

        # =====================================================================
        # STEP 1: Detect Investment Periods (GIPS Compliance)
        # =====================================================================
        periods = split_into_investment_periods(daily_values)
        result.investment_periods = periods
        result.total_periods = len(periods)

        if not periods:
            result.has_sufficient_data = False
            result.warnings.append("No valid investment periods found (all values zero or None)")
            return result

        if len(periods) > 1:
            if scope == "current_period":
                result.warnings.append(
                    f"Portfolio has {len(periods)} investment periods. "
                    f"Metrics calculated for current period only (GIPS-compliant). "
                    f"Use scope=full_history to see combined metrics."
                )
            else:
                result.warnings.append(
                    f"Portfolio has {len(periods)} investment periods. "
                    f"Metrics calculated across all periods (zero-equity days excluded)."
                )

        # =====================================================================
        # STEP 2: Select Values Based on Scope
        # =====================================================================
        if scope == "full_history":
            # Use all valid values across all periods
            analysis_values = get_all_period_values(daily_values, periods)

            # Set measurement period to full range
            result.measurement_period = MeasurementPeriodInfo(
                start_date=periods[0].start_date,
                end_date=periods[-1].end_date,
                trading_days=sum(p.trading_days for p in periods),
                period_number=0,  # 0 = all periods combined
            )
        else:
            # Use active period only (default, GIPS-compliant)
            analysis_values = get_active_period_values(daily_values, periods)

            active_period = next((p for p in periods if p.is_active), periods[-1])
            result.measurement_period = MeasurementPeriodInfo(
                start_date=active_period.start_date,
                end_date=active_period.end_date,
                trading_days=active_period.trading_days,
                period_number=active_period.period_number,
            )

        if len(analysis_values) < MIN_DAYS_FOR_VOLATILITY:
            result.has_sufficient_data = False
            result.warnings.append("Insufficient data in selected scope")
            return result

        # =====================================================================
        # STEP 3: Calculate Daily Returns
        # =====================================================================
        sorted_values = sorted(analysis_values, key=lambda x: x.date)
        daily_returns: list[Decimal] = []

        for i in range(1, len(sorted_values)):
            prev_val = sorted_values[i - 1].value
            curr_val = sorted_values[i].value
            cash_flow = sorted_values[i].cash_flow

            if prev_val > ZERO:
                # Adjust for cash flows
                adjusted_prev = prev_val + cash_flow
                if adjusted_prev > ZERO:
                    ret = (curr_val - adjusted_prev) / adjusted_prev
                    daily_returns.append(ret)

        if not daily_returns:
            result.has_sufficient_data = False
            result.warnings.append("Could not calculate daily returns")
            return result

        # =====================================================================
        # STEP 4: Calculate Risk Metrics
        # =====================================================================

        # Volatility
        result.volatility_daily = calculate_volatility(daily_returns, annualize=False)
        result.volatility_annualized = calculate_volatility(daily_returns, annualize=True)

        # Downside deviation
        result.downside_deviation = calculate_downside_deviation(
            daily_returns, annualize=True
        )

        # Sharpe Ratio
        if annualized_return is not None and result.volatility_annualized:
            result.sharpe_ratio = calculate_sharpe_ratio(
                annualized_return, result.volatility_annualized, risk_free_rate
            )

        # Sortino Ratio
        if annualized_return is not None and result.downside_deviation:
            result.sortino_ratio = calculate_sortino_ratio(
                annualized_return, result.downside_deviation, risk_free_rate
            )

        # Drawdowns (calculated on analysis values)
        max_dd, max_dd_period, top_drawdowns = calculate_drawdowns(analysis_values)
        result.max_drawdown = max_dd
        result.drawdown_periods = top_drawdowns

        if max_dd_period:
            result.max_drawdown_start = max_dd_period.start_date
            result.max_drawdown_end = max_dd_period.end_date

        # Current drawdown
        result.current_drawdown = calculate_current_drawdown(sorted_values)

        # Calmar Ratio
        if annualized_return is not None and max_dd is not None and max_dd < ZERO:
            result.calmar_ratio = calculate_calmar_ratio(annualized_return, max_dd)

        # VaR and CVaR
        result.var_95 = calculate_var(daily_returns, confidence_level=Decimal("0.95"))
        result.cvar_95 = calculate_cvar(daily_returns, confidence_level=Decimal("0.95"))

        # Win/Loss stats
        positive = [r for r in daily_returns if r > ZERO]
        negative = [r for r in daily_returns if r < ZERO]
        result.positive_days = len(positive)
        result.negative_days = len(negative)

        if daily_returns:
            result.win_rate = Decimal(len(positive)) / Decimal(len(daily_returns))
            result.best_day = max(daily_returns)
            result.worst_day = min(daily_returns)

            # Find dates for best/worst days
            for i, ret in enumerate(daily_returns):
                if ret == result.best_day:
                    result.best_day_date = sorted_values[i + 1].date
                if ret == result.worst_day:
                    result.worst_day_date = sorted_values[i + 1].date

        return result
