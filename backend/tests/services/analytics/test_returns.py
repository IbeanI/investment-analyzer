# backend/tests/services/analytics/test_returns.py
"""
Unit tests for return calculations.

These tests verify the pure calculation logic WITHOUT database dependencies.
All tests use known values that can be verified by hand.

Test Coverage:
- calculate_simple_return: Basic return calculation
- calculate_twr: Time-Weighted Return (Daily Linking Method)
- calculate_cagr: Compound Annual Growth Rate
- calculate_xirr: Extended Internal Rate of Return
- annualize_return: Return annualization
- ReturnsCalculator.calculate_all: Combined calculations
"""

from datetime import date
from decimal import Decimal

import pytest

from app.services.analytics.types import CashFlow, DailyValue
from app.services.analytics.returns import (
    calculate_simple_return,
    calculate_twr,
    calculate_cagr,
    calculate_xirr,
    annualize_return,
    ReturnsCalculator,
)


# =============================================================================
# SIMPLE RETURN TESTS
# =============================================================================

class TestSimpleReturn:
    """Tests for calculate_simple_return function."""

    def test_positive_return(self):
        """Test positive return calculation."""
        result = calculate_simple_return(
            start_value=Decimal("1000"),
            end_value=Decimal("1200"),
        )
        assert result == Decimal("0.2")  # 20%

    def test_negative_return(self):
        """Test negative return calculation."""
        result = calculate_simple_return(
            start_value=Decimal("1000"),
            end_value=Decimal("800"),
        )
        assert result == Decimal("-0.2")  # -20%

    def test_zero_return(self):
        """Test zero return."""
        result = calculate_simple_return(
            start_value=Decimal("1000"),
            end_value=Decimal("1000"),
        )
        assert result == Decimal("0")

    def test_zero_start_value_returns_none(self):
        """Test that zero start value returns None."""
        result = calculate_simple_return(
            start_value=Decimal("0"),
            end_value=Decimal("1000"),
        )
        assert result is None

    def test_large_return(self):
        """Test large return (100% gain)."""
        result = calculate_simple_return(
            start_value=Decimal("500"),
            end_value=Decimal("1000"),
        )
        assert result == Decimal("1")  # 100%


# =============================================================================
# TWR TESTS (Daily Linking Method)
# =============================================================================

class TestTWR:
    """Tests for Time-Weighted Return calculation."""

    def test_simple_growth_no_cash_flow(self):
        """Test TWR with simple growth, no cash flows."""
        # €1000 grows to €1100 (10% return)
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("1000"), cash_flow=Decimal("0")),
            DailyValue(date=date(2024, 1, 2), value=Decimal("1100"), cash_flow=Decimal("0")),
        ]
        
        result = calculate_twr(daily_values)
        
        assert result is not None
        assert abs(result - Decimal("0.1")) < Decimal("0.0001")  # 10%

    def test_growth_with_deposit(self):
        """
        Test TWR removes cash flow impact.
        
        Day 1: €1000
        Day 2: €1100 (10% growth)
        Day 3: Deposit €500, value becomes €1650 (includes €50 more growth from €1100)
        
        TWR should be approximately:
        - Day 1->2: (1100 - 0) / 1000 - 1 = 10%
        - Day 2->3: (1650 - 500) / 1100 - 1 = 1150/1100 - 1 ≈ 4.55%
        - TWR = (1.1 * 1.0455) - 1 ≈ 15%
        """
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("1000"), cash_flow=Decimal("0")),
            DailyValue(date=date(2024, 1, 2), value=Decimal("1100"), cash_flow=Decimal("0")),
            DailyValue(date=date(2024, 1, 3), value=Decimal("1650"), cash_flow=Decimal("500")),
        ]
        
        result = calculate_twr(daily_values)
        
        assert result is not None
        # (1.1 * (1650-500)/1100) - 1 = (1.1 * 1.0454545) - 1 ≈ 0.15
        assert abs(result - Decimal("0.15")) < Decimal("0.01")

    def test_growth_with_withdrawal(self):
        """
        Test TWR with withdrawal.
        
        Day 1: €1000
        Day 2: €1100 (10% growth)
        Day 3: Withdraw €200, value becomes €990 (includes €90 more growth from €900)
        
        TWR should be:
        - Day 1->2: 10%
        - Day 2->3: (990 - (-200)) / 1100 - 1 = 1190/1100 - 1 ≈ 8.18%
        - TWR = (1.1 * 1.0818) - 1 ≈ 19%
        """
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("1000"), cash_flow=Decimal("0")),
            DailyValue(date=date(2024, 1, 2), value=Decimal("1100"), cash_flow=Decimal("0")),
            DailyValue(date=date(2024, 1, 3), value=Decimal("990"), cash_flow=Decimal("-200")),
        ]
        
        result = calculate_twr(daily_values)
        
        assert result is not None
        # (1.1 * (990+200)/1100) - 1 = (1.1 * 1.0818) - 1 ≈ 0.19
        assert abs(result - Decimal("0.19")) < Decimal("0.01")

    def test_user_example_vwce_vuaa(self):
        """
        Test the user's example:
        - Buy €500 VWCE + €250 VUAA = €750
        - VWCE +50% → €750 + €250 = €1000
        - Buy €250 more VUAA → €1250
        
        TWR should be 33.33% (pure investment performance)
        """
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("750"), cash_flow=Decimal("750")),
            DailyValue(date=date(2024, 1, 15), value=Decimal("1000"), cash_flow=Decimal("0")),
            DailyValue(date=date(2024, 1, 20), value=Decimal("1250"), cash_flow=Decimal("250")),
        ]
        
        result = calculate_twr(daily_values)
        
        assert result is not None
        # Day 1->15: (1000-0)/750 - 1 = 33.33%
        # Day 15->20: (1250-250)/1000 - 1 = 0%
        # TWR = 1.3333 * 1.0 - 1 = 33.33%
        assert abs(result - Decimal("0.3333")) < Decimal("0.01")

    def test_insufficient_data(self):
        """Test TWR returns None with less than 2 data points."""
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("1000")),
        ]
        
        result = calculate_twr(daily_values)
        
        assert result is None

    def test_empty_list(self):
        """Test TWR returns None with empty list."""
        result = calculate_twr([])
        assert result is None


# =============================================================================
# CAGR TESTS
# =============================================================================

class TestCAGR:
    """Tests for Compound Annual Growth Rate calculation."""

    def test_one_year_growth(self):
        """Test CAGR for exactly one year."""
        result = calculate_cagr(
            start_value=Decimal("1000"),
            end_value=Decimal("1120"),
            days=365,
        )
        
        assert result is not None
        # 12% return over 1 year = 12% CAGR
        assert abs(result - Decimal("0.12")) < Decimal("0.001")

    def test_two_year_growth(self):
        """Test CAGR for two years."""
        # €1000 → €1210 over 2 years (21% total)
        # CAGR = (1210/1000)^(1/2) - 1 = 1.1 - 1 = 10%
        result = calculate_cagr(
            start_value=Decimal("1000"),
            end_value=Decimal("1210"),
            days=730,  # 2 years
        )
        
        assert result is not None
        assert abs(result - Decimal("0.10")) < Decimal("0.01")

    def test_half_year_growth(self):
        """Test CAGR for half year annualized."""
        # €1000 → €1050 over 6 months (5% over 6 months)
        # CAGR = (1050/1000)^(365/182.5) - 1 ≈ 10.25%
        result = calculate_cagr(
            start_value=Decimal("1000"),
            end_value=Decimal("1050"),
            days=183,  # ~6 months
        )
        
        assert result is not None
        # Approximately 10.25% annualized
        assert abs(result - Decimal("0.1025")) < Decimal("0.01")

    def test_negative_return(self):
        """Test CAGR with negative return."""
        result = calculate_cagr(
            start_value=Decimal("1000"),
            end_value=Decimal("900"),
            days=365,
        )
        
        assert result is not None
        assert result < Decimal("0")
        assert abs(result - Decimal("-0.1")) < Decimal("0.001")

    def test_zero_start_value_returns_none(self):
        """Test CAGR returns None for zero start value."""
        result = calculate_cagr(
            start_value=Decimal("0"),
            end_value=Decimal("1000"),
            days=365,
        )
        assert result is None

    def test_zero_days_returns_none(self):
        """Test CAGR returns None for zero days."""
        result = calculate_cagr(
            start_value=Decimal("1000"),
            end_value=Decimal("1100"),
            days=0,
        )
        assert result is None

    def test_total_loss(self):
        """Test CAGR with total loss."""
        result = calculate_cagr(
            start_value=Decimal("1000"),
            end_value=Decimal("0"),
            days=365,
        )
        
        assert result == Decimal("-1")  # -100%


# =============================================================================
# XIRR TESTS
# =============================================================================

class TestXIRR:
    """Tests for Extended Internal Rate of Return calculation."""

    def test_simple_investment_return(self):
        """
        Test XIRR with simple investment and final value.
        
        Invest €10,000 on Jan 1, worth €11,000 on Dec 31 = 10% return
        """
        cash_flows = [
            CashFlow(date=date(2024, 1, 1), amount=Decimal("10000")),   # Investment
            CashFlow(date=date(2024, 12, 31), amount=Decimal("-11000")),  # Final value
        ]
        
        result = calculate_xirr(cash_flows)
        
        assert result is not None
        assert abs(result - Decimal("0.10")) < Decimal("0.01")

    def test_multiple_deposits(self):
        """
        Test XIRR with multiple deposits.
        
        Jan 1: Invest €10,000
        Jul 1: Add €5,000
        Dec 31: Worth €16,500
        
        XIRR should account for the timing of deposits.
        """
        cash_flows = [
            CashFlow(date=date(2024, 1, 1), amount=Decimal("10000")),
            CashFlow(date=date(2024, 7, 1), amount=Decimal("5000")),
            CashFlow(date=date(2024, 12, 31), amount=Decimal("-16500")),
        ]
        
        result = calculate_xirr(cash_flows)
        
        assert result is not None
        # XIRR accounts for timing - second deposit had less time to grow
        assert result > Decimal("0.05")  # Should be positive
        assert result < Decimal("0.15")  # But not too high

    def test_withdrawal_during_period(self):
        """
        Test XIRR with withdrawal.
        
        Jan 1: Invest €10,000
        Jul 1: Withdraw €2,000
        Dec 31: Worth €9,000
        
        Total cash in: €10,000
        Total cash out: €2,000 + €9,000 = €11,000
        Net gain: €1,000
        """
        cash_flows = [
            CashFlow(date=date(2024, 1, 1), amount=Decimal("10000")),
            CashFlow(date=date(2024, 7, 1), amount=Decimal("-2000")),  # Withdrawal
            CashFlow(date=date(2024, 12, 31), amount=Decimal("-9000")),  # Final value
        ]
        
        result = calculate_xirr(cash_flows)
        
        assert result is not None
        assert result > Decimal("0")  # Should be positive

    def test_negative_return(self):
        """
        Test XIRR with negative return.
        
        Invest €10,000, ends at €8,000 = -20% return
        """
        cash_flows = [
            CashFlow(date=date(2024, 1, 1), amount=Decimal("10000")),
            CashFlow(date=date(2024, 12, 31), amount=Decimal("-8000")),
        ]
        
        result = calculate_xirr(cash_flows)
        
        assert result is not None
        assert result < Decimal("0")
        assert abs(result - Decimal("-0.20")) < Decimal("0.01")

    def test_insufficient_cash_flows(self):
        """Test XIRR returns None with less than 2 cash flows."""
        cash_flows = [
            CashFlow(date=date(2024, 1, 1), amount=Decimal("10000")),
        ]
        
        result = calculate_xirr(cash_flows)
        
        assert result is None

    def test_no_negative_cash_flow(self):
        """Test XIRR returns None without negative cash flow (final value)."""
        cash_flows = [
            CashFlow(date=date(2024, 1, 1), amount=Decimal("10000")),
            CashFlow(date=date(2024, 12, 31), amount=Decimal("5000")),  # Both positive
        ]
        
        result = calculate_xirr(cash_flows)
        
        assert result is None


# =============================================================================
# ANNUALIZE RETURN TESTS
# =============================================================================

class TestAnnualizeReturn:
    """Tests for return annualization."""

    def test_one_year_no_change(self):
        """Test that 1-year return stays the same."""
        result = annualize_return(
            total_return=Decimal("0.10"),
            days=365,
        )
        
        assert result is not None
        assert abs(result - Decimal("0.10")) < Decimal("0.001")

    def test_half_year_annualized(self):
        """Test 6-month return annualized."""
        # 5% over 6 months → approximately 10.25% annualized
        result = annualize_return(
            total_return=Decimal("0.05"),
            days=183,
        )
        
        assert result is not None
        assert abs(result - Decimal("0.1025")) < Decimal("0.01")

    def test_two_years_annualized(self):
        """Test 2-year return annualized."""
        # 21% over 2 years → 10% annualized
        result = annualize_return(
            total_return=Decimal("0.21"),
            days=730,
        )
        
        assert result is not None
        assert abs(result - Decimal("0.10")) < Decimal("0.01")

    def test_zero_days_returns_none(self):
        """Test annualization returns None for zero days."""
        result = annualize_return(
            total_return=Decimal("0.10"),
            days=0,
        )
        
        assert result is None

    def test_negative_return_annualized(self):
        """Test negative return annualization."""
        result = annualize_return(
            total_return=Decimal("-0.10"),
            days=365,
        )
        
        assert result is not None
        assert abs(result - Decimal("-0.10")) < Decimal("0.001")


# =============================================================================
# RETURNS CALCULATOR TESTS
# =============================================================================

class TestReturnsCalculator:
    """Tests for ReturnsCalculator.calculate_all."""

    def test_calculate_all_basic(self):
        """Test calculate_all with basic data."""
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("1000"), cash_flow=Decimal("0")),
            DailyValue(date=date(2024, 12, 31), value=Decimal("1100"), cash_flow=Decimal("0")),
        ]
        
        result = ReturnsCalculator.calculate_all(daily_values)
        
        assert result.start_value == Decimal("1000")
        assert result.end_value == Decimal("1100")
        assert result.has_sufficient_data is True
        assert result.simple_return is not None
        assert result.twr is not None

    def test_calculate_all_with_cash_flows(self):
        """Test calculate_all properly handles cash flows."""
        # User's example: VWCE +50%, then buy more VUAA
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("750"), cash_flow=Decimal("750")),
            DailyValue(date=date(2024, 1, 15), value=Decimal("1000"), cash_flow=Decimal("0")),
            DailyValue(date=date(2024, 1, 20), value=Decimal("1250"), cash_flow=Decimal("250")),
        ]
        
        # Add final value as negative cash flow for XIRR
        cash_flows = [
            CashFlow(date=date(2024, 1, 1), amount=Decimal("750")),
            CashFlow(date=date(2024, 1, 20), amount=Decimal("250")),
            CashFlow(date=date(2024, 1, 20), amount=Decimal("-1250")),  # Final value
        ]
        
        result = ReturnsCalculator.calculate_all(daily_values, cash_flows)
        
        # Simple return should be cash-flow adjusted: 250/750 = 33.33%
        assert result.simple_return is not None
        assert abs(result.simple_return - Decimal("0.3333")) < Decimal("0.01")
        
        # TWR should also be ~33.33%
        assert result.twr is not None
        assert abs(result.twr - Decimal("0.3333")) < Decimal("0.01")
        
        # Total gain should be €250
        assert result.total_gain is not None
        assert abs(result.total_gain - Decimal("250")) < Decimal("1")
        
        # Deposits should be €250 (excluding first day)
        assert result.total_deposits == Decimal("250")

    def test_calculate_all_insufficient_data(self):
        """Test calculate_all with insufficient data."""
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("1000")),
        ]
        
        result = ReturnsCalculator.calculate_all(daily_values)
        
        assert result.has_sufficient_data is False
        assert len(result.warnings) > 0

    def test_calculate_all_with_xirr(self):
        """Test calculate_all includes XIRR when cash flows provided."""
        daily_values = [
            DailyValue(date=date(2024, 1, 1), value=Decimal("10000"), cash_flow=Decimal("0")),
            DailyValue(date=date(2024, 12, 31), value=Decimal("11000"), cash_flow=Decimal("0")),
        ]
        
        cash_flows = [
            CashFlow(date=date(2024, 1, 1), amount=Decimal("10000")),
            CashFlow(date=date(2024, 12, 31), amount=Decimal("-11000")),
        ]
        
        result = ReturnsCalculator.calculate_all(daily_values, cash_flows)
        
        assert result.xirr is not None
        assert result.mwr is not None  # MWR = IRR
        assert abs(result.xirr - Decimal("0.10")) < Decimal("0.01")
