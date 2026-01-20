# backend/app/services/analytics/benchmark.py
"""
Benchmark comparison functions for the Analytics Service.

This module contains functions for comparing portfolio performance
against a benchmark index (e.g., ^SPX, IWDA.AS):
- Beta: Systematic risk relative to market
- Alpha: Excess return above expected (Jensen's Alpha)
- Correlation: How closely portfolio tracks benchmark
- Tracking Error: Standard deviation of return differences
- Information Ratio: Active return per unit of tracking risk
- Capture Ratios: Up/Down market capture

Unlike other calculators, this module requires benchmark prices
which must be synced to the database beforehand.

No external dependencies (scipy, numpy) - uses only `statistics` stdlib.

Formulas:
    Beta = Cov(R_p, R_m) / Var(R_m)
    
    Alpha = R_p - [R_f + β(R_m - R_f)]
    
    Correlation = Cov(R_p, R_m) / (σ_p * σ_m)
    
    Tracking Error = std(R_p - R_m)
    
    Information Ratio = (R_p - R_m) / Tracking Error
"""

import logging
import math
from decimal import Decimal
from statistics import mean, stdev

from app.services.analytics.types import BenchmarkMetrics
from app.services.constants import (
    TRADING_DAYS_PER_YEAR,
    DEFAULT_RISK_FREE_RATE,
)

logger = logging.getLogger(__name__)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _covariance(x: list[float], y: list[float]) -> float:
    """Calculate covariance between two series."""
    if len(x) != len(y) or len(x) < 2:
        return 0.0

    mean_x = mean(x)
    mean_y = mean(y)

    cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(len(x)))
    return cov / (len(x) - 1)


def _variance(x: list[float]) -> float:
    """Calculate variance of a series."""
    if len(x) < 2:
        return 0.0

    return stdev(x) ** 2


def _correlation(x: list[float], y: list[float]) -> float:
    """Calculate Pearson correlation coefficient."""
    if len(x) != len(y) or len(x) < 2:
        return 0.0

    std_x = stdev(x)
    std_y = stdev(y)

    if std_x == 0 or std_y == 0:
        return 0.0

    cov = _covariance(x, y)
    return cov / (std_x * std_y)


# =============================================================================
# BETA
# =============================================================================

def calculate_beta(
        portfolio_returns: list[Decimal],
        benchmark_returns: list[Decimal],
) -> Decimal | None:
    """
    Calculate Beta (systematic risk).
    
    Beta measures how much the portfolio moves relative to the market.
    
    Formula: β = Cov(R_p, R_m) / Var(R_m)
    
    Interpretation:
        β > 1: More volatile than market
        β < 1: Less volatile than market
        β = 1: Moves exactly with market
        β < 0: Moves opposite to market (rare)
    
    Args:
        portfolio_returns: List of portfolio daily returns
        benchmark_returns: List of benchmark daily returns (same length)
        
    Returns:
        Beta as Decimal, or None if insufficient data
    """
    if len(portfolio_returns) != len(benchmark_returns):
        logger.warning("Portfolio and benchmark return series must be same length")
        return None

    if len(portfolio_returns) < 2:
        return None

    # Convert to float for calculation
    p_returns = [float(r) for r in portfolio_returns]
    b_returns = [float(r) for r in benchmark_returns]

    var_benchmark = _variance(b_returns)

    if var_benchmark == 0:
        return None

    cov = _covariance(p_returns, b_returns)
    beta = cov / var_benchmark

    return Decimal(str(beta))


# =============================================================================
# ALPHA
# =============================================================================

def calculate_alpha(
        portfolio_return: Decimal,
        benchmark_return: Decimal,
        beta: Decimal,
        risk_free_rate: Decimal = DEFAULT_RISK_FREE_RATE,
) -> Decimal:
    """
    Calculate Jensen's Alpha.
    
    Alpha measures the excess return above what CAPM predicts.
    Positive alpha = outperformance, negative = underperformance.
    
    Formula: α = R_p - [R_f + β(R_m - R_f)]
    
    Where:
        R_p = Portfolio return
        R_f = Risk-free rate
        β = Portfolio beta
        R_m = Benchmark return
    
    Args:
        portfolio_return: Total portfolio return (annualized)
        benchmark_return: Total benchmark return (annualized)
        beta: Portfolio beta
        risk_free_rate: Risk-free rate (annualized)
        
    Returns:
        Alpha as Decimal
    """
    expected_return = risk_free_rate + beta * (benchmark_return - risk_free_rate)
    alpha = portfolio_return - expected_return

    return alpha


# =============================================================================
# CORRELATION & R-SQUARED
# =============================================================================

def calculate_correlation(
        portfolio_returns: list[Decimal],
        benchmark_returns: list[Decimal],
) -> Decimal | None:
    """
    Calculate Pearson correlation coefficient.
    
    Measures how closely portfolio returns move with benchmark.
    
    Args:
        portfolio_returns: List of portfolio daily returns
        benchmark_returns: List of benchmark daily returns
        
    Returns:
        Correlation coefficient (-1 to 1), or None if insufficient data
    """
    if len(portfolio_returns) != len(benchmark_returns):
        return None

    if len(portfolio_returns) < 2:
        return None

    p_returns = [float(r) for r in portfolio_returns]
    b_returns = [float(r) for r in benchmark_returns]

    corr = _correlation(p_returns, b_returns)

    return Decimal(str(corr))


def calculate_r_squared(correlation: Decimal) -> Decimal:
    """
    Calculate R-squared (coefficient of determination).
    
    R² shows what proportion of portfolio variance is explained by benchmark.
    
    Formula: R² = correlation²
    
    Interpretation:
        R² = 0.9: 90% of portfolio movement explained by benchmark
        R² = 0.5: 50% explained (significant independent movement)
    
    Args:
        correlation: Pearson correlation coefficient
        
    Returns:
        R-squared (0 to 1)
    """
    return correlation * correlation


# =============================================================================
# TRACKING ERROR & INFORMATION RATIO
# =============================================================================

def calculate_tracking_error(
        portfolio_returns: list[Decimal],
        benchmark_returns: list[Decimal],
        annualize: bool = True,
) -> Decimal | None:
    """
    Calculate Tracking Error.
    
    Tracking error is the standard deviation of the difference
    between portfolio and benchmark returns.
    
    Formula: TE = std(R_p - R_m)
    
    Lower tracking error = portfolio closely follows benchmark.
    Higher tracking error = active management / deviation from benchmark.
    
    Args:
        portfolio_returns: Portfolio daily returns
        benchmark_returns: Benchmark daily returns
        annualize: If True, annualize the result
        
    Returns:
        Tracking error as Decimal, or None if insufficient data
    """
    if len(portfolio_returns) != len(benchmark_returns):
        return None

    if len(portfolio_returns) < 2:
        return None

    # Calculate excess returns
    excess_returns = [
        float(portfolio_returns[i] - benchmark_returns[i])
        for i in range(len(portfolio_returns))
    ]

    te = stdev(excess_returns)

    if annualize:
        te = te * math.sqrt(TRADING_DAYS_PER_YEAR)

    return Decimal(str(te))


def calculate_information_ratio(
        portfolio_return: Decimal,
        benchmark_return: Decimal,
        tracking_error: Decimal,
) -> Decimal | None:
    """
    Calculate Information Ratio.
    
    IR measures how much excess return is generated per unit of tracking risk.
    Higher IR = better risk-adjusted active performance.
    
    Formula: IR = (R_p - R_m) / Tracking Error
    
    Interpretation:
        IR > 0.5: Good active management
        IR > 1.0: Excellent active management
    
    Args:
        portfolio_return: Annualized portfolio return
        benchmark_return: Annualized benchmark return
        tracking_error: Annualized tracking error
        
    Returns:
        Information ratio, or None if tracking error is zero
    """
    if tracking_error is None or tracking_error == 0:
        return None

    excess_return = portfolio_return - benchmark_return
    ir = excess_return / tracking_error

    return ir


# =============================================================================
# CAPTURE RATIOS
# =============================================================================

def calculate_capture_ratios(
        portfolio_returns: list[Decimal],
        benchmark_returns: list[Decimal],
) -> tuple[Decimal | None, Decimal | None]:
    """
    Calculate Up Capture and Down Capture ratios.
    
    Up Capture: Portfolio performance in up markets vs benchmark
    Down Capture: Portfolio performance in down markets vs benchmark
    
    Ideal: High up capture, low down capture
    
    Formula:
        Up Capture = (Σ R_p when R_m > 0) / (Σ R_m when R_m > 0)
        Down Capture = (Σ R_p when R_m < 0) / (Σ R_m when R_m < 0)
    
    Args:
        portfolio_returns: Portfolio daily returns
        benchmark_returns: Benchmark daily returns
        
    Returns:
        Tuple of (up_capture, down_capture) as Decimals
    """
    if len(portfolio_returns) != len(benchmark_returns):
        return None, None

    # Separate up and down market days
    up_portfolio = []
    up_benchmark = []
    down_portfolio = []
    down_benchmark = []

    for i in range(len(benchmark_returns)):
        if benchmark_returns[i] > 0:
            up_portfolio.append(portfolio_returns[i])
            up_benchmark.append(benchmark_returns[i])
        elif benchmark_returns[i] < 0:
            down_portfolio.append(portfolio_returns[i])
            down_benchmark.append(benchmark_returns[i])

    # Calculate captures
    up_capture = None
    if up_benchmark:
        sum_up_bench = sum(up_benchmark)
        if sum_up_bench != 0:
            sum_up_port = sum(up_portfolio)
            up_capture = sum_up_port / sum_up_bench

    down_capture = None
    if down_benchmark:
        sum_down_bench = sum(down_benchmark)
        if sum_down_bench != 0:
            sum_down_port = sum(down_portfolio)
            down_capture = sum_down_port / sum_down_bench

    return up_capture, down_capture


# =============================================================================
# COMBINED BENCHMARK CALCULATOR
# =============================================================================

class BenchmarkCalculator:
    """
    Calculator for benchmark comparison metrics.
    
    Unlike other calculators, this one may need to fetch external data
    for the benchmark prices.
    """

    @staticmethod
    def calculate_all(
            portfolio_returns: list[Decimal],
            benchmark_returns: list[Decimal],
            portfolio_total_return: Decimal,
            benchmark_total_return: Decimal,
            benchmark_symbol: str,
            benchmark_name: str | None = None,
            risk_free_rate: Decimal = DEFAULT_RISK_FREE_RATE,
    ) -> BenchmarkMetrics:
        """
        Calculate all benchmark comparison metrics.
        
        Args:
            portfolio_returns: Daily portfolio returns
            benchmark_returns: Daily benchmark returns (aligned by date)
            portfolio_total_return: Annualized portfolio return
            benchmark_total_return: Annualized benchmark return
            benchmark_symbol: Benchmark ticker (e.g., "SPY")
            benchmark_name: Benchmark full name
            risk_free_rate: Risk-free rate for alpha calculation
        
        Returns:
            BenchmarkMetrics with all available metrics
        """
        result = BenchmarkMetrics(
            benchmark_symbol=benchmark_symbol,
            benchmark_name=benchmark_name,
        )

        if len(portfolio_returns) != len(benchmark_returns):
            result.has_sufficient_data = False
            result.warnings.append("Portfolio and benchmark data lengths don't match")
            return result

        if len(portfolio_returns) < 10:
            result.has_sufficient_data = False
            result.warnings.append("Insufficient data: need at least 10 data points")
            return result

        # Returns
        result.portfolio_return = portfolio_total_return
        result.benchmark_return = benchmark_total_return
        result.excess_return = portfolio_total_return - benchmark_total_return

        # Beta
        result.beta = calculate_beta(portfolio_returns, benchmark_returns)

        # Alpha (requires beta)
        if result.beta is not None:
            result.alpha = calculate_alpha(
                portfolio_total_return,
                benchmark_total_return,
                result.beta,
                risk_free_rate,
            )

        # Correlation & R²
        result.correlation = calculate_correlation(portfolio_returns, benchmark_returns)

        if result.correlation is not None:
            result.r_squared = calculate_r_squared(result.correlation)

        # Tracking error & Information ratio
        result.tracking_error = calculate_tracking_error(
            portfolio_returns, benchmark_returns
        )

        if result.tracking_error is not None:
            result.information_ratio = calculate_information_ratio(
                portfolio_total_return,
                benchmark_total_return,
                result.tracking_error,
            )

        # Capture ratios
        up_cap, down_cap = calculate_capture_ratios(
            portfolio_returns, benchmark_returns
        )
        result.up_capture = up_cap
        result.down_capture = down_cap

        return result
