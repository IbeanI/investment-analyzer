# backend/app/services/valuation/__init__.py
"""
Valuation Service Package.

This package provides portfolio valuation capabilities:
- Single date valuation (get_valuation)
- Position snapshots (get_holdings)
- Time series for charts (get_history)

Usage:
    from app.services.valuation import ValuationService

    service = ValuationService()

    # Single date valuation
    result = service.get_valuation(db, portfolio_id=1)

    # Open positions only
    holdings = service.get_holdings(db, portfolio_id=1)

    # Time series for charts
    history = service.get_history(
        db,
        portfolio_id=1,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        interval="monthly"
    )

Architecture:
    valuation/
    ├── __init__.py              # This file - package exports
    ├── types.py                 # Internal data classes
    ├── calculators.py           # Point-in-time calculators
    ├── history_calculator.py    # Time series calculator
    └── service.py               # ValuationService (orchestrator)

Data Flow:
    Transactions → HoldingsCalculator → Positions
    Positions → CostBasisCalculator → CostBasisResult
    Positions + Prices → ValueCalculator → ValueResult
    CostBasis + Value → PnLCalculators → PnLResult
    All Above → HoldingValuation → PortfolioValuation

Key Types:
    - HoldingPosition: Aggregated transaction data for one asset
    - CostBasisResult: Cost basis in local and portfolio currency
    - ValueResult: Current value with FX conversion
    - PnLResult: Unrealized + Realized P&L
    - HoldingValuation: Complete valuation for one holding
    - PortfolioValuation: Complete portfolio valuation
    - HistoryPoint: Single point in time series
    - PortfolioHistory: Full time series result
"""

# Calculators (for testing / direct usage)
from app.services.valuation.calculators import (
    HoldingsCalculator,
    CostBasisCalculator,
    ValueCalculator,
    UnrealizedPnLCalculator,
    RealizedPnLCalculator,
    CashCalculator,
)
from app.services.valuation.history_calculator import HistoryCalculator
# Main service
from app.services.valuation.service import ValuationService
# Internal types (for advanced usage / testing)
from app.services.valuation.types import (
    HoldingPosition,
    CostBasisResult,
    ValueResult,
    PnLResult,
    HoldingValuation,
    PortfolioValuation,
    CashBalance,
    HistoryPoint,
    PortfolioHistory,
)

__all__ = [
    # Main service
    "ValuationService",

    # Data types
    "HoldingPosition",
    "CostBasisResult",
    "ValueResult",
    "PnLResult",
    "HoldingValuation",
    "PortfolioValuation",
    "CashBalance",
    "HistoryPoint",
    "PortfolioHistory",

    # Calculators (for testing)
    "HoldingsCalculator",
    "CostBasisCalculator",
    "ValueCalculator",
    "UnrealizedPnLCalculator",
    "RealizedPnLCalculator",
    "CashCalculator",
    "HistoryCalculator",
]
