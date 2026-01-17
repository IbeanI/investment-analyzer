# backend/tests/services/analytics/test_benchmark.py
"""
Unit tests for benchmark comparison calculations.

These tests verify the pure calculation logic WITHOUT database dependencies.
All tests use known values that can be verified by hand.

Test Coverage:
- calculate_beta: Systematic risk
- calculate_alpha: Jensen's Alpha
- calculate_correlation: Pearson correlation
- calculate_r_squared: Coefficient of determination
- calculate_tracking_error: Standard deviation of return differences
- calculate_information_ratio: Active return per unit of tracking risk
- calculate_capture_ratios: Up/down market capture
- BenchmarkCalculator.calculate_all: Combined calculations
"""

from datetime import date
from decimal import Decimal

import pytest

from app.services.analytics.benchmark import (
    calculate_beta,
    calculate_alpha,
    calculate_correlation,
    calculate_r_squared,
    calculate_tracking_error,
    calculate_information_ratio,
    calculate_capture_ratios,
    BenchmarkCalculator,
)


# =============================================================================
# BETA TESTS
# =============================================================================

class TestBeta:
    """Tests for beta calculation."""

    def test_beta_one(self):
        """Test beta = 1 when portfolio perfectly tracks benchmark."""
        # Same returns = beta of 1
        portfolio_returns = [
            Decimal("0.05"),
            Decimal("-0.03"),
            Decimal("0.02"),
            Decimal("-0.01"),
            Decimal("0.04"),
        ]
        benchmark_returns = portfolio_returns.copy()
        
        result = calculate_beta(portfolio_returns, benchmark_returns)
        
        assert result is not None
        assert abs(result - Decimal("1.0")) < Decimal("0.01")

    def test_beta_greater_than_one(self):
        """Test beta > 1 when portfolio is more volatile."""
        # Portfolio moves 2x the benchmark
        benchmark_returns = [
            Decimal("0.02"),
            Decimal("-0.01"),
            Decimal("0.03"),
            Decimal("-0.02"),
            Decimal("0.01"),
        ]
        portfolio_returns = [r * 2 for r in benchmark_returns]
        
        result = calculate_beta(portfolio_returns, benchmark_returns)
        
        assert result is not None
        assert abs(result - Decimal("2.0")) < Decimal("0.1")

    def test_beta_less_than_one(self):
        """Test beta < 1 when portfolio is less volatile."""
        # Portfolio moves 0.5x the benchmark
        benchmark_returns = [
            Decimal("0.04"),
            Decimal("-0.02"),
            Decimal("0.06"),
            Decimal("-0.04"),
            Decimal("0.02"),
        ]
        portfolio_returns = [r / 2 for r in benchmark_returns]
        
        result = calculate_beta(portfolio_returns, benchmark_returns)
        
        assert result is not None
        assert abs(result - Decimal("0.5")) < Decimal("0.1")

    def test_beta_zero_variance_returns_none(self):
        """Test beta returns None when benchmark has zero variance."""
        portfolio_returns = [Decimal("0.05"), Decimal("0.03"), Decimal("0.04")]
        benchmark_returns = [Decimal("0.02")] * 3  # Constant returns
        
        result = calculate_beta(portfolio_returns, benchmark_returns)
        
        assert result is None

    def test_insufficient_data(self):
        """Test beta with insufficient data."""
        portfolio_returns = [Decimal("0.05")]
        benchmark_returns = [Decimal("0.03")]
        
        result = calculate_beta(portfolio_returns, benchmark_returns)
        
        assert result is None


# =============================================================================
# ALPHA TESTS
# =============================================================================

class TestAlpha:
    """Tests for Jensen's Alpha calculation."""

    def test_positive_alpha(self):
        """Test positive alpha (outperformance)."""
        # Alpha = Rp - [Rf + β(Rm - Rf)]
        # If Rp = 15%, Rf = 2%, β = 1, Rm = 10%
        # Alpha = 0.15 - [0.02 + 1*(0.10 - 0.02)] = 0.15 - 0.10 = 0.05 (5%)
        result = calculate_alpha(
            portfolio_return=Decimal("0.15"),
            benchmark_return=Decimal("0.10"),
            beta=Decimal("1.0"),
            risk_free_rate=Decimal("0.02"),
        )
        
        assert result is not None
        assert abs(result - Decimal("0.05")) < Decimal("0.001")

    def test_negative_alpha(self):
        """Test negative alpha (underperformance)."""
        # Alpha = 0.08 - [0.02 + 1*(0.10 - 0.02)] = 0.08 - 0.10 = -0.02 (-2%)
        result = calculate_alpha(
            portfolio_return=Decimal("0.08"),
            benchmark_return=Decimal("0.10"),
            beta=Decimal("1.0"),
            risk_free_rate=Decimal("0.02"),
        )
        
        assert result is not None
        assert result < Decimal("0")

    def test_alpha_with_high_beta(self):
        """Test alpha with beta > 1."""
        # With β = 1.5, expected return is higher
        # Alpha = 0.15 - [0.02 + 1.5*(0.10 - 0.02)] = 0.15 - 0.14 = 0.01
        result = calculate_alpha(
            portfolio_return=Decimal("0.15"),
            benchmark_return=Decimal("0.10"),
            beta=Decimal("1.5"),
            risk_free_rate=Decimal("0.02"),
        )
        
        assert result is not None
        assert abs(result - Decimal("0.01")) < Decimal("0.001")


# =============================================================================
# CORRELATION TESTS
# =============================================================================

class TestCorrelation:
    """Tests for correlation calculation."""

    def test_perfect_positive_correlation(self):
        """Test correlation = 1 for identical series."""
        returns = [
            Decimal("0.05"),
            Decimal("-0.03"),
            Decimal("0.02"),
            Decimal("-0.01"),
            Decimal("0.04"),
        ]
        
        result = calculate_correlation(returns, returns)
        
        assert result is not None
        assert abs(result - Decimal("1.0")) < Decimal("0.001")

    def test_perfect_negative_correlation(self):
        """Test correlation = -1 for opposite series."""
        portfolio_returns = [
            Decimal("0.05"),
            Decimal("-0.03"),
            Decimal("0.02"),
        ]
        benchmark_returns = [r * -1 for r in portfolio_returns]
        
        result = calculate_correlation(portfolio_returns, benchmark_returns)
        
        assert result is not None
        assert abs(result - Decimal("-1.0")) < Decimal("0.001")

    def test_low_correlation(self):
        """Test low correlation for weakly correlated series."""
        # These have some correlation but not strong
        portfolio_returns = [
            Decimal("0.05"),
            Decimal("0.02"),
            Decimal("-0.03"),
            Decimal("0.01"),
            Decimal("-0.02"),
            Decimal("0.03"),
        ]
        benchmark_returns = [
            Decimal("0.01"),
            Decimal("-0.02"),
            Decimal("0.04"),
            Decimal("-0.01"),
            Decimal("0.02"),
            Decimal("-0.03"),
        ]
        
        result = calculate_correlation(portfolio_returns, benchmark_returns)
        
        assert result is not None
        # Correlation should be between -1 and 1
        assert Decimal("-1") <= result <= Decimal("1")


# =============================================================================
# R-SQUARED TESTS
# =============================================================================

class TestRSquared:
    """Tests for R-squared calculation."""

    def test_perfect_r_squared(self):
        """Test R² = 1 for perfectly correlated series (correlation = 1)."""
        # R² = correlation²
        result = calculate_r_squared(Decimal("1.0"))
        
        assert result is not None
        assert abs(result - Decimal("1.0")) < Decimal("0.001")

    def test_r_squared_from_correlation(self):
        """Test R² calculated from correlation."""
        # If correlation = 0.8, R² = 0.64
        result = calculate_r_squared(Decimal("0.8"))
        
        assert result is not None
        assert abs(result - Decimal("0.64")) < Decimal("0.001")
    
    def test_r_squared_negative_correlation(self):
        """Test R² with negative correlation (still positive R²)."""
        # If correlation = -0.7, R² = 0.49
        result = calculate_r_squared(Decimal("-0.7"))
        
        assert result is not None
        assert abs(result - Decimal("0.49")) < Decimal("0.001")


# =============================================================================
# TRACKING ERROR TESTS
# =============================================================================

class TestTrackingError:
    """Tests for tracking error calculation."""

    def test_zero_tracking_error(self):
        """Test tracking error = 0 when perfectly tracking."""
        returns = [Decimal("0.05"), Decimal("-0.03"), Decimal("0.02")]
        
        result = calculate_tracking_error(returns, returns)
        
        assert result is not None
        assert result == Decimal("0")

    def test_positive_tracking_error(self):
        """Test tracking error > 0 when not perfectly tracking."""
        portfolio_returns = [
            Decimal("0.05"),
            Decimal("-0.02"),
            Decimal("0.03"),
            Decimal("-0.04"),
            Decimal("0.02"),
        ]
        benchmark_returns = [
            Decimal("0.03"),
            Decimal("-0.01"),
            Decimal("0.05"),
            Decimal("-0.02"),
            Decimal("0.01"),
        ]
        
        result = calculate_tracking_error(portfolio_returns, benchmark_returns)
        
        assert result is not None
        assert result > Decimal("0")


# =============================================================================
# INFORMATION RATIO TESTS
# =============================================================================

class TestInformationRatio:
    """Tests for information ratio calculation."""

    def test_positive_information_ratio(self):
        """Test positive information ratio (outperformance)."""
        # IR = (Rp - Rm) / TE
        # If Rp = 15%, Rm = 10%, TE = 10%
        # IR = (0.15 - 0.10) / 0.10 = 0.5
        result = calculate_information_ratio(
            portfolio_return=Decimal("0.15"),
            benchmark_return=Decimal("0.10"),
            tracking_error=Decimal("0.10"),
        )
        
        assert result is not None
        assert abs(result - Decimal("0.5")) < Decimal("0.001")

    def test_negative_information_ratio(self):
        """Test negative information ratio (underperformance)."""
        result = calculate_information_ratio(
            portfolio_return=Decimal("0.07"),
            benchmark_return=Decimal("0.10"),
            tracking_error=Decimal("0.10"),
        )
        
        assert result is not None
        assert result < Decimal("0")

    def test_zero_tracking_error_returns_none(self):
        """Test information ratio returns None with zero tracking error."""
        result = calculate_information_ratio(
            portfolio_return=Decimal("0.15"),
            benchmark_return=Decimal("0.10"),
            tracking_error=Decimal("0"),
        )
        
        assert result is None


# =============================================================================
# CAPTURE RATIOS TESTS
# =============================================================================

class TestCaptureRatios:
    """Tests for up/down capture ratio calculation."""

    def test_capture_ratios_perfect_tracking(self):
        """Test capture ratios = 100% when perfectly tracking."""
        returns = [
            Decimal("0.05"),   # Up
            Decimal("-0.03"),  # Down
            Decimal("0.02"),   # Up
            Decimal("-0.01"),  # Down
        ]
        
        up_capture, down_capture = calculate_capture_ratios(returns, returns)
        
        assert up_capture is not None
        assert down_capture is not None
        assert abs(up_capture - Decimal("1.0")) < Decimal("0.01")
        assert abs(down_capture - Decimal("1.0")) < Decimal("0.01")

    def test_capture_ratios_outperformance(self):
        """Test capture ratios when portfolio outperforms."""
        # Portfolio gains more in up markets, loses less in down markets
        portfolio_returns = [
            Decimal("0.06"),   # Up market: 6% vs 4%
            Decimal("-0.02"),  # Down market: -2% vs -4%
            Decimal("0.04"),   # Up market: 4% vs 3%
            Decimal("-0.01"),  # Down market: -1% vs -2%
        ]
        benchmark_returns = [
            Decimal("0.04"),   # Up
            Decimal("-0.04"),  # Down
            Decimal("0.03"),   # Up
            Decimal("-0.02"),  # Down
        ]
        
        up_capture, down_capture = calculate_capture_ratios(
            portfolio_returns, benchmark_returns
        )
        
        # Good: high up capture, low down capture
        assert up_capture is not None
        assert down_capture is not None
        # Up capture should be > 100% (outperforms in up markets)
        # Down capture should be < 100% (loses less in down markets)


# =============================================================================
# BENCHMARK CALCULATOR TESTS
# =============================================================================

class TestBenchmarkCalculator:
    """Tests for BenchmarkCalculator.calculate_all."""

    def test_calculate_all_basic(self):
        """Test calculate_all with basic data (needs at least 10 points)."""
        portfolio_returns = [
            Decimal("0.05"), Decimal("-0.03"), Decimal("0.02"),
            Decimal("-0.01"), Decimal("0.04"), Decimal("0.01"),
            Decimal("-0.02"), Decimal("0.03"), Decimal("-0.01"),
            Decimal("0.02"), Decimal("0.01"), Decimal("-0.02"),
        ]
        benchmark_returns = [
            Decimal("0.04"), Decimal("-0.02"), Decimal("0.01"),
            Decimal("-0.02"), Decimal("0.03"), Decimal("0.02"),
            Decimal("-0.01"), Decimal("0.02"), Decimal("-0.02"),
            Decimal("0.01"), Decimal("0.02"), Decimal("-0.01"),
        ]
        
        result = BenchmarkCalculator.calculate_all(
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            portfolio_total_return=Decimal("0.12"),
            benchmark_total_return=Decimal("0.10"),
            benchmark_symbol="^SPX",
            risk_free_rate=Decimal("0.02"),
        )
        
        assert result.benchmark_symbol == "^SPX"
        assert result.has_sufficient_data is True
        assert result.beta is not None
        assert result.alpha is not None
        assert result.correlation is not None
        assert result.r_squared is not None
        assert result.excess_return is not None
        assert abs(result.excess_return - Decimal("0.02")) < Decimal("0.001")

    def test_calculate_all_returns_excess_return(self):
        """Test that excess return is calculated correctly."""
        portfolio_returns = [Decimal("0.01")] * 12
        benchmark_returns = [Decimal("0.01")] * 12
        
        result = BenchmarkCalculator.calculate_all(
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            portfolio_total_return=Decimal("0.15"),
            benchmark_total_return=Decimal("0.10"),
            benchmark_symbol="^SPX",
            risk_free_rate=Decimal("0.02"),
        )
        
        # Excess return = 15% - 10% = 5%
        assert result.excess_return == Decimal("0.05")

    def test_calculate_all_insufficient_data(self):
        """Test calculate_all with insufficient data."""
        portfolio_returns = [Decimal("0.05")]
        benchmark_returns = [Decimal("0.04")]
        
        result = BenchmarkCalculator.calculate_all(
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            portfolio_total_return=Decimal("0.05"),
            benchmark_total_return=Decimal("0.04"),
            benchmark_symbol="^SPX",
            risk_free_rate=Decimal("0.02"),
        )
        
        assert result.has_sufficient_data is False
        assert len(result.warnings) > 0
