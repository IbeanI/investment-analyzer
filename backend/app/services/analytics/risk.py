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
from datetime import date
from decimal import Decimal
from statistics import mean, stdev

from app.services.analytics.types import DailyValue, RiskMetrics, DrawdownPeriod

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

TRADING_DAYS_PER_YEAR = 252
DEFAULT_RISK_FREE_RATE = Decimal("0.02")  # 2% annual


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
    if len(daily_values) < 2:
        return []

    returns = []
    sorted_values = sorted(daily_values, key=lambda x: x.date)

    for i in range(1, len(sorted_values)):
        prev_value = sorted_values[i - 1].value  # V_start
        curr_value = sorted_values[i].value  # V_end
        cash_flow = sorted_values[i].cash_flow  # CF

        if prev_value <= 0:
            continue

        # Daily Linking Method: r = (V_end - CF) / V_start - 1
        daily_return = (curr_value - cash_flow) / prev_value - Decimal("1")
        returns.append(daily_return)

    return returns


def _decimal_stdev(values: list[Decimal]) -> Decimal | None:
    """Calculate standard deviation of Decimal values."""
    if len(values) < 2:
        return None

    # Convert to float for calculation
    float_values = [float(v) for v in values]

    try:
        std = stdev(float_values)
        return Decimal(str(std))
    except Exception:
        return None


def _decimal_mean(values: list[Decimal]) -> Decimal | None:
    """Calculate mean of Decimal values."""
    if not values:
        return None

    float_values = [float(v) for v in values]
    return Decimal(str(mean(float_values)))


# =============================================================================
# VOLATILITY
# =============================================================================

def calculate_volatility(
        daily_returns: list[Decimal],
        annualize: bool = True,
) -> Decimal | None:
    """
    Calculate volatility (standard deviation of returns).
    
    Args:
        daily_returns: List of daily returns
        annualize: If True, multiply by √252 for annualized volatility
        
    Returns:
        Volatility as decimal (e.g., 0.20 = 20%), or None if insufficient data
    """
    if len(daily_returns) < 2:
        return None

    vol = _decimal_stdev(daily_returns)

    if vol is None:
        return None

    if annualize:
        vol = vol * Decimal(str(math.sqrt(TRADING_DAYS_PER_YEAR)))

    return vol


def calculate_downside_deviation(
        daily_returns: list[Decimal],
        target_return: Decimal = Decimal("0"),
        annualize: bool = True,
) -> Decimal | None:
    """
    Calculate downside deviation (semi-deviation).
    
    Only considers returns below the target (negative returns by default).
    Used in Sortino Ratio calculation.
    
    Args:
        daily_returns: List of daily returns
        target_return: Minimum acceptable return (default 0)
        annualize: If True, annualize the result
        
    Returns:
        Downside deviation as decimal, or None if insufficient data
    """
    downside_returns = [r for r in daily_returns if r < target_return]

    if len(downside_returns) < 2:
        return None

    # Calculate deviation from target
    deviations = [(r - target_return) ** 2 for r in downside_returns]
    mean_sq_deviation = sum(deviations) / Decimal(str(len(deviations)))

    downside_dev = Decimal(str(math.sqrt(float(mean_sq_deviation))))

    if annualize:
        downside_dev = downside_dev * Decimal(str(math.sqrt(TRADING_DAYS_PER_YEAR)))

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
    if volatility is None or volatility == 0:
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
    if downside_deviation is None or downside_deviation == 0:
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
    if max_drawdown is None or max_drawdown == 0:
        return None

    # Max drawdown is negative, so we use absolute value
    calmar = cagr / abs(max_drawdown)

    return calmar


# =============================================================================
# DRAWDOWN
# =============================================================================

def calculate_drawdowns(
        daily_values: list[DailyValue],
) -> tuple[Decimal | None, list[DrawdownPeriod]]:
    """
    Calculate maximum drawdown and all drawdown periods.
    
    A drawdown is the decline from a peak to a trough before a new peak.
    
    Args:
        daily_values: List of DailyValue sorted by date
        
    Returns:
        Tuple of (max_drawdown, list of DrawdownPeriod)
        max_drawdown is negative decimal (e.g., -0.15 = -15% drawdown)
    """
    if len(daily_values) < 2:
        return None, []

    sorted_values = sorted(daily_values, key=lambda x: x.date)

    # Track peaks and drawdowns
    peak_value = sorted_values[0].value
    peak_date = sorted_values[0].date

    max_drawdown = Decimal("0")
    current_drawdown = Decimal("0")

    # For tracking drawdown periods
    drawdown_periods: list[DrawdownPeriod] = []
    in_drawdown = False
    dd_start_date: date | None = None
    dd_trough_date: date | None = None
    dd_trough_value: Decimal | None = None

    for dv in sorted_values:
        value = dv.value
        current_date = dv.date

        if value >= peak_value:
            # New peak reached
            if in_drawdown and dd_start_date and dd_trough_date:
                # Record the completed drawdown period
                depth = (dd_trough_value - peak_value) / peak_value if peak_value > 0 else Decimal("0")
                duration = (current_date - dd_start_date).days
                recovery = (current_date - dd_trough_date).days

                drawdown_periods.append(DrawdownPeriod(
                    start_date=dd_start_date,
                    trough_date=dd_trough_date,
                    end_date=current_date,
                    depth=depth,
                    duration_days=duration,
                    recovery_days=recovery,
                ))

            peak_value = value
            peak_date = current_date
            in_drawdown = False
            current_drawdown = Decimal("0")
        else:
            # Below peak - in drawdown
            if peak_value > 0:
                current_drawdown = (value - peak_value) / peak_value

                if not in_drawdown:
                    # Start of new drawdown
                    in_drawdown = True
                    dd_start_date = peak_date
                    dd_trough_date = current_date
                    dd_trough_value = value
                elif value < dd_trough_value:
                    # New trough
                    dd_trough_date = current_date
                    dd_trough_value = value

                if current_drawdown < max_drawdown:
                    max_drawdown = current_drawdown

    # Handle ongoing drawdown (not recovered)
    if in_drawdown and dd_start_date and dd_trough_date:
        depth = (dd_trough_value - peak_value) / peak_value if peak_value > 0 else Decimal("0")
        duration = (sorted_values[-1].date - dd_start_date).days

        drawdown_periods.append(DrawdownPeriod(
            start_date=dd_start_date,
            trough_date=dd_trough_date,
            end_date=None,  # Not recovered
            depth=depth,
            duration_days=duration,
            recovery_days=None,
        ))

    return max_drawdown, drawdown_periods


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

    if peak_value <= 0:
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
    if len(daily_returns) < 10:
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

    positive = [r for r in daily_returns if r > 0]
    negative = [r for r in daily_returns if r < 0]

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
            total_return_annualized: Decimal | None = None,
            cagr: Decimal | None = None,
            risk_free_rate: Decimal = DEFAULT_RISK_FREE_RATE,
    ) -> RiskMetrics:
        """
        Calculate all risk metrics.
        
        Args:
            daily_values: Daily portfolio values
            total_return_annualized: Annualized return for Sharpe calculation
            cagr: CAGR for Calmar calculation
            risk_free_rate: Risk-free rate (default 2%)
        
        Returns:
            RiskMetrics with all available metrics
        """
        result = RiskMetrics()

        if len(daily_values) < 2:
            result.has_sufficient_data = False
            result.warnings.append("Insufficient data: need at least 2 data points")
            return result

        # Calculate daily returns
        daily_returns = calculate_daily_returns(daily_values)

        if len(daily_returns) < 2:
            result.has_sufficient_data = False
            result.warnings.append("Could not calculate daily returns")
            return result

        # Volatility
        result.volatility_daily = calculate_volatility(daily_returns, annualize=False)
        result.volatility_annualized = calculate_volatility(daily_returns, annualize=True)
        result.downside_deviation = calculate_downside_deviation(daily_returns)

        # Risk-adjusted ratios (need return data)
        if total_return_annualized is not None and result.volatility_annualized:
            result.sharpe_ratio = calculate_sharpe_ratio(
                total_return_annualized,
                result.volatility_annualized,
                risk_free_rate,
            )

        if total_return_annualized is not None and result.downside_deviation:
            result.sortino_ratio = calculate_sortino_ratio(
                total_return_annualized,
                result.downside_deviation,
                risk_free_rate,
            )

        # Drawdown
        max_dd, dd_periods = calculate_drawdowns(daily_values)
        result.max_drawdown = max_dd
        result.drawdown_periods = dd_periods

        # Find max drawdown dates
        if dd_periods:
            worst_dd = min(dd_periods, key=lambda x: x.depth)
            result.max_drawdown_start = worst_dd.start_date
            result.max_drawdown_end = worst_dd.end_date

        result.current_drawdown = calculate_current_drawdown(daily_values)

        # Calmar ratio
        if cagr is not None and max_dd is not None:
            result.calmar_ratio = calculate_calmar_ratio(cagr, max_dd)

        # VaR
        result.var_95 = calculate_var(daily_returns)
        result.cvar_95 = calculate_cvar(daily_returns)

        # Win/Loss stats
        (
            result.positive_days,
            result.negative_days,
            result.win_rate,
            result.best_day,
            result.best_day_date,
            result.worst_day,
            result.worst_day_date,
        ) = calculate_win_statistics(daily_returns)

        return result
