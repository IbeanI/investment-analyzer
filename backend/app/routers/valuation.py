# backend/app/routers/valuation.py
"""
Portfolio valuation endpoints.

Provides portfolio valuation, holdings breakdown, and historical performance:
- GET /portfolios/{id}/valuation - Full valuation with holdings + cash
- GET /portfolios/{id}/holdings - Lightweight positions only (future)
- GET /portfolios/{id}/valuation/history - Time series for charts

Note: These endpoints are nested under /portfolios/{id} because valuations
are always in the context of a specific portfolio.
"""

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Portfolio, User
from app.services.constants import MAX_HISTORY_DAYS
from app.dependencies import get_portfolio_with_owner_check
from app.schemas.valuation import (
    CostBasisDetail,
    CurrentValueDetail,
    PnLDetail,
    HoldingValuation,
    CashBalanceDetail,
    PortfolioValuationSummary,
    PortfolioValuationResponse,
    ValuationHistoryPoint,
    PortfolioHistoryResponse,
)
from app.services.valuation import ValuationService
from app.dependencies import get_valuation_service

# =============================================================================
# ROUTER SETUP
# =============================================================================

router = APIRouter(
    prefix="/portfolios",
    tags=["Valuation"],
)


# =============================================================================
# MAPPER FUNCTIONS (Internal Types -> Pydantic Schemas)
# =============================================================================

def _map_cost_basis(cost_basis) -> CostBasisDetail:
    """Map internal CostBasisResult to Pydantic schema."""
    return CostBasisDetail(
        local_currency=cost_basis.local_currency,
        local_amount=cost_basis.local_amount,
        portfolio_currency=cost_basis.portfolio_currency,
        portfolio_amount=cost_basis.portfolio_amount,
        avg_cost_per_share=cost_basis.avg_cost_per_share,
    )


def _map_current_value(value) -> CurrentValueDetail:
    """Map internal ValueResult to Pydantic schema."""
    return CurrentValueDetail(
        price_per_share=value.price,
        price_date=value.price_date,
        local_currency=value.local_currency,
        local_amount=value.local_amount,
        portfolio_currency=value.portfolio_currency,
        portfolio_amount=value.portfolio_amount,
        fx_rate_used=value.fx_rate_used,
    )


def _map_pnl(pnl) -> PnLDetail:
    """Map internal PnLResult to Pydantic schema."""
    return PnLDetail(
        unrealized_amount=pnl.unrealized_amount,
        unrealized_percentage=pnl.unrealized_percentage,
        realized_amount=pnl.realized_amount,
        realized_percentage=pnl.realized_percentage,
        total_amount=pnl.total_amount,
        total_percentage=pnl.total_percentage,
    )


def _map_holding(holding) -> HoldingValuation:
    """Map internal HoldingValuation to Pydantic schema."""
    return HoldingValuation(
        asset_id=holding.asset_id,
        ticker=holding.ticker,
        exchange=holding.exchange,
        asset_name=holding.asset_name,
        asset_class=holding.asset_class,
        asset_currency=holding.asset_currency,
        quantity=holding.quantity,
        cost_basis=_map_cost_basis(holding.cost_basis),
        current_value=_map_current_value(holding.current_value),
        pnl=_map_pnl(holding.pnl),
        warnings=holding.warnings,
        has_complete_data=holding.has_complete_data,
        price_is_synthetic=holding.price_is_synthetic,
        price_source=holding.price_source,
        proxy_ticker=holding.proxy_ticker,
        proxy_exchange=holding.proxy_exchange,
    )


def _map_cash_balance(cash) -> CashBalanceDetail:
    """Map internal CashBalance to Pydantic schema."""
    return CashBalanceDetail(
        currency=cash.currency,
        amount=cash.amount,
        amount_portfolio=cash.amount_portfolio,
        fx_rate_used=cash.fx_rate_used,
    )


def _map_history_point(point) -> ValuationHistoryPoint:
    """Map internal HistoryPoint to Pydantic schema."""
    return ValuationHistoryPoint(
        date=point.date,
        value=point.value,
        cash=point.cash,
        equity=point.equity,
        cost_basis=point.cost_basis,
        net_invested=point.net_invested,
        unrealized_pnl=point.unrealized_pnl,
        realized_pnl=point.realized_pnl,
        total_pnl=point.total_pnl,
        pnl_percentage=point.pnl_percentage,
        has_complete_data=point.has_complete_data,
    )


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get(
    "/{portfolio_id}/valuation",
    response_model=PortfolioValuationResponse,
    summary="Get portfolio valuation",
    response_description="Complete portfolio valuation with holdings breakdown",
)
def get_portfolio_valuation(
        portfolio: Portfolio = Depends(get_portfolio_with_owner_check),
        valuation_date: date | None = Query(
            default=None,
            description="Valuation date (default: today)",
            alias="date"
        ),
        db: Session = Depends(get_db),
        service: ValuationService = Depends(get_valuation_service),
) -> PortfolioValuationResponse:
    """
    Get complete portfolio valuation for a specific date.

    Returns:
    - **summary**: Total cost basis, value, P&L
    - **holdings**: Individual position valuations
    - **cash_balances**: Cash by currency (if portfolio tracks cash)

    The valuation includes:
    - Cost basis using weighted average method
    - Current value with FX conversion
    - Unrealized P&L (paper gains/losses)
    - Realized P&L (from closed positions)

    **Note:** If price or FX data is missing for any holding,
    `has_complete_data` will be `false` and affected totals will be `null`.

    Raises **403** if you don't own the portfolio.
    """
    portfolio_id = portfolio.id

    # Get valuation from service
    # Domain exceptions (PortfolioNotFoundError) propagate to global handlers
    valuation = service.get_valuation(
        db=db,
        portfolio_id=portfolio_id,
        valuation_date=valuation_date,
    )

    # Calculate day change by comparing to yesterday
    day_change: Decimal | None = None
    day_change_percentage: Decimal | None = None

    if valuation.total_equity is not None:
        # Use actual valuation date (which defaults to today if not specified)
        actual_date = valuation.valuation_date
        yesterday = actual_date - timedelta(days=1)
        prev_valuation = service.get_valuation(
            db=db,
            portfolio_id=portfolio_id,
            valuation_date=yesterday,
        )

        if prev_valuation.total_equity is not None:
            day_change = valuation.total_equity - prev_valuation.total_equity
            if prev_valuation.total_equity != Decimal("0"):
                day_change_percentage = day_change / prev_valuation.total_equity
            else:
                day_change_percentage = Decimal("0")
        else:
            # No previous data found - return 0
            day_change = Decimal("0")
            day_change_percentage = Decimal("0")

    # Map to response schema
    return PortfolioValuationResponse(
        portfolio_id=valuation.portfolio_id,
        portfolio_name=valuation.portfolio_name,
        portfolio_currency=valuation.portfolio_currency,
        valuation_date=valuation.valuation_date,
        summary=PortfolioValuationSummary(
            total_cost_basis=valuation.total_cost_basis,
            total_net_invested=valuation.total_net_invested,
            total_value=valuation.total_value,
            total_cash=valuation.total_cash,
            total_equity=valuation.total_equity,
            total_unrealized_pnl=valuation.total_unrealized_pnl,
            total_realized_pnl=valuation.total_realized_pnl,
            total_pnl=valuation.total_pnl,
            total_pnl_percentage=valuation.total_pnl_percentage,
            day_change=day_change,
            day_change_percentage=day_change_percentage,
        ),
        holdings=[_map_holding(h) for h in valuation.holdings],
        tracks_cash=valuation.tracks_cash,
        cash_balances=[_map_cash_balance(c) for c in valuation.cash_balances],
        has_complete_data=valuation.has_complete_data,
        warnings=valuation.warnings,
        has_synthetic_data=valuation.has_synthetic_data,
        synthetic_holdings_count=valuation.synthetic_holdings_count,
    )


@router.get(
    "/{portfolio_id}/valuation/history",
    response_model=PortfolioHistoryResponse,
    summary="Get portfolio valuation history",
    response_description="Time series of portfolio valuations"
)
def get_portfolio_valuation_history(
        portfolio: Portfolio = Depends(get_portfolio_with_owner_check),
        from_date: date = Query(
            ...,
            description="Start date for history"
        ),
        to_date: date = Query(
            ...,
            description="End date for history"
        ),
        interval: str = Query(
            default="daily",
            pattern=r"^(daily|weekly|monthly)$",
            description="Data interval: daily, weekly, monthly"
        ),
        db: Session = Depends(get_db),
        service: ValuationService = Depends(get_valuation_service),
) -> PortfolioHistoryResponse:
    """
    Get portfolio valuation history for charting.

    Returns time series data with:
    - Portfolio value over time
    - Cost basis progression
    - P&L evolution (unrealized + realized)

    **Intervals:**
    - `daily`: Every calendar day
    - `weekly`: Every Friday (or last trading day)
    - `monthly`: Last day of each month

    **Performance:** Uses batch data fetching and rolling state calculation
    for O(D + T) complexity where D = dates, T = transactions.

    Raises **403** if you don't own the portfolio.
    """
    portfolio_id = portfolio.id

    # Validate date range
    if from_date > to_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from_date must be before or equal to to_date"
        )

    # Validate date range doesn't exceed maximum
    date_range_days = (to_date - from_date).days
    if date_range_days > MAX_HISTORY_DAYS:
        max_years = MAX_HISTORY_DAYS // 365
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Date range of {date_range_days} days exceeds maximum of {MAX_HISTORY_DAYS} days ({max_years} years)"
        )

    # Get history from service
    # Domain exceptions (PortfolioNotFoundError, InvalidIntervalError) propagate to global handlers
    history = service.get_history(
        db=db,
        portfolio_id=portfolio_id,
        start_date=from_date,
        end_date=to_date,
        interval=interval,
    )

    # Map to response schema
    return PortfolioHistoryResponse(
        portfolio_id=history.portfolio_id,
        portfolio_currency=history.portfolio_currency,
        from_date=history.start_date,
        to_date=history.end_date,
        interval=history.interval,
        tracks_cash=history.tracks_cash,
        data=[_map_history_point(p) for p in history.data],
        total_points=len(history.data),
        warnings=history.warnings,
    )
