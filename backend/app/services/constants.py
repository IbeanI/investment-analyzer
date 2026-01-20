# backend/app/services/constants.py
"""
Centralized constants for the Investment Analyzer services.

This module provides a single source of truth for all business constants
used across the application. Centralizing these values:

1. Prevents inconsistencies from duplicate definitions
2. Makes it easy to tune parameters in one place
3. Documents the meaning and units of each constant
4. Enables environment-based overrides if needed in the future

Usage:
    from app.services.constants import (
        TRADING_DAYS_PER_YEAR,
        DEFAULT_RISK_FREE_RATE,
        PRICE_FALLBACK_DAYS,
    )
"""

from decimal import Decimal


# =============================================================================
# FINANCIAL CALENDAR CONSTANTS
# =============================================================================

# Standard number of trading days in a year (excludes weekends and holidays)
# Used for annualizing volatility, Sharpe ratio, and other risk metrics
TRADING_DAYS_PER_YEAR: int = 252

# Standard number of calendar days in a year
# Used for annualizing returns (CAGR, TWR)
CALENDAR_DAYS_PER_YEAR: int = 365


# =============================================================================
# RISK-FREE RATE
# =============================================================================

# Default risk-free rate for Sharpe ratio and other risk-adjusted calculations
# Represents approximate yield on short-term government bonds
# 2% = 0.02 as a decimal
DEFAULT_RISK_FREE_RATE: Decimal = Decimal("0.02")


# =============================================================================
# PRICE & FX FALLBACK SETTINGS
# =============================================================================

# Maximum days to look back when a price is missing (weekends, holidays)
# If no price found within this window, valuation will use last available
PRICE_FALLBACK_DAYS: int = 5

# Maximum days to look back when an FX rate is missing
# FX markets close on weekends, so we need fallback for Sat/Sun valuations
FX_FALLBACK_DAYS: int = 7


# =============================================================================
# MARKET DATA SYNC SETTINGS
# =============================================================================

# Hours after which market data is considered stale and needs refresh
# 24 hours = sync once per day during market hours
DEFAULT_STALENESS_HOURS: int = 24


# =============================================================================
# ANALYTICS CACHE SETTINGS
# =============================================================================

# Time-to-live for cached analytics results in seconds
# 1 hour = 3600 seconds
# Analytics are CPU-intensive, so caching prevents redundant recalculation
CACHE_TTL_SECONDS: int = 3600


# =============================================================================
# IRR/XIRR CALCULATION SETTINGS
# =============================================================================

# Maximum iterations for Newton-Raphson method in XIRR calculation
# 100 iterations is sufficient for convergence in virtually all cases
IRR_MAX_ITERATIONS: int = 100

# Convergence tolerance for XIRR calculation
# 0.0000001 = 0.00001% precision (more than sufficient for financial reporting)
IRR_TOLERANCE: Decimal = Decimal("0.0000001")

# Initial guess for IRR iteration (10% annual return)
# Starting near typical market returns helps convergence
IRR_INITIAL_GUESS: Decimal = Decimal("0.1")


# =============================================================================
# SYNTHETIC DATA THRESHOLDS
# =============================================================================

# Warning threshold for synthetic (proxy-backcasted) data usage
# If portfolio history contains >20% synthetic prices, show warning
SYNTHETIC_WARNING_THRESHOLD: Decimal = Decimal("20")

# Critical threshold for synthetic data
# If portfolio history contains >50% synthetic prices, show critical warning
SYNTHETIC_CRITICAL_THRESHOLD: Decimal = Decimal("50")


# =============================================================================
# DEFAULT BENCHMARKS
# =============================================================================

# Default benchmark indices for performance comparison
# Maps portfolio currency to Yahoo Finance symbol
DEFAULT_BENCHMARKS: dict[str, str] = {
    "USD": "^SPX",       # S&P 500 Index
    "EUR": "IWDA.AS",    # iShares MSCI World ETF (Amsterdam)
    "GBP": "^SPX",       # Fallback to S&P 500
    "CHF": "^SPX",       # Fallback to S&P 500
    "DEFAULT": "^SPX",   # Default fallback
}


# =============================================================================
# PORTFOLIO SETTINGS DEFAULTS
# =============================================================================

# Whether proxy backcasting is enabled by default for new portfolios
# True = automatically fill historical gaps using proxy assets
DEFAULT_ENABLE_PROXY_BACKCASTING: bool = True


# =============================================================================
# CIRCUIT BREAKER SETTINGS
# =============================================================================

# Number of failures before circuit opens and blocks requests
# 5 failures = service is likely having issues
CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5

# Seconds to wait before testing if service has recovered
# 60 seconds = give service time to recover before retrying
CIRCUIT_BREAKER_RECOVERY_TIMEOUT: float = 60.0

# Maximum calls allowed in half-open state to test recovery
# 3 calls = enough to verify service is working without overwhelming it
CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS: int = 3

# Time window (seconds) for counting failures (0 = count all failures)
# 300 = 5 minutes, only count recent failures
CIRCUIT_BREAKER_FAILURE_WINDOW: float = 300.0


# =============================================================================
# MEMORY MANAGEMENT CONSTANTS
# =============================================================================

# Maximum number of days to process in a single chunk for history calculations
# Prevents memory spikes when processing large date ranges
# 365 days × 100 assets × 3 fields ≈ 4 MB per chunk (reasonable)
HISTORY_CHUNK_SIZE_DAYS: int = 365

# Threshold date range (days) above which chunked processing is enabled
# For small ranges, batch processing is more efficient
# For large ranges (>2 years), chunked processing prevents memory issues
HISTORY_CHUNK_THRESHOLD_DAYS: int = 730  # 2 years

# Maximum estimated price records before enabling chunked processing
# Based on: assets × days × ~100 bytes per record
# 100,000 records ≈ 10 MB in-memory footprint
MAX_PRICE_RECORDS_BEFORE_CHUNKING: int = 100_000


# =============================================================================
# RISK CALCULATION CONSTANTS
# =============================================================================

# Minimum drawdown depth to record in drawdown analysis
# Only record drawdowns greater than 1% to filter out noise
# -0.01 = -1% (drawdowns are negative)
DRAWDOWN_RECORDING_THRESHOLD: Decimal = Decimal("-0.01")

# Minimum portfolio equity required for valid calculations
# Prevents division by zero and filters out meaningless data points
# 1.0 = $1 or €1 minimum portfolio value
MIN_EQUITY_THRESHOLD: Decimal = Decimal("1.0")

# Minimum days required for meaningful volatility calculation
# Need at least 2 data points for standard deviation
MIN_DAYS_FOR_VOLATILITY: int = 2

# Minimum days required for meaningful drawdown analysis
MIN_DAYS_FOR_DRAWDOWN: int = 5


# =============================================================================
# DECIMAL PRECISION CONSTANTS
# =============================================================================
# Standardized precision levels for financial calculations
# Using named constants prevents typos and ensures consistency

# Currency amounts: 2 decimal places (e.g., $1234.56)
# Used for: portfolio value, cost basis, P&L amounts, cash balances
CURRENCY_PRECISION: Decimal = Decimal("0.01")

# Share quantities and FX rates: 8 decimal places
# Used for: fractional shares, average cost per share, exchange rates
# Supports crypto (BTC has 8 decimals) and high-precision FX rates
SHARE_PRECISION: Decimal = Decimal("0.00000001")

# Percentage values: 4 decimal places (e.g., 12.3456%)
# Used for: drawdown percentages, return percentages in intermediate calculations
PERCENTAGE_PRECISION: Decimal = Decimal("0.0001")

# Display percentage: 2 decimal places (e.g., 12.34%)
# Used for: final display of P&L percentages, return percentages
DISPLAY_PERCENTAGE_PRECISION: Decimal = Decimal("0.01")


# =============================================================================
# RISK CALCULATION THRESHOLDS
# =============================================================================

# Minimum sample size for Value at Risk (VaR) calculation
# Need enough data points for statistically meaningful percentile
MIN_VAR_SAMPLE_SIZE: int = 10


# =============================================================================
# UTILITY CONSTANTS
# =============================================================================

# Type-safe zero for Decimal comparisons
# Use this instead of Decimal("0") for cleaner code and avoiding typos
ZERO: Decimal = Decimal("0")
