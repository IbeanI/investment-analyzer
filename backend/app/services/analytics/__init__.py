# backend/app/services/analytics/__init__.py
"""
Analytics Service Package.

This package provides portfolio analytics capabilities:
- Performance metrics (TWR, IRR, CAGR, Simple Return)
- Risk metrics (Volatility, Sharpe, Sortino, Max Drawdown)
- Benchmark comparison (Beta, Alpha, Correlation)

Architecture:
    analytics/
    ├── __init__.py              # This file - package exports
    ├── types.py                 # Data classes for results
    ├── returns.py               # Return calculations (TWR, IRR, CAGR)
    ├── risk.py                  # Risk calculations (Sharpe, Drawdown)
    ├── benchmark.py             # Benchmark comparison (Beta, Alpha)
    └── service.py               # AnalyticsService (orchestrator)

Usage:
    from app.services.analytics import AnalyticsService

    service = AnalyticsService()

    # Get all analytics
    result = service.get_analytics(
        db=db,
        portfolio_id=1,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        benchmark_symbol="SPY",
    )

    # Access metrics
    print(f"TWR: {result.performance.twr}")
    print(f"Sharpe: {result.risk.sharpe_ratio}")
    print(f"Beta: {result.benchmark.beta}")

    # Or get individual metric sets
    performance = service.get_performance(db, portfolio_id=1, start_date, end_date)
    risk = service.get_risk(db, portfolio_id=1, start_date, end_date)
    benchmark = service.get_benchmark(db, portfolio_id=1, start_date, end_date, "SPY")

Data Flow:
    ValuationService.get_history()
        ↓
    PortfolioHistory (daily values)
        ↓
    ┌─────────────────────────────────────────┐
    │           AnalyticsService              │
    │  ┌─────────────┐  ┌─────────────────┐   │
    │  │ Returns     │  │ Risk            │   │
    │  │ Calculator  │  │ Calculator      │   │
    │  │ • TWR       │  │ • Volatility    │   │
    │  │ • IRR/XIRR  │  │ • Sharpe        │   │
    │  │ • CAGR      │  │ • Drawdown      │   │
    │  └─────────────┘  └─────────────────┘   │
    │                                         │
    │  ┌───────────────────────────────────┐  │
    │  │ Benchmark Calculator              │  │
    │  │ • Beta  • Alpha  • Correlation    │  │
    │  └───────────────────────────────────┘  │
    └─────────────────────────────────────────┘
        ↓
    AnalyticsResult
"""

from app.services.analytics.benchmark import (
    BenchmarkCalculator,
    calculate_beta,
    calculate_alpha,
    calculate_correlation,
    calculate_tracking_error,
    calculate_information_ratio,
)
# Calculators (for testing / direct usage)
from app.services.analytics.returns import (
    ReturnsCalculator,
    calculate_simple_return,
    calculate_twr,
    calculate_cagr,
    calculate_xirr,
    annualize_return,
)
from app.services.analytics.risk import (
    RiskCalculator,
    calculate_volatility,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_drawdowns,
    calculate_var,
)
# Main service
from app.services.analytics.service import (
    AnalyticsService,
    AnalyticsCache,
    BenchmarkNotSyncedError,
    DEFAULT_BENCHMARKS,
)
# Types
from app.services.analytics.types import (
    # Input types
    CashFlow,
    DailyValue,
    # Investment period tracking (GIPS)
    InvestmentPeriod,
    MeasurementPeriodInfo,
    AnalysisScope,
    # Result types
    PerformanceMetrics,
    RiskMetrics,
    BenchmarkMetrics,
    DrawdownPeriod,
    AnalyticsPeriod,
    AnalyticsResult,
)

__all__ = [
    # Main service
    "AnalyticsService",
    "AnalyticsCache",
    "BenchmarkNotSyncedError",
    "DEFAULT_BENCHMARKS",

    # Input types
    "CashFlow",
    "DailyValue",

    # Investment period tracking (GIPS)
    "InvestmentPeriod",
    "MeasurementPeriodInfo",
    "AnalysisScope",

    # Result types
    "PerformanceMetrics",
    "RiskMetrics",
    "BenchmarkMetrics",
    "DrawdownPeriod",
    "AnalyticsPeriod",
    "AnalyticsResult",

    # Calculators
    "ReturnsCalculator",
    "RiskCalculator",
    "BenchmarkCalculator",

    # Individual functions (for testing)
    "calculate_simple_return",
    "calculate_twr",
    "calculate_cagr",
    "calculate_xirr",
    "annualize_return",
    "calculate_volatility",
    "calculate_sharpe_ratio",
    "calculate_sortino_ratio",
    "calculate_drawdowns",
    "calculate_var",
    "calculate_beta",
    "calculate_alpha",
    "calculate_correlation",
    "calculate_tracking_error",
    "calculate_information_ratio",
]
