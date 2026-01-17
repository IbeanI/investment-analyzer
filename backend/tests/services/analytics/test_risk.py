# backend/tests/services/analytics/test_risk.py
"""
Unit tests for risk calculations.

These tests verify the pure calculation logic WITHOUT database dependencies.
All tests use known values that can be verified by hand.

Test Coverage:
- calculate_volatility: Standard deviation of returns
- calculate_sharpe_ratio: Risk-adjusted return
- calculate_sortino_ratio: Downside risk-adjusted return
- calculate_drawdowns: Peak-to-trough analysis
- calculate_var: Value at Risk
- calculate_cvar: Conditional VaR (Expected Shortfall)
- RiskCalculator.calculate_all: Combined calculations
"""

from datetime import date
from decimal import Decimal

import pytest

from app.services.analytics.types import DailyValue, DrawdownPeriod
from app.services.analytics.risk import (
    calculate_daily_returns,
    calculate_volatility,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_drawdowns,
    calculate_var,
    calculate_cvar,
    calculate_win_statistics,
    RiskCalculator,
    TRADING_DAYS_PER_YEAR,
)


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================

class TestDailyReturns:
    """Tests for calculate_daily_returns function."""

    def test_simple_returns(self):
        """Test daily returns calculation without cash flows."""
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("100")),
            DailyValue(date=date(2024, 1, 2), value=Decimal("105")),  # +5%
            DailyValue(date=date(2024, 1, 3), value=Decimal("103")),  # -1.9%
        ]
        
        returns = calculate_daily_returns(daily_values)
        
        assert len(returns) == 2
        assert abs(returns[0] - Decimal("0.05")) < Decimal("0.001")  # 5%
        # (103-0)/105 - 1 = -1.9%
        assert returns[1] < Decimal("0")

    def test_returns_with_cash_flow(self):
        """Test daily returns properly handle cash flows (Daily Linking Method)."""
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("100"), cash_flow=Decimal("0")),
            DailyValue(date=date(2024, 1, 2), value=Decimal("160"), cash_flow=Decimal("50")),
            # Day 2: (160 - 50) / 100 - 1 = 10%
        ]
        
        returns = calculate_daily_returns(daily_values)
        
        assert len(returns) == 1
        assert abs(returns[0] - Decimal("0.10")) < Decimal("0.001")

    def test_insufficient_data(self):
        """Test returns with insufficient data."""
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("100")),
        ]
        
        returns = calculate_daily_returns(daily_values)
        
        assert returns == []


# =============================================================================
# VOLATILITY TESTS
# =============================================================================

class TestVolatility:
    """Tests for volatility calculation."""

    def test_zero_volatility(self):
        """Test volatility with constant returns."""
        # All same return = 0 volatility
        returns = [Decimal("0.01")] * 10
        
        result = calculate_volatility(returns)
        
        assert result is not None
        assert result == Decimal("0")

    def test_positive_volatility(self):
        """Test volatility with varying returns."""
        # Returns: +5%, -3%, +2%, -1%, +4%
        returns = [
            Decimal("0.05"),
            Decimal("-0.03"),
            Decimal("0.02"),
            Decimal("-0.01"),
            Decimal("0.04"),
        ]
        
        result = calculate_volatility(returns)
        
        assert result is not None
        assert result > Decimal("0")

    def test_annualized_volatility(self):
        """Test that annualized volatility is daily * sqrt(252)."""
        returns = [
            Decimal("0.05"),
            Decimal("-0.03"),
            Decimal("0.02"),
            Decimal("-0.01"),
            Decimal("0.04"),
        ]
        
        daily_vol = calculate_volatility(returns, annualize=False)
        annual_vol = calculate_volatility(returns, annualize=True)
        
        assert daily_vol is not None
        assert annual_vol is not None
        
        # Annual = Daily * sqrt(252)
        import math
        expected_annual = daily_vol * Decimal(str(math.sqrt(TRADING_DAYS_PER_YEAR)))
        assert abs(annual_vol - expected_annual) < Decimal("0.0001")

    def test_insufficient_data(self):
        """Test volatility with insufficient data."""
        returns = [Decimal("0.05")]  # Only 1 return
        
        result = calculate_volatility(returns)
        
        assert result is None


# =============================================================================
# SHARPE RATIO TESTS
# =============================================================================

class TestSharpeRatio:
    """Tests for Sharpe ratio calculation."""

    def test_positive_sharpe(self):
        """Test positive Sharpe ratio."""
        result = calculate_sharpe_ratio(
            total_return=Decimal("0.12"),  # 12%
            volatility=Decimal("0.20"),  # 20%
            risk_free_rate=Decimal("0.02"),  # 2%
        )
        
        assert result is not None
        # (0.12 - 0.02) / 0.20 = 0.50
        assert abs(result - Decimal("0.50")) < Decimal("0.001")

    def test_negative_sharpe(self):
        """Test negative Sharpe ratio (return below risk-free)."""
        result = calculate_sharpe_ratio(
            total_return=Decimal("0.01"),  # 1%
            volatility=Decimal("0.20"),  # 20%
            risk_free_rate=Decimal("0.02"),  # 2%
        )
        
        assert result is not None
        # (0.01 - 0.02) / 0.20 = -0.05
        assert result < Decimal("0")

    def test_zero_volatility_returns_none(self):
        """Test Sharpe returns None with zero volatility."""
        result = calculate_sharpe_ratio(
            total_return=Decimal("0.12"),
            volatility=Decimal("0"),
            risk_free_rate=Decimal("0.02"),
        )
        
        assert result is None


# =============================================================================
# SORTINO RATIO TESTS
# =============================================================================

class TestSortinoRatio:
    """Tests for Sortino ratio calculation."""

    def test_positive_sortino(self):
        """Test positive Sortino ratio."""
        result = calculate_sortino_ratio(
            total_return=Decimal("0.12"),  # 12%
            downside_deviation=Decimal("0.10"),  # 10%
            risk_free_rate=Decimal("0.02"),  # 2%
        )
        
        assert result is not None
        # (0.12 - 0.02) / 0.10 = 1.0
        assert abs(result - Decimal("1.0")) < Decimal("0.001")

    def test_zero_downside_deviation_returns_none(self):
        """Test Sortino returns None with zero downside deviation."""
        result = calculate_sortino_ratio(
            total_return=Decimal("0.12"),
            downside_deviation=Decimal("0"),
            risk_free_rate=Decimal("0.02"),
        )
        
        assert result is None


# =============================================================================
# DRAWDOWN TESTS
# =============================================================================

class TestDrawdowns:
    """Tests for drawdown calculation."""

    def test_no_drawdown(self):
        """Test with monotonically increasing values."""
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("100")),
            DailyValue(date=date(2024, 1, 2), value=Decimal("105")),
            DailyValue(date=date(2024, 1, 3), value=Decimal("110")),
        ]
        
        max_dd, periods = calculate_drawdowns(daily_values)
        
        assert max_dd == Decimal("0")  # No drawdown
        assert len(periods) == 0

    def test_single_drawdown(self):
        """Test with a single drawdown that recovers."""
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("100")),  # Peak
            DailyValue(date=date(2024, 1, 2), value=Decimal("90")),   # -10%
            DailyValue(date=date(2024, 1, 3), value=Decimal("85")),   # Trough (-15%)
            DailyValue(date=date(2024, 1, 4), value=Decimal("95")),   # Recovery
            DailyValue(date=date(2024, 1, 5), value=Decimal("105")),  # New peak
        ]
        
        max_dd, periods = calculate_drawdowns(daily_values)
        
        assert max_dd is not None
        assert max_dd < Decimal("0")  # Negative
        assert abs(max_dd - Decimal("-0.15")) < Decimal("0.01")  # -15%
        assert len(periods) >= 1

    def test_ongoing_drawdown(self):
        """Test with drawdown that hasn't recovered."""
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("100")),  # Peak
            DailyValue(date=date(2024, 1, 2), value=Decimal("90")),   # -10%
            DailyValue(date=date(2024, 1, 3), value=Decimal("85")),   # Still down
        ]
        
        max_dd, periods = calculate_drawdowns(daily_values)
        
        assert max_dd is not None
        assert max_dd < Decimal("0")
        # Ongoing drawdown has end_date = None
        if periods:
            assert any(p.end_date is None for p in periods)

    def test_multiple_drawdowns(self):
        """Test with multiple drawdowns."""
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("100")),
            DailyValue(date=date(2024, 1, 2), value=Decimal("95")),   # DD 1
            DailyValue(date=date(2024, 1, 3), value=Decimal("105")),  # Recovery + new peak
            DailyValue(date=date(2024, 1, 4), value=Decimal("90")),   # DD 2 (-14.3%)
            DailyValue(date=date(2024, 1, 5), value=Decimal("110")),  # Recovery
        ]
        
        max_dd, periods = calculate_drawdowns(daily_values)
        
        assert max_dd is not None
        assert max_dd < Decimal("0")


# =============================================================================
# VALUE AT RISK TESTS
# =============================================================================

class TestVaR:
    """Tests for Value at Risk calculation."""

    def test_var_calculation(self):
        """Test VaR at 95% confidence."""
        # Create 20 returns, mostly positive with some negative
        returns = [Decimal("0.01")] * 15 + [
            Decimal("-0.02"),
            Decimal("-0.03"),
            Decimal("-0.04"),
            Decimal("-0.05"),
            Decimal("-0.06"),
        ]
        
        result = calculate_var(returns, confidence_level=Decimal("0.95"))
        
        assert result is not None
        assert result < Decimal("0")  # VaR is typically negative (loss)

    def test_var_all_positive(self):
        """Test VaR with all positive returns."""
        returns = [Decimal("0.01")] * 20
        
        result = calculate_var(returns, confidence_level=Decimal("0.95"))
        
        assert result is not None
        # Even with all positive, the 5th percentile is still positive
        assert result > Decimal("0")

    def test_insufficient_data(self):
        """Test VaR with insufficient data (needs at least 10)."""
        returns = [Decimal("0.01")] * 5
        
        result = calculate_var(returns)
        
        assert result is None


# =============================================================================
# CONDITIONAL VAR TESTS
# =============================================================================

class TestCVaR:
    """Tests for Conditional VaR (Expected Shortfall) calculation."""

    def test_cvar_calculation(self):
        """Test CVaR is more severe than VaR."""
        returns = [Decimal("0.01")] * 15 + [
            Decimal("-0.02"),
            Decimal("-0.03"),
            Decimal("-0.04"),
            Decimal("-0.05"),
            Decimal("-0.06"),
        ]
        
        var = calculate_var(returns, confidence_level=Decimal("0.95"))
        cvar = calculate_cvar(returns, confidence_level=Decimal("0.95"))
        
        assert var is not None
        assert cvar is not None
        # CVaR should be more negative (worse) than VaR
        assert cvar <= var


# =============================================================================
# WIN STATISTICS TESTS
# =============================================================================

class TestWinStatistics:
    """Tests for win rate and best/worst day calculation."""

    def test_win_statistics(self):
        """Test win statistics calculation."""
        returns = [
            Decimal("0.05"),   # Win
            Decimal("-0.03"),  # Loss
            Decimal("0.02"),   # Win
            Decimal("-0.01"),  # Loss
            Decimal("0.04"),   # Win
        ]
        
        # Returns: (positive_days, negative_days, win_rate, best_day, best_date, worst_day, worst_date)
        pos_days, neg_days, win_rate, best, best_date, worst, worst_date = calculate_win_statistics(returns)
        
        assert pos_days == 3
        assert neg_days == 2
        assert win_rate == Decimal("0.6")  # 60%
        assert best == Decimal("0.05")
        assert worst == Decimal("-0.03")

    def test_all_winning_days(self):
        """Test with all positive returns."""
        returns = [Decimal("0.01"), Decimal("0.02"), Decimal("0.03")]
        
        pos_days, neg_days, win_rate, best, best_date, worst, worst_date = calculate_win_statistics(returns)
        
        assert win_rate == Decimal("1")  # 100%

    def test_all_losing_days(self):
        """Test with all negative returns."""
        returns = [Decimal("-0.01"), Decimal("-0.02"), Decimal("-0.03")]
        
        pos_days, neg_days, win_rate, best, best_date, worst, worst_date = calculate_win_statistics(returns)
        
        assert win_rate == Decimal("0")  # 0%


# =============================================================================
# RISK CALCULATOR TESTS
# =============================================================================

class TestRiskCalculator:
    """Tests for RiskCalculator.calculate_all."""

    def test_calculate_all_basic(self):
        """Test calculate_all with basic data."""
        daily_values = [
            DailyValue(date=date(2024, 1, i), value=Decimal(str(100 + i)))
            for i in range(1, 31)  # 30 days of gradual growth
        ]
        
        result = RiskCalculator.calculate_all(
            daily_values=daily_values,
            total_return_annualized=Decimal("0.12"),
            cagr=Decimal("0.11"),
            risk_free_rate=Decimal("0.02"),
        )
        
        assert result.has_sufficient_data is True
        assert result.volatility_daily is not None
        assert result.volatility_annualized is not None
        assert result.sharpe_ratio is not None
        assert result.positive_days > 0

    def test_calculate_all_with_drawdown(self):
        """Test calculate_all captures drawdown metrics."""
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("100")),
            DailyValue(date=date(2024, 1, 2), value=Decimal("105")),
            DailyValue(date=date(2024, 1, 3), value=Decimal("95")),   # Drawdown
            DailyValue(date=date(2024, 1, 4), value=Decimal("90")),   # Worse
            DailyValue(date=date(2024, 1, 5), value=Decimal("100")),  # Recovery
            DailyValue(date=date(2024, 1, 6), value=Decimal("110")),  # New high
        ]
        
        result = RiskCalculator.calculate_all(
            daily_values=daily_values,
            total_return_annualized=Decimal("0.10"),
            cagr=Decimal("0.10"),
            risk_free_rate=Decimal("0.02"),
        )
        
        assert result.max_drawdown is not None
        assert result.max_drawdown < Decimal("0")

    def test_calculate_all_insufficient_data(self):
        """Test calculate_all with insufficient data."""
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("100")),
        ]
        
        result = RiskCalculator.calculate_all(
            daily_values=daily_values,
            total_return_annualized=None,
            cagr=None,
            risk_free_rate=Decimal("0.02"),
        )
        
        assert result.has_sufficient_data is False
        assert len(result.warnings) > 0
