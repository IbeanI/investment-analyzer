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

Note: These endpoints are nested under /portfolios/{id} because analytics
are always in the context of a specific portfolio.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Portfolio, Transaction
from app.schemas.analytics import (
    PeriodInfo,
    PerformanceMetricsResponse,
    PerformanceResponse,
    DrawdownPeriodResponse,
    RiskMetricsResponse,
    RiskResponse,
    BenchmarkMetricsResponse,
    BenchmarkResponse,
    AnalyticsResponse,
)
from app.services.analytics import (
    AnalyticsService,
    BenchmarkNotSyncedError,
    PerformanceMetrics,
    RiskMetrics,
    BenchmarkMetrics,
    AnalyticsPeriod,
    DrawdownPeriod,
)

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
# DEPENDENCIES
# =============================================================================

def get_analytics_service() -> AnalyticsService:
    """Dependency that provides the analytics service."""
    return AnalyticsService()


def get_portfolio_or_404(db: Session, portfolio_id: int) -> Portfolio:
    """Fetch a portfolio by ID or raise 404 if not found."""
    portfolio = db.get(Portfolio, portfolio_id)

    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio with id {portfolio_id} not found"
        )

    return portfolio


def _get_first_transaction_date(db: Session, portfolio_id: int) -> date | None:
    """Get the date of the first transaction for a portfolio."""
    stmt = select(func.min(Transaction.date)).where(
        Transaction.portfolio_id == portfolio_id
    )
    result = db.execute(stmt).scalar()
    # Transaction.date is datetime, convert to date
    if result is not None:
        return result.date() if hasattr(result, 'date') else result
    return None


def _resolve_date_range(
        db: Session,
        portfolio_id: int,
        from_date: date | None,
        to_date: date | None,
) -> tuple[date, date]:
    """
    Resolve date range with smart defaults.

    Args:
        db: Database session
        portfolio_id: Portfolio ID
        from_date: Start date (None = first transaction date)
        to_date: End date (None = today)

    Returns:
        Tuple of (resolved_from_date, resolved_to_date)

    Raises:
        HTTPException: If no transactions found and from_date not provided
    """
    # Default to_date to today
    if to_date is None:
        to_date = date.today()

    # Default from_date to first transaction date
    if from_date is None:
        from_date = _get_first_transaction_date(db, portfolio_id)
        if from_date is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No transactions found for this portfolio. Please provide from_date."
            )

    return from_date, to_date


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _decimal_to_str(value: Decimal | int | None) -> str | None:
    """Convert Decimal to string, preserving None."""
    if value is None:
        return None
    # Convert int to Decimal if needed (safety net)
    if isinstance(value, int):
        value = Decimal(str(value))
    # Format to reasonable precision (8 decimal places)
    return str(value.quantize(Decimal("0.00000001")).normalize())


def _validate_date_range(from_date: date, to_date: date) -> None:
    """Validate that from_date is before or equal to to_date."""
    if from_date > to_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from_date must be before or equal to to_date"
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
def get_portfolio_analytics(
        portfolio_id: int,
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
        db: Session = Depends(get_db),
        service: AnalyticsService = Depends(get_analytics_service),
) -> AnalyticsResponse:
    """
    Get complete portfolio analytics for a date range.

    Returns:
    - **performance**: TWR, XIRR, CAGR, simple return, total gain
    - **risk**: Volatility, Sharpe, Sortino, Drawdown, VaR
    - **benchmark**: Beta, Alpha, Correlation (if benchmark_symbol provided)

    **Performance Metrics:**
    - `twr`: Time-Weighted Return (removes cash flow timing bias)
    - `xirr`: Extended IRR (money-weighted, accounts for cash flow timing)
    - `cagr`: Compound Annual Growth Rate
    - `simple_return`: Cash-flow adjusted return (total_gain / start_value)

    **Risk Metrics:**
    - `sharpe_ratio`: Risk-adjusted return (higher is better)
    - `sortino_ratio`: Downside risk-adjusted return
    - `max_drawdown`: Largest peak-to-trough decline
    - `var_95`: Value at Risk at 95% confidence

    **Benchmark Metrics (if benchmark provided):**
    - `beta`: Systematic risk (β > 1 = more volatile than market)
    - `alpha`: Excess return above expected
    - `correlation`: How closely portfolio tracks benchmark

    **Note:** Results are cached for 1 hour to improve performance.
    """
    # Verify portfolio exists first
    portfolio = get_portfolio_or_404(db, portfolio_id)

    # Resolve date defaults (from_date = first txn, to_date = today)
    from_date, to_date = _resolve_date_range(db, portfolio_id, from_date, to_date)

    # Validate inputs
    _validate_date_range(from_date, to_date)

    # Get analytics from service
    try:
        result = service.get_analytics(
            db=db,
            portfolio_id=portfolio_id,
            start_date=from_date,
            end_date=to_date,
            benchmark_symbol=benchmark_symbol,
            risk_free_rate=risk_free_rate,
        )
    except BenchmarkNotSyncedError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "BenchmarkNotSynced",
                "message": e.message,
                "benchmark_symbol": e.symbol,
            }
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
    )


@router.get(
    "/{portfolio_id}/analytics/performance",
    response_model=PerformanceResponse,
    summary="Get performance metrics only",
    response_description="Performance metrics (TWR, XIRR, CAGR)"
)
def get_portfolio_performance(
        portfolio_id: int,
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
    """
    # Verify portfolio exists first
    portfolio = get_portfolio_or_404(db, portfolio_id)

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
def get_portfolio_risk(
        portfolio_id: int,
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

    **Sharpe Ratio Interpretation:**
    - < 1.0: Sub-optimal
    - 1.0 - 2.0: Good
    - 2.0 - 3.0: Very good
    - > 3.0: Excellent

    **Note:** Risk metrics require daily data internally for accuracy.
    """
    # Verify portfolio exists first
    portfolio = get_portfolio_or_404(db, portfolio_id)

    # Resolve date defaults
    from_date, to_date = _resolve_date_range(db, portfolio_id, from_date, to_date)

    # Validate inputs
    _validate_date_range(from_date, to_date)

    # Get risk from service
    risk = service.get_risk(
        db=db,
        portfolio_id=portfolio_id,
        start_date=from_date,
        end_date=to_date,
        risk_free_rate=risk_free_rate,
    )

    # Build period info (we need trading_days from the risk result)
    # Since RiskMetrics doesn't have this, we approximate from daily values
    calendar_days = (to_date - from_date).days
    trading_days = risk.positive_days + risk.negative_days

    period = PeriodInfo(
        from_date=from_date,
        to_date=to_date,
        trading_days=trading_days,
        calendar_days=calendar_days,
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
    summary="Get benchmark comparison",
    response_description="Benchmark metrics (Beta, Alpha, Correlation)"
)
def get_portfolio_benchmark(
        portfolio_id: int,
        from_date: date | None = Query(
            default=None,
            description="Start date of analysis period (default: first transaction date)"
        ),
        to_date: date | None = Query(
            default=None,
            description="End date of analysis period (default: today)"
        ),
        benchmark_symbol: str = Query(
            ...,
            description="Benchmark ticker (e.g., '^SPX', 'IWDA.AS')",
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
    Compare portfolio performance against a benchmark.

    Requires `benchmark` query parameter with a valid ticker symbol.
    The benchmark must be synced to the database before use.

    **Common benchmarks:**
    - `^SPX`: S&P 500 Index (US large cap)
    - `IWDA.AS`: iShares MSCI World ETF (Global developed markets)

    **Metrics returned:**
    - `beta`: Systematic risk (β > 1 = more volatile than market)
    - `alpha`: Jensen's Alpha (excess return above expected)
    - `correlation`: Pearson correlation (-1 to 1)
    - `r_squared`: How much variance is explained by benchmark
    - `tracking_error`: Standard deviation of return differences
    - `information_ratio`: Active return per unit of tracking risk
    - `up_capture` / `down_capture`: Performance in up/down markets

    **Beta Interpretation:**
    - β = 1.0: Moves with market
    - β > 1.0: More volatile than market
    - β < 1.0: Less volatile than market
    - β < 0: Moves opposite to market (rare)

    **Error:** Returns 400 if benchmark is not synced to database.
    """
    # Verify portfolio exists first
    portfolio = get_portfolio_or_404(db, portfolio_id)

    # Resolve date defaults
    from_date, to_date = _resolve_date_range(db, portfolio_id, from_date, to_date)

    # Validate inputs
    _validate_date_range(from_date, to_date)

    # Get benchmark comparison from service
    try:
        benchmark = service.get_benchmark(
            db=db,
            portfolio_id=portfolio_id,
            start_date=from_date,
            end_date=to_date,
            benchmark_symbol=benchmark_symbol,
            risk_free_rate=risk_free_rate,
        )
    except BenchmarkNotSyncedError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "BenchmarkNotSynced",
                "message": e.message,
                "benchmark_symbol": e.symbol,
            }
        )

    # Build period info
    calendar_days = (to_date - from_date).days

    period = PeriodInfo(
        from_date=from_date,
        to_date=to_date,
        trading_days=0,  # We don't have this from benchmark-only call
        calendar_days=calendar_days,
    )

    return BenchmarkResponse(
        portfolio_id=portfolio_id,
        portfolio_currency=portfolio.currency,
        period=period,
        benchmark=_map_benchmark(benchmark),
    )
