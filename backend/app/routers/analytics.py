# backend/app/routers/analytics.py
"""
Portfolio analytics endpoints.

Provides performance, risk, and benchmark metrics:
- GET /portfolios/{id}/analytics - Full analytics (performance + risk + benchmark)
- GET /portfolios/{id}/analytics/performance - Performance metrics only
- GET /portfolios/{id}/analytics/risk - Risk metrics only
- GET /portfolios/{id}/analytics/benchmark - Benchmark comparison only

Optional parameters:
- from_date: Start of analysis period (default: first transaction date)
- to_date: End of analysis period (default: today)
- benchmark_symbol: Benchmark ticker (e.g., "^SPX", "IWDA.AS")
- risk_free_rate: Annual risk-free rate as decimal (default: 0.02)
- scope: Analysis scope - "current_period" (GIPS default) or "full_history"

Note: These endpoints are nested under /portfolios/{id} because analytics
are always in the context of a specific portfolio.
"""

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Portfolio, Transaction, User
from app.middleware.rate_limit import limiter, RATE_LIMIT_ANALYTICS
from app.dependencies import get_portfolio_with_owner_check
from app.services.constants import MAX_HISTORY_DAYS
from app.schemas.analytics import (
    PeriodInfo,
    PerformanceMetricsResponse,
    PerformanceResponse,
    DrawdownPeriodResponse,
    InvestmentPeriodResponse,
    MeasurementPeriodResponse,
    RiskMetricsResponse,
    RiskResponse,
    BenchmarkMetricsResponse,
    BenchmarkResponse,
    AnalyticsResponse,
)
from app.services.analytics import (
    AnalyticsService,
    PerformanceMetrics,
    RiskMetrics,
    BenchmarkMetrics,
    AnalyticsPeriod,
    DrawdownPeriod,
    InvestmentPeriod,
    MeasurementPeriodInfo,
)
from app.dependencies import get_analytics_service

# =============================================================================
# ROUTER SETUP
# =============================================================================

router = APIRouter(
    prefix="/portfolios",
    tags=["Analytics"],
)

# =============================================================================
# CONSTANTS
# =============================================================================

DEFAULT_RISK_FREE_RATE = Decimal("0.02")
MAX_DRAWDOWN_PERIODS = 5


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _get_first_transaction_date(db: Session, portfolio_id: int) -> date | None:
    """Get the date of the first transaction for a portfolio."""
    result = db.execute(
        select(func.min(Transaction.date))
        .where(Transaction.portfolio_id == portfolio_id)
    ).scalar()
    return result


def _resolve_date_range(
        db: Session,
        portfolio_id: int,
        from_date: date | None,
        to_date: date | None,
) -> tuple[date, date]:
    """
    Resolve date range defaults.

    - from_date defaults to first transaction date
    - to_date defaults to today
    """

    def ensure_date(d: date | datetime | None) -> date | None:
        """Convert datetime to date if needed."""
        if d is None:
            return None
        if isinstance(d, datetime):
            return d.date()
        return d

    to_date = ensure_date(to_date) or date.today()

    if from_date is None:
        first_txn_date = _get_first_transaction_date(db, portfolio_id)
        from_date = ensure_date(first_txn_date) or to_date
    else:
        from_date = ensure_date(from_date)

    return from_date, to_date


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _decimal_to_str(value: Decimal | None) -> str | None:
    """Convert Decimal to string for JSON response, preserving precision."""
    if value is None:
        return None
    # Convert int to Decimal if needed (safety net)
    if isinstance(value, int):
        value = Decimal(str(value))
    # Use str() directly to preserve exact Decimal precision
    # Normalize removes trailing zeros while keeping precision
    return str(value.normalize())


def _validate_date_range(from_date: date, to_date: date) -> None:
    """Validate date range constraints."""
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


# =============================================================================
# MAPPER FUNCTIONS (Internal Types -> Pydantic Schemas)
# =============================================================================

def _map_period(period: AnalyticsPeriod) -> PeriodInfo:
    """Map internal AnalyticsPeriod to Pydantic schema."""
    return PeriodInfo(
        from_date=period.from_date,
        to_date=period.to_date,
        trading_days=period.trading_days,
        calendar_days=period.calendar_days,
    )


def _map_drawdown_period(dd: DrawdownPeriod) -> DrawdownPeriodResponse:
    """Map internal DrawdownPeriod to Pydantic schema."""
    return DrawdownPeriodResponse(
        start_date=dd.start_date,
        trough_date=dd.trough_date,
        end_date=dd.end_date,
        depth=_decimal_to_str(dd.depth),
        duration_days=dd.duration_days,
        recovery_days=dd.recovery_days,
    )


def _map_investment_period(period: InvestmentPeriod) -> InvestmentPeriodResponse:
    """Map internal InvestmentPeriod to Pydantic schema."""
    return InvestmentPeriodResponse(
        period_index=period.period_number,
        start_date=period.start_date,
        end_date=period.end_date,
        is_active=period.is_active,
        contribution_date=None,  # Not tracked at this level
        contribution_value=None,  # Not tracked at this level
        start_value=_decimal_to_str(period.start_value),
        end_value=_decimal_to_str(period.end_value),
        trading_days=period.trading_days,
    )


def _map_measurement_period(period: MeasurementPeriodInfo | None) -> MeasurementPeriodResponse | None:
    """Map internal MeasurementPeriodInfo to Pydantic schema."""
    if period is None:
        return None
    return MeasurementPeriodResponse(
        period_type="current_period" if period.period_number > 0 else "full_history",
        start_date=period.start_date,
        end_date=period.end_date,
        trading_days=period.trading_days,
        description=f"Period {period.period_number}" if period.period_number > 0 else "All periods combined",
    )


def _map_performance(perf: PerformanceMetrics) -> PerformanceMetricsResponse:
    """Map internal PerformanceMetrics to Pydantic schema."""
    return PerformanceMetricsResponse(
        simple_return=_decimal_to_str(perf.simple_return),
        simple_return_annualized=_decimal_to_str(perf.simple_return_annualized),
        twr=_decimal_to_str(perf.twr),
        twr_annualized=_decimal_to_str(perf.twr_annualized),
        cagr=_decimal_to_str(perf.cagr),
        xirr=_decimal_to_str(perf.xirr),
        total_gain=_decimal_to_str(perf.total_gain),
        start_value=_decimal_to_str(perf.start_value),
        end_value=_decimal_to_str(perf.end_value),
        cost_basis=_decimal_to_str(perf.cost_basis),
        total_deposits=_decimal_to_str(perf.total_deposits) or "0",
        total_withdrawals=_decimal_to_str(perf.total_withdrawals) or "0",
        net_invested=_decimal_to_str(perf.net_invested),
        has_sufficient_data=perf.has_sufficient_data,
        warnings=perf.warnings,
        total_realized_pnl=_decimal_to_str(perf.total_realized_pnl),
    )


def _map_risk(risk: RiskMetrics) -> RiskMetricsResponse:
    """Map internal RiskMetrics to Pydantic schema."""
    # Limit drawdown periods to top 5 (sorted by depth - most negative first)
    sorted_drawdowns = sorted(
        risk.drawdown_periods,
        key=lambda x: x.depth if x.depth else Decimal("0")
    )[:MAX_DRAWDOWN_PERIODS]

    return RiskMetricsResponse(
        volatility_daily=_decimal_to_str(risk.volatility_daily),
        volatility_annualized=_decimal_to_str(risk.volatility_annualized),
        downside_deviation=_decimal_to_str(risk.downside_deviation),
        sharpe_ratio=_decimal_to_str(risk.sharpe_ratio),
        sortino_ratio=_decimal_to_str(risk.sortino_ratio),
        calmar_ratio=_decimal_to_str(risk.calmar_ratio),
        max_drawdown=_decimal_to_str(risk.max_drawdown),
        max_drawdown_start=risk.max_drawdown_start,
        max_drawdown_end=risk.max_drawdown_end,
        current_drawdown=_decimal_to_str(risk.current_drawdown),
        var_95=_decimal_to_str(risk.var_95),
        cvar_95=_decimal_to_str(risk.cvar_95),
        positive_days=risk.positive_days,
        negative_days=risk.negative_days,
        win_rate=_decimal_to_str(risk.win_rate),
        best_day=_decimal_to_str(risk.best_day),
        best_day_date=risk.best_day_date,
        worst_day=_decimal_to_str(risk.worst_day),
        worst_day_date=risk.worst_day_date,
        drawdown_periods=[_map_drawdown_period(dd) for dd in sorted_drawdowns],
        # GIPS investment period tracking
        measurement_period=_map_measurement_period(risk.measurement_period),
        investment_periods=[_map_investment_period(p) for p in risk.investment_periods],
        total_periods=risk.total_periods,
        scope=risk.scope,
        # Data quality
        has_sufficient_data=risk.has_sufficient_data,
        warnings=risk.warnings,
    )


def _map_benchmark(bench: BenchmarkMetrics) -> BenchmarkMetricsResponse:
    """Map internal BenchmarkMetrics to Pydantic schema."""
    return BenchmarkMetricsResponse(
        benchmark_symbol=bench.benchmark_symbol,
        benchmark_name=bench.benchmark_name,
        portfolio_return=_decimal_to_str(bench.portfolio_return),
        benchmark_return=_decimal_to_str(bench.benchmark_return),
        excess_return=_decimal_to_str(bench.excess_return),
        beta=_decimal_to_str(bench.beta),
        alpha=_decimal_to_str(bench.alpha),
        correlation=_decimal_to_str(bench.correlation),
        r_squared=_decimal_to_str(bench.r_squared),
        tracking_error=_decimal_to_str(bench.tracking_error),
        information_ratio=_decimal_to_str(bench.information_ratio),
        up_capture=_decimal_to_str(bench.up_capture),
        down_capture=_decimal_to_str(bench.down_capture),
        has_sufficient_data=bench.has_sufficient_data,
        warnings=bench.warnings,
    )


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get(
    "/{portfolio_id}/analytics",
    response_model=AnalyticsResponse,
    summary="Get full portfolio analytics",
    response_description="Complete analytics with performance, risk, and optional benchmark"
)
@limiter.limit(RATE_LIMIT_ANALYTICS)
def get_portfolio_analytics(
        request: Request,  # Required for rate limiting
        portfolio: Portfolio = Depends(get_portfolio_with_owner_check),
        from_date: date | None = Query(
            default=None,
            description="Start date of analysis period (default: first transaction date)",
            alias="from_date"
        ),
        to_date: date | None = Query(
            default=None,
            description="End date of analysis period (default: today)",
            alias="to_date"
        ),
        benchmark_symbol: str | None = Query(
            default=None,
            description="Benchmark ticker (e.g., '^SPX', 'IWDA.AS'). If not provided, no benchmark comparison.",
            alias="benchmark"
        ),
        risk_free_rate: Decimal = Query(
            default=DEFAULT_RISK_FREE_RATE,
            ge=Decimal("0"),
            le=Decimal("1"),
            description="Annual risk-free rate as decimal (0.02 = 2%)",
            alias="risk_free_rate"
        ),
        scope: str = Query(
            default="current_period",
            description="Analysis scope: 'current_period' (GIPS-compliant, default) or 'full_history'",
        ),
        db: Session = Depends(get_db),
        service: AnalyticsService = Depends(get_analytics_service),
) -> AnalyticsResponse:
    """
    Get complete portfolio analytics for a date range.

    Returns comprehensive metrics including:
    - **Performance**: TWR, XIRR, CAGR, simple return
    - **Risk**: Volatility, Sharpe, Sortino, Drawdowns, VaR
    - **Benchmark** (optional): Beta, Alpha, Correlation

    **GIPS Compliance (scope parameter):**
    - `current_period`: Metrics for active investment period only (default, GIPS-compliant)
    - `full_history`: Chain all periods together, excluding zero-equity days

    **Note**: If the portfolio has multiple investment periods (separated by full
    liquidations), the default behavior shows metrics for the current period only.
    Use `scope=full_history` to see combined metrics across all periods.

    Raises **403** if you don't own the portfolio.
    """
    portfolio_id = portfolio.id

    # Resolve date defaults (from_date = first txn, to_date = today)
    from_date, to_date = _resolve_date_range(db, portfolio_id, from_date, to_date)

    # Validate inputs
    _validate_date_range(from_date, to_date)

    # Validate scope
    if scope not in ("current_period", "full_history"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scope '{scope}'. Must be 'current_period' or 'full_history'"
        )

    # Get analytics from service (BenchmarkNotSyncedError handled by global handler)
    result = service.get_analytics(
        db=db,
        portfolio_id=portfolio_id,
        start_date=from_date,
        end_date=to_date,
        benchmark_symbol=benchmark_symbol,
        risk_free_rate=risk_free_rate,
        scope=scope,
    )

    # Map to response schema
    return AnalyticsResponse(
        portfolio_id=result.portfolio_id,
        portfolio_currency=result.portfolio_currency,
        period=_map_period(result.period),
        performance=_map_performance(result.performance),
        risk=_map_risk(result.risk),
        benchmark=_map_benchmark(result.benchmark) if result.benchmark else None,
        has_complete_data=result.has_complete_data,
        warnings=result.warnings,
        has_synthetic_data=result.has_synthetic_data,
        synthetic_data_percentage=result.synthetic_data_percentage,
        synthetic_holdings=result.synthetic_holdings,
        synthetic_date_range=result.synthetic_date_range,
        synthetic_details=result.synthetic_details,
        reliability_notes=result.reliability_notes,
    )


@router.get(
    "/{portfolio_id}/analytics/performance",
    response_model=PerformanceResponse,
    summary="Get performance metrics only",
    response_description="Performance metrics (TWR, XIRR, CAGR)"
)
@limiter.limit(RATE_LIMIT_ANALYTICS)
def get_portfolio_performance(
        request: Request,  # Required for rate limiting
        portfolio: Portfolio = Depends(get_portfolio_with_owner_check),
        from_date: date | None = Query(
            default=None,
            description="Start date of analysis period (default: first transaction date)"
        ),
        to_date: date | None = Query(
            default=None,
            description="End date of analysis period (default: today)"
        ),
        db: Session = Depends(get_db),
        service: AnalyticsService = Depends(get_analytics_service),
) -> PerformanceResponse:
    """
    Get performance metrics for a portfolio.

    Returns only return-based metrics:
    - `twr`: Time-Weighted Return
    - `xirr`: Extended IRR (money-weighted)
    - `cagr`: Compound Annual Growth Rate
    - `simple_return`: Cash-flow adjusted return
    - `total_gain`: Absolute gain in portfolio currency

    **Use this endpoint when you only need returns**, without risk
    or benchmark analysis. It's faster than the full analytics endpoint.

    Raises **403** if you don't own the portfolio.
    """
    portfolio_id = portfolio.id

    # Resolve date defaults
    from_date, to_date = _resolve_date_range(db, portfolio_id, from_date, to_date)

    # Validate inputs
    _validate_date_range(from_date, to_date)

    # Get performance from service
    performance = service.get_performance(
        db=db,
        portfolio_id=portfolio_id,
        start_date=from_date,
        end_date=to_date,
    )

    # Build period info
    period = PeriodInfo(
        from_date=from_date,
        to_date=to_date,
        trading_days=performance.trading_days,
        calendar_days=performance.calendar_days,
    )

    return PerformanceResponse(
        portfolio_id=portfolio_id,
        portfolio_currency=portfolio.currency,
        period=period,
        performance=_map_performance(performance),
    )


@router.get(
    "/{portfolio_id}/analytics/risk",
    response_model=RiskResponse,
    summary="Get risk metrics only",
    response_description="Risk metrics (Volatility, Sharpe, Drawdown)"
)
@limiter.limit(RATE_LIMIT_ANALYTICS)
def get_portfolio_risk(
        request: Request,  # Required for rate limiting
        portfolio: Portfolio = Depends(get_portfolio_with_owner_check),
        from_date: date | None = Query(
            default=None,
            description="Start date of analysis period (default: first transaction date)"
        ),
        to_date: date | None = Query(
            default=None,
            description="End date of analysis period (default: today)"
        ),
        risk_free_rate: Decimal = Query(
            default=DEFAULT_RISK_FREE_RATE,
            ge=Decimal("0"),
            le=Decimal("1"),
            description="Annual risk-free rate as decimal (0.02 = 2%)"
        ),
        scope: str = Query(
            default="current_period",
            description="Analysis scope: 'current_period' (GIPS-compliant, default) or 'full_history'",
        ),
        db: Session = Depends(get_db),
        service: AnalyticsService = Depends(get_analytics_service),
) -> RiskResponse:
    """
    Get risk metrics for a portfolio.

    Returns:
    - **Volatility**: Daily and annualized standard deviation
    - **Risk-adjusted returns**: Sharpe, Sortino, Calmar ratios
    - **Drawdown analysis**: Max drawdown, current drawdown, top 5 periods
    - **Value at Risk**: VaR and CVaR at 95% confidence
    - **Win statistics**: Positive/negative days, best/worst day
    - **Investment periods**: GIPS-compliant period detection

    **GIPS Compliance (scope parameter):**
    - `current_period`: Metrics for active investment period only (default)
    - `full_history`: Chain all periods together, excluding zero-equity days

    **Sharpe Ratio Interpretation:**
    - < 1.0: Sub-optimal
    - 1.0 - 2.0: Good
    - 2.0 - 3.0: Very good
    - > 3.0: Excellent

    **Note:** Risk metrics require daily data internally for accuracy.

    Raises **403** if you don't own the portfolio.
    """
    portfolio_id = portfolio.id

    # Resolve date defaults
    from_date, to_date = _resolve_date_range(db, portfolio_id, from_date, to_date)

    # Validate inputs
    _validate_date_range(from_date, to_date)

    # Validate scope
    if scope not in ("current_period", "full_history"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scope '{scope}'. Must be 'current_period' or 'full_history'"
        )

    # Get risk from service
    risk = service.get_risk(
        db=db,
        portfolio_id=portfolio_id,
        start_date=from_date,
        end_date=to_date,
        risk_free_rate=risk_free_rate,
        scope=scope,
    )

    # Build period info using measurement period if available
    if risk.measurement_period:
        period = PeriodInfo(
            from_date=risk.measurement_period.start_date,
            to_date=risk.measurement_period.end_date,
            trading_days=risk.measurement_period.trading_days,
            calendar_days=(risk.measurement_period.end_date - risk.measurement_period.start_date).days,
        )
    else:
        period = PeriodInfo(
            from_date=from_date,
            to_date=to_date,
            trading_days=0,
            calendar_days=(to_date - from_date).days,
        )

    return RiskResponse(
        portfolio_id=portfolio_id,
        portfolio_currency=portfolio.currency,
        period=period,
        risk=_map_risk(risk),
    )


@router.get(
    "/{portfolio_id}/analytics/benchmark",
    response_model=BenchmarkResponse,
    summary="Get benchmark comparison only",
    response_description="Benchmark metrics (Beta, Alpha, Correlation)"
)
@limiter.limit(RATE_LIMIT_ANALYTICS)
def get_portfolio_benchmark(
        request: Request,  # Required for rate limiting
        portfolio: Portfolio = Depends(get_portfolio_with_owner_check),
        from_date: date | None = Query(
            default=None,
            description="Start date of analysis period (default: first transaction date)"
        ),
        to_date: date | None = Query(
            default=None,
            description="End date of analysis period (default: today)"
        ),
        benchmark_symbol: str | None = Query(
            default=None,
            description="Benchmark ticker (e.g., '^SPX', 'IWDA.AS'). Uses default if not provided.",
            alias="benchmark"
        ),
        risk_free_rate: Decimal = Query(
            default=DEFAULT_RISK_FREE_RATE,
            ge=Decimal("0"),
            le=Decimal("1"),
            description="Annual risk-free rate as decimal (0.02 = 2%)"
        ),
        db: Session = Depends(get_db),
        service: AnalyticsService = Depends(get_analytics_service),
) -> BenchmarkResponse:
    """
    Get benchmark comparison metrics for a portfolio.

    Compares portfolio performance against a benchmark index:
    - **CAPM metrics**: Beta (systematic risk), Alpha (excess return)
    - **Correlation**: How closely the portfolio tracks the benchmark
    - **Tracking error**: Standard deviation of return differences
    - **Information ratio**: Active return per unit of active risk

    **Beta Interpretation:**
    - β > 1: More volatile than market
    - β < 1: Less volatile than market
    - β = 1: Moves with market

    **Alpha Interpretation:**
    - α > 0: Outperforming risk-adjusted expectations
    - α < 0: Underperforming risk-adjusted expectations

    **Note:** Benchmark must be synced (have price data) before comparison.

    Raises **403** if you don't own the portfolio.
    """
    portfolio_id = portfolio.id

    # Resolve date defaults
    from_date, to_date = _resolve_date_range(db, portfolio_id, from_date, to_date)

    # Validate inputs
    _validate_date_range(from_date, to_date)

    # Get benchmark from service (BenchmarkNotSyncedError handled by global handler)
    benchmark = service.get_benchmark(
        db=db,
        portfolio_id=portfolio_id,
        start_date=from_date,
        end_date=to_date,
        benchmark_symbol=benchmark_symbol,
        risk_free_rate=risk_free_rate,
    )

    # Build period info
    period = PeriodInfo(
        from_date=from_date,
        to_date=to_date,
        trading_days=0,  # We don't have this from benchmark response
        calendar_days=(to_date - from_date).days,
    )

    return BenchmarkResponse(
        portfolio_id=portfolio_id,
        portfolio_currency=portfolio.currency,
        period=period,
        benchmark=_map_benchmark(benchmark),
    )
