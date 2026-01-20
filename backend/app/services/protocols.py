# backend/app/services/protocols.py
"""
Protocol interfaces for service dependency injection.

Using typing.Protocol enables structural subtyping:
- Existing classes satisfy protocols without modification
- Test mocks work without explicit inheritance
- Clear documentation of required interfaces
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.services.fx_rate_service import FXRateResult
    from app.services.valuation.types import PortfolioValuation, PortfolioHistory


class FXRateServiceProtocol(Protocol):
    """Interface required by ValuationService and ValueCalculator."""

    def get_rate_or_none(
        self,
        db: Session,
        base_currency: str,
        quote_currency: str,
        target_date: date,
        allow_fallback: bool = True,
    ) -> FXRateResult | None:
        ...


class ValuationServiceProtocol(Protocol):
    """Interface required by AnalyticsService."""

    def get_valuation(
        self,
        db: Session,
        portfolio_id: int,
        valuation_date: date | None = None,
    ) -> PortfolioValuation:
        ...

    def get_history(
        self,
        db: Session,
        portfolio_id: int,
        start_date: date,
        end_date: date,
        interval: str = "daily",
    ) -> PortfolioHistory:
        ...
