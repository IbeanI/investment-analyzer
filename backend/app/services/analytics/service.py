# backend/app/services/analytics/service.py
"""
Analytics Service orchestrator.

This is the main entry point for the Analytics Service. It:
1. Fetches portfolio history from ValuationService (ALWAYS daily interval)
2. Extracts cash flows from transactions
3. Delegates to specialized calculators
4. Caches results for 1 hour (CPU-intensive calculations)
5. Aggregates results into AnalyticsResult

IMPORTANT: Risk metrics require daily data points. This service always
fetches daily data internally, regardless of any UI preferences.

Architecture:
    AnalyticsService
        ├── uses → ValuationService (get_history with interval="daily")
        ├── uses → ReturnsCalculator (TWR, IRR, CAGR)
        ├── uses → RiskCalculator (Volatility, Sharpe, Drawdown)
        ├── uses → BenchmarkCalculator (Beta, Alpha)
        └── uses → AnalyticsCache (1-hour TTL cache)

Benchmark Requirements:
    - Benchmark must exist as an Asset in the database
    - Benchmark prices must be synced before analytics can run
    - Default benchmarks: ^SPX (USD), IWDA.AS (EUR)

Usage:
    from app.services.analytics import AnalyticsService

    service = AnalyticsService()

    # Performance metrics only
    perf = service.get_performance(db, portfolio_id=1, start_date, end_date)

    # Risk metrics only
    risk = service.get_risk(db, portfolio_id=1, start_date, end_date)

    # Benchmark comparison (benchmark must be synced first!)
    bench = service.get_benchmark(db, portfolio_id=1, start_date, end_date, "^SPX")

    # All metrics combined
    result = service.get_analytics(db, portfolio_id=1, start_date, end_date)
"""

import logging
import threading
from datetime import date, datetime, timedelta
import decimal
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction, TransactionType, Portfolio, Asset, MarketData
from app.services.analytics.benchmark import BenchmarkCalculator
from app.services.protocols import ValuationServiceProtocol
from app.services.valuation.types import PortfolioHistory
from app.services.analytics.returns import ReturnsCalculator, calculate_series_returns
from app.services.analytics.risk import RiskCalculator
from app.services.analytics.types import (
    CashFlow,
    DailyValue,
    PerformanceMetrics,
    RiskMetrics,
    BenchmarkMetrics,
    AnalyticsPeriod,
    AnalyticsResult,
)

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

# CRITICAL: Analytics always uses daily data internally.
# Risk metrics (Volatility, Beta, Sharpe) strictly require daily data points.
# Do not change this - weekly/monthly data will produce inaccurate results.
_INTERNAL_INTERVAL = "daily"

# Import centralized constants
from app.services.constants import (
    DEFAULT_RISK_FREE_RATE,
    SYNTHETIC_WARNING_THRESHOLD,
    SYNTHETIC_CRITICAL_THRESHOLD,
    DEFAULT_BENCHMARKS,
    CACHE_TTL_SECONDS,
)


# =============================================================================
# CACHE
# =============================================================================

# Maximum number of entries in the analytics cache
# Prevents unbounded memory growth from attackers generating many unique date ranges
# 1000 entries × ~10KB avg result size ≈ 10MB max cache footprint
ANALYTICS_CACHE_MAX_SIZE = 1000


class AnalyticsCache:
    """
    Thread-safe bounded LRU cache with TTL for analytics results.

    Analytics calculations are CPU-intensive, so we cache results
    for 1 hour to avoid redundant recalculation.

    Memory Safety:
        Uses a bounded LRU cache with a maximum of 1000 entries to prevent
        unbounded memory growth. When the cache is full, the least recently
        used entry is evicted to make room for new entries.

    Cache key format: "analytics:{portfolio_id}:{start}:{end}:{benchmark}"

    Thread Safety:
        Uses threading.Lock for safe concurrent access in single-worker mode.
        For production with multiple workers, consider using Redis instead.
    """

    def __init__(
            self,
            ttl_seconds: int = CACHE_TTL_SECONDS,
            max_size: int = ANALYTICS_CACHE_MAX_SIZE,
    ):
        """
        Initialize cache with TTL and max size.

        Args:
            ttl_seconds: Time-to-live in seconds (default 1 hour)
            max_size: Maximum number of entries (default 1000)
        """
        from collections import OrderedDict
        self._cache: OrderedDict[str, tuple[datetime, Any]] = OrderedDict()
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_size = max_size
        self._lock = threading.Lock()

    def _make_key(
            self,
            portfolio_id: int,
            start_date: date,
            end_date: date,
            benchmark: str | None,
    ) -> str:
        """Generate cache key."""
        return f"analytics:{portfolio_id}:{start_date}:{end_date}:{benchmark or 'none'}"

    def get(
            self,
            portfolio_id: int,
            start_date: date,
            end_date: date,
            benchmark: str | None,
    ) -> AnalyticsResult | None:
        """
        Get cached result if exists and not expired.

        Implements LRU by moving accessed entries to the end.

        Returns:
            Cached AnalyticsResult or None if not found/expired
        """
        key = self._make_key(portfolio_id, start_date, end_date, benchmark)

        with self._lock:
            if key in self._cache:
                timestamp, result = self._cache[key]
                if datetime.now() - timestamp < self._ttl:
                    # Move to end (most recently used)
                    self._cache.move_to_end(key)
                    logger.debug(f"Cache hit for {key}")
                    return result
                else:
                    # Expired - remove from cache
                    del self._cache[key]
                    logger.debug(f"Cache expired for {key}")

        return None

    def set(
            self,
            portfolio_id: int,
            start_date: date,
            end_date: date,
            benchmark: str | None,
            result: AnalyticsResult,
    ) -> None:
        """
        Store result in cache with LRU eviction.

        If cache is at max capacity, evicts the least recently used entry.
        """
        key = self._make_key(portfolio_id, start_date, end_date, benchmark)
        with self._lock:
            # If key exists, remove it first (will re-add at end)
            if key in self._cache:
                del self._cache[key]
            # Evict oldest entries if at capacity
            while len(self._cache) >= self._max_size:
                # Remove oldest (first) entry
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                logger.debug(f"Cache evicted {oldest_key} (LRU)")
            # Add new entry at end (most recently used)
            self._cache[key] = (datetime.now(), result)
        logger.debug(f"Cached result for {key}")

    def invalidate(self, portfolio_id: int) -> int:
        """
        Invalidate all cache entries for a portfolio.

        Args:
            portfolio_id: Portfolio to invalidate

        Returns:
            Number of entries invalidated
        """
        prefix = f"analytics:{portfolio_id}:"
        with self._lock:
            keys_to_delete = [k for k in self._cache.keys() if k.startswith(prefix)]
            for key in keys_to_delete:
                del self._cache[key]

        if keys_to_delete:
            logger.debug(f"Invalidated {len(keys_to_delete)} cache entries for portfolio {portfolio_id}")

        return len(keys_to_delete)

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
        logger.debug(f"Cleared {count} cache entries")

    def size(self) -> int:
        """Return current number of cached entries."""
        with self._lock:
            return len(self._cache)


# Import BenchmarkNotSyncedError from centralized exceptions
from app.services.exceptions import BenchmarkNotSyncedError


# =============================================================================
# ANALYTICS SERVICE
# =============================================================================

class AnalyticsService:
    """
    Main orchestrator for portfolio analytics.

    This service coordinates all analytics calculations by:
    1. Fetching historical portfolio values from ValuationService (daily)
    2. Extracting transaction data for cash flow analysis
    3. Delegating to specialized calculators
    4. Caching results for 1 hour
    5. Combining results into comprehensive analytics response

    IMPORTANT: This service always fetches DAILY data internally.
    Risk metrics require daily data points for accurate calculation.

    Attributes:
        _valuation_service: ValuationService for portfolio history
        _cache: AnalyticsCache for result caching
    """

    # Shared cache instance (singleton pattern)
    _shared_cache: AnalyticsCache | None = None

    def __init__(
            self,
            valuation_service: ValuationServiceProtocol | None = None,
            cache: AnalyticsCache | None = None,
    ):
        """
        Initialize the Analytics Service.

        Args:
            valuation_service: ValuationService instance for portfolio history.
                              If None, creates a new instance.
            cache: AnalyticsCache instance. If None, uses shared cache.
        """
        # Lazy import to avoid circular dependencies
        if valuation_service is None:
            from app.services.valuation import ValuationService
            valuation_service = ValuationService()

        self._valuation_service: ValuationServiceProtocol = valuation_service

        # Use shared cache or create one
        if cache is not None:
            self._cache = cache
        else:
            if AnalyticsService._shared_cache is None:
                AnalyticsService._shared_cache = AnalyticsCache()
            self._cache = AnalyticsService._shared_cache

        logger.info("AnalyticsService initialized")

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def get_performance(
            self,
            db: Session,
            portfolio_id: int,
            start_date: date,
            end_date: date,
    ) -> PerformanceMetrics:
        """
        Calculate performance metrics for a portfolio.

        Returns TWR, IRR/XIRR, CAGR, and simple return.

        Args:
            db: Database session
            portfolio_id: Portfolio to analyze
            start_date: Start of analysis period
            end_date: End of analysis period

        Returns:
            PerformanceMetrics with all return calculations
        """
        logger.info(
            f"Calculating performance for portfolio {portfolio_id} "
            f"from {start_date} to {end_date}"
        )

        # Get daily values from valuation service
        daily_values = self._get_daily_values(db, portfolio_id, start_date, end_date)

        if not daily_values:
            return PerformanceMetrics(
                has_sufficient_data=False,
                warnings=["No valuation data available for the period"],
            )

        # Get cash flows for XIRR calculation
        cash_flows = self._get_cash_flows(db, portfolio_id, start_date, end_date)

        if daily_values:
            # Add start value as positive cash flow (capital already invested at period start)
            # This is essential for XIRR when the portfolio had value before the period began
            if daily_values[0].value > 0:
                cash_flows.insert(0, CashFlow(
                    date=daily_values[0].date,
                    amount=daily_values[0].value,  # Positive = money in
                ))

            # Add end value as negative cash flow (money out)
            cash_flows.append(CashFlow(
                date=daily_values[-1].date,
                amount=-daily_values[-1].value,  # Negative = outflow
            ))

        # Get cost_basis and realized_pnl from valuation for accurate simple_return calculation
        # This is crucial for portfolios without cash tracking (no DEPOSIT/WITHDRAWAL)
        cost_basis, realized_pnl = self._get_valuation_data(db, portfolio_id, end_date)

        # Calculate all return metrics
        result = ReturnsCalculator.calculate_all(
            daily_values,
            cash_flows,
            cost_basis=cost_basis,
            realized_pnl=realized_pnl,
        )

        return result

    def _get_valuation_data(
            self,
            db: Session,
            portfolio_id: int,
            valuation_date: date,
    ) -> tuple[Decimal | None, Decimal | None]:
        """
        Get cost basis and realized P&L from valuation service.

        Returns:
            Tuple of (cost_basis, realized_pnl) - both can be None if error
        """
        try:
            valuation = self._valuation_service.get_valuation(
                db=db,
                portfolio_id=portfolio_id,
                valuation_date=valuation_date,
            )
            return valuation.total_cost_basis, valuation.total_realized_pnl
        except Exception as e:
            logger.warning(f"Could not get valuation data: {e}", exc_info=True)
            return None, None

    def get_risk(
            self,
            db: Session,
            portfolio_id: int,
            start_date: date,
            end_date: date,
            risk_free_rate: Decimal = DEFAULT_RISK_FREE_RATE,
            scope: str = "current_period"
    ) -> RiskMetrics:
        """
        Calculate risk metrics for a portfolio.

        Returns volatility, Sharpe ratio, max drawdown, etc.

        Args:
            db: Database session
            portfolio_id: Portfolio to analyze
            start_date: Start of analysis period
            end_date: End of analysis period
            risk_free_rate: Annual risk-free rate (default 2%)

        Returns:
            RiskMetrics with all risk calculations
        """
        logger.info(
            f"Calculating risk for portfolio {portfolio_id} "
            f"from {start_date} to {end_date}"
        )

        # Get daily values
        daily_values = self._get_daily_values(db, portfolio_id, start_date, end_date)

        if not daily_values:
            return RiskMetrics(
                has_sufficient_data=False,
                warnings=["No valuation data available for the period"],
            )

        # Get cost_basis and realized_pnl for accurate CAGR calculation (needed for Calmar ratio)
        cost_basis, realized_pnl = self._get_valuation_data(db, portfolio_id, end_date)

        # Get performance metrics for CAGR (needed for Calmar ratio)
        # Pass cost_basis and realized_pnl for accurate simple_return/CAGR calculation
        performance = ReturnsCalculator.calculate_all(
            daily_values,
            cost_basis=cost_basis,
            realized_pnl=realized_pnl,
        )

        # Calculate all risk metrics
        # Note: Sharpe uses TWR (time-weighted return) which is correctly calculated
        # from daily returns and doesn't need cost_basis adjustment
        result = RiskCalculator.calculate_all(
            daily_values=daily_values,
            risk_free_rate=risk_free_rate,
            annualized_return=performance.twr_annualized,
            scope=scope,
        )
        return result

    def get_benchmark(
            self,
            db: Session,
            portfolio_id: int,
            start_date: date,
            end_date: date,
            benchmark_symbol: str | None = None,
            risk_free_rate: Decimal = DEFAULT_RISK_FREE_RATE,
    ) -> BenchmarkMetrics:
        """
        Calculate benchmark comparison metrics.

        Compares portfolio to a benchmark index.

        Args:
            db: Database session
            portfolio_id: Portfolio to analyze
            start_date: Start of analysis period
            end_date: End of analysis period
            benchmark_symbol: Benchmark ticker (e.g., "^SPX", "IWDA.AS").
                            If None, uses default based on portfolio currency.
            risk_free_rate: Annual risk-free rate

        Returns:
            BenchmarkMetrics with comparison analysis

        Raises:
            BenchmarkNotSyncedError: If benchmark not found or has no data
        """
        # Get portfolio to determine currency for default benchmark
        portfolio = db.get(Portfolio, portfolio_id)

        # Determine benchmark symbol
        if benchmark_symbol is None:
            if portfolio:
                benchmark_symbol = self._get_default_benchmark(portfolio.currency)
            else:
                benchmark_symbol = DEFAULT_BENCHMARKS["DEFAULT"]

        logger.info(
            f"Calculating benchmark comparison for portfolio {portfolio_id} "
            f"vs {benchmark_symbol} from {start_date} to {end_date}"
        )

        # Get portfolio daily values
        portfolio_values = self._get_daily_values(db, portfolio_id, start_date, end_date)

        if not portfolio_values:
            return self._build_insufficient_benchmark_result(
                benchmark_symbol, "No portfolio valuation data available"
            )

        # Get benchmark prices (raises BenchmarkNotSyncedError if not found)
        benchmark_prices = self._get_benchmark_prices(
            db, benchmark_symbol, start_date, end_date
        )

        if not benchmark_prices:
            return self._build_insufficient_benchmark_result(
                benchmark_symbol, f"No price data available for benchmark {benchmark_symbol}"
            )

        # Align dates - only use dates where both have data
        aligned_data = self._align_portfolio_and_benchmark(portfolio_values, benchmark_prices)

        if aligned_data is None:
            return self._build_insufficient_benchmark_result(
                benchmark_symbol, "Insufficient overlapping data between portfolio and benchmark"
            )

        common_dates, aligned_portfolio, aligned_benchmark = aligned_data

        # Calculate returns
        portfolio_returns = calculate_series_returns(aligned_portfolio)
        benchmark_returns = calculate_series_returns(aligned_benchmark)

        # Calculate total returns
        portfolio_total = (aligned_portfolio[-1] - aligned_portfolio[0]) / aligned_portfolio[0]
        benchmark_total = (aligned_benchmark[-1] - aligned_benchmark[0]) / aligned_benchmark[0]

        # Annualize
        days = (common_dates[-1] - common_dates[0]).days
        if days > 0:
            portfolio_annual = self._annualize_return(portfolio_total, days)
            benchmark_annual = self._annualize_return(benchmark_total, days)
        else:
            portfolio_annual = portfolio_total
            benchmark_annual = benchmark_total

        # Calculate all benchmark metrics
        result = BenchmarkCalculator.calculate_all(
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            portfolio_total_return=portfolio_annual,
            benchmark_total_return=benchmark_annual,
            benchmark_symbol=benchmark_symbol,
            risk_free_rate=risk_free_rate,
        )

        return result

    def get_analytics(
            self,
            db: Session,
            portfolio_id: int,
            start_date: date,
            end_date: date,
            benchmark_symbol: str | None = None,
            risk_free_rate: Decimal = DEFAULT_RISK_FREE_RATE,
            scope: str = "current_period",
    ) -> AnalyticsResult:
        """
        Calculate all analytics metrics for a portfolio.

        This is the main entry point that returns everything:
        - Performance (TWR, IRR, CAGR)
        - Risk (Volatility, Sharpe, Drawdown)
        - Benchmark (Beta, Alpha) - if benchmark_symbol provided

        Results are cached for 1 hour to avoid redundant calculations.

        Args:
            db: Database session
            portfolio_id: Portfolio to analyze
            start_date: Start of analysis period
            end_date: End of analysis period
            benchmark_symbol: Optional benchmark ticker (e.g., "^SPX")
            risk_free_rate: Annual risk-free rate for Sharpe ratio
            scope: Analysis scope - "current_period" or "full_history"

        Returns:
            AnalyticsResult with all metrics

        Raises:
            BenchmarkNotSyncedError: If benchmark requested but not synced
        """
        logger.info(
            f"Calculating full analytics for portfolio {portfolio_id} "
            f"from {start_date} to {end_date}"
        )

        # Check cache
        cached = self._cache.get(portfolio_id, start_date, end_date, benchmark_symbol)
        if cached is not None:
            logger.debug(f"Cache hit for portfolio {portfolio_id}")
            return cached

        # Validate portfolio
        portfolio = db.get(Portfolio, portfolio_id)
        if portfolio is None:
            return self._build_not_found_result(portfolio_id, start_date, end_date)

        # Fetch data (single history call, reused by _get_daily_values)
        history = self._valuation_service.get_history(
            db=db, portfolio_id=portfolio_id,
            start_date=start_date, end_date=end_date, interval="daily",
        )
        # Pass history to avoid duplicate get_history call
        daily_values = self._get_daily_values(
            db, portfolio_id, start_date, end_date, history=history
        )
        cost_basis, realized_pnl = self._get_valuation_data(db, portfolio_id, end_date)

        # Calculate metrics
        performance = self._calculate_performance_metrics(
            db, portfolio_id, start_date, end_date,
            daily_values, cost_basis, realized_pnl, scope,
        )
        risk = RiskCalculator.calculate_all(
            daily_values=daily_values,
            risk_free_rate=risk_free_rate,
            annualized_return=performance.twr_annualized,
            scope=scope,
        )
        benchmark = None
        if benchmark_symbol:
            benchmark = self.get_benchmark(
                db, portfolio_id, start_date, end_date,
                benchmark_symbol, risk_free_rate
            )

        # Build result
        result = self._build_analytics_result(
            portfolio, portfolio_id, start_date, end_date,
            daily_values, history, performance, risk, benchmark,
        )

        # Cache and return
        self._cache.set(portfolio_id, start_date, end_date, benchmark_symbol, result)
        return result

    def invalidate_cache(self, portfolio_id: int) -> int:
        """
        Invalidate all cached analytics for a portfolio.

        Call this when transactions are added/modified to ensure
        fresh analytics on next request.

        Args:
            portfolio_id: Portfolio to invalidate

        Returns:
            Number of cache entries invalidated
        """
        return self._cache.invalidate(portfolio_id)

    @classmethod
    def clear_all_cache(cls) -> None:
        """Clear all cached analytics across all portfolios."""
        if cls._shared_cache is not None:
            cls._shared_cache.clear()

    # =========================================================================
    # PRIVATE HELPERS
    # =========================================================================

    def _get_default_benchmark(self, portfolio_currency: str) -> str:
        """
        Get default benchmark symbol based on portfolio currency.

        Args:
            portfolio_currency: Portfolio's base currency (e.g., "EUR", "USD")

        Returns:
            Default benchmark ticker for that currency
        """
        return DEFAULT_BENCHMARKS.get(
            portfolio_currency.upper(),
            DEFAULT_BENCHMARKS["DEFAULT"]
        )

    def _get_daily_values(
            self,
            db: Session,
            portfolio_id: int,
            start_date: date,
            end_date: date,
            history: PortfolioHistory | None = None,
    ) -> list[DailyValue]:
        """
        Get daily portfolio values for analytics calculations.

        IMPORTANT: Always uses daily interval internally.
        Risk metrics (Volatility, Sharpe, Beta) require daily data points.

        Converts PortfolioHistory to list of DailyValue for calculators.

        CRITICAL FIX: Cash flows from transaction dates without equity data
        are assigned to the NEXT date with valid equity. This ensures all
        cash flows are counted for TWR/deposit/withdrawal calculations.

        Args:
            db: Database session
            portfolio_id: Portfolio ID
            start_date: Start date for analysis
            end_date: End date for analysis
            history: Optional pre-fetched history to avoid duplicate DB calls.
                     If not provided, will fetch from ValuationService.
        """
        try:
            # Use provided history or fetch if not provided
            # This optimization avoids duplicate get_history calls
            if history is None:
                # CRITICAL: Always use daily interval for risk metrics
                history = self._valuation_service.get_history(
                    db=db,
                    portfolio_id=portfolio_id,
                    start_date=start_date,
                    end_date=end_date,
                    interval=_INTERNAL_INTERVAL,  # Always "daily"
                )

            # Step 1: Build list of DailyValue for dates with valid equity
            daily_values = []
            for point in history.data:
                if point.equity is not None:
                    daily_values.append(DailyValue(
                        date=point.date,
                        value=point.equity,
                        cash_flow=Decimal("0"),
                    ))

            if not daily_values:
                return []

            # Step 2: Get ALL cash flows from transactions
            cash_flow_map = self._get_cash_flow_map(db, portfolio_id, start_date, end_date)

            if not cash_flow_map:
                return daily_values

            # Step 3: Build a sorted list of dates that have DailyValue entries
            daily_value_dates = sorted(dv.date for dv in daily_values)
            date_to_index = {dv.date: i for i, dv in enumerate(daily_values)}

            # Step 4: Assign each cash flow to the appropriate DailyValue
            # If the cash flow date has a DailyValue, assign directly.
            # If not, assign to the NEXT date with a DailyValue.
            # This handles weekends, holidays, and missing market data.

            for cf_date, cf_amount in cash_flow_map.items():
                if cf_date in date_to_index:
                    # Exact match - assign directly
                    daily_values[date_to_index[cf_date]].cash_flow += cf_amount
                else:
                    # Find the next date with valid equity
                    # Use binary search for efficiency
                    next_date = None
                    for dv_date in daily_value_dates:
                        if dv_date > cf_date:
                            next_date = dv_date
                            break

                    if next_date is not None:
                        # Assign to next available date
                        daily_values[date_to_index[next_date]].cash_flow += cf_amount
                        logger.debug(
                            f"Cash flow on {cf_date} ({cf_amount}) assigned to {next_date} "
                            f"(no equity on transaction date)"
                        )
                    elif daily_values:
                        # No future date - assign to last available date
                        # This handles edge case of transactions after last market data
                        daily_values[-1].cash_flow += cf_amount
                        logger.debug(
                            f"Cash flow on {cf_date} ({cf_amount}) assigned to last date "
                            f"{daily_values[-1].date} (no future equity data)"
                        )

            return daily_values

        except Exception as e:
            logger.error(f"Error getting daily values: {e}", exc_info=True)
            return []

    def _calculate_cash_flow_amount(
            self,
            txn: Transaction,
            has_cash_tracking: bool,
    ) -> Decimal | None:
        """
        Calculate cash flow amount for a transaction in portfolio currency.

        Returns signed amount (positive = money in, negative = money out),
        or None if transaction type is not a cash flow in this mode.

        Args:
            txn: Transaction to process
            has_cash_tracking: True if portfolio uses DEPOSIT/WITHDRAWAL

        Returns:
            Cash flow amount in portfolio currency, or None if not applicable
        """
        exchange_rate = txn.exchange_rate or Decimal("1")

        if has_cash_tracking:
            # Cash tracking mode: only DEPOSIT/WITHDRAWAL are external cash flows
            if txn.transaction_type == TransactionType.DEPOSIT:
                return txn.quantity / exchange_rate
            elif txn.transaction_type == TransactionType.WITHDRAWAL:
                return -txn.quantity / exchange_rate
        else:
            # Non-cash tracking mode: BUY/SELL are external cash flows
            if txn.transaction_type == TransactionType.BUY:
                # Cost includes fee: qty × price + fee
                txn_value_local = (txn.quantity * txn.price_per_share) + txn.fee
                return txn_value_local / exchange_rate
            elif txn.transaction_type == TransactionType.SELL:
                # Proceeds excludes fee: qty × price - fee
                txn_value_local = (txn.quantity * txn.price_per_share) - txn.fee
                return -txn_value_local / exchange_rate

        return None

    def _get_cash_flows(
            self,
            db: Session,
            portfolio_id: int,
            start_date: date,
            end_date: date,
    ) -> list[CashFlow]:
        """
        Extract cash flows from transactions for TWR and XIRR calculations.

        Cash flow handling depends on whether portfolio tracks cash:

        Portfolio WITH cash tracking (has DEPOSIT/WITHDRAWAL):
            - DEPOSIT = money into portfolio (positive)
            - WITHDRAWAL = money out of portfolio (negative)
            - BUY/SELL are internal movements (cash ↔ assets), not cash flows

        Portfolio WITHOUT cash tracking (no DEPOSIT/WITHDRAWAL):
            - BUY = money into portfolio (positive) - investor adds money
            - SELL = money out of portfolio (negative) - investor removes money

        Returns:
            List of CashFlow objects with date and amount
        """
        # Check if portfolio has DEPOSIT/WITHDRAWAL transactions
        deposit_withdrawal_stmt = select(Transaction).where(
            Transaction.portfolio_id == portfolio_id,
            Transaction.transaction_type.in_([
                TransactionType.DEPOSIT,
                TransactionType.WITHDRAWAL,
            ])
        ).limit(1)

        has_cash_tracking = db.execute(deposit_withdrawal_stmt).scalar() is not None

        # Select transaction types based on cash tracking mode
        if has_cash_tracking:
            txn_types = [TransactionType.DEPOSIT, TransactionType.WITHDRAWAL]
        else:
            txn_types = [TransactionType.BUY, TransactionType.SELL]

        stmt = select(Transaction).where(
            Transaction.portfolio_id == portfolio_id,
            Transaction.date >= start_date,
            Transaction.date <= end_date,
            Transaction.transaction_type.in_(txn_types)
        ).order_by(Transaction.date)

        transactions = db.execute(stmt).scalars().all()

        cash_flows = []
        for txn in transactions:
            amount = self._calculate_cash_flow_amount(txn, has_cash_tracking)
            if amount is not None:
                cash_flows.append(CashFlow(date=txn.date.date(), amount=amount))

        return cash_flows

    def _get_cash_flow_map(
            self,
            db: Session,
            portfolio_id: int,
            start_date: date,
            end_date: date,
    ) -> dict[date, Decimal]:
        """Get cash flows grouped by date."""
        cash_flows = self._get_cash_flows(db, portfolio_id, start_date, end_date)

        result = {}
        for cf in cash_flows:
            if cf.date in result:
                result[cf.date] += cf.amount
            else:
                result[cf.date] = cf.amount

        return result

    def _get_benchmark_prices(
            self,
            db: Session,
            symbol: str,
            start_date: date,
            end_date: date,
    ) -> dict[date, Decimal]:
        """
        Get benchmark prices from database.

        IMPORTANT: Benchmark must exist as an Asset and have synced market data.
        If not found, raises BenchmarkNotSyncedError with clear instructions.

        Args:
            db: Database session
            symbol: Benchmark ticker (e.g., "^SPX", "IWDA.AS")
            start_date: Start of date range
            end_date: End of date range

        Returns:
            Dict mapping date to closing price

        Raises:
            BenchmarkNotSyncedError: If benchmark not found or has no price data
        """
        # Find the benchmark asset
        asset = db.execute(
            select(Asset).where(Asset.ticker == symbol.upper())
        ).scalar()

        if not asset:
            raise BenchmarkNotSyncedError(
                symbol=symbol,
                message=(
                    f"Benchmark '{symbol}' not found in database. "
                    f"Add it as an asset and run market data sync first. "
                    f"Tip: POST /assets/ to create, then POST /portfolios/{{id}}/sync"
                )
            )

        # Get market data (exclude no_data_available placeholders)
        stmt = select(MarketData).where(
            MarketData.asset_id == asset.id,
            MarketData.date >= start_date,
            MarketData.date <= end_date,
            MarketData.no_data_available == False,
        ).order_by(MarketData.date)

        market_data = db.execute(stmt).scalars().all()

        if not market_data:
            raise BenchmarkNotSyncedError(
                symbol=symbol,
                message=(
                    f"Benchmark '{symbol}' exists but has no price data for "
                    f"{start_date} to {end_date}. Run market data sync first. "
                    f"Tip: POST /portfolios/{{id}}/sync"
                )
            )

        return {md.date: md.close_price for md in market_data if md.close_price}

    def _annualize_return(self, total_return: Decimal, days: int) -> Decimal:
        """
        Annualize a return using Decimal arithmetic for precision.

        Formula: (1 + r)^(365/days) - 1

        Uses Python's Decimal.__pow__() which supports non-integer exponents,
        maintaining full precision without float conversion.

        Args:
            total_return: Total return as decimal (e.g., 0.15 = 15%)
            days: Number of calendar days in the period

        Returns:
            Annualized return as Decimal
        """
        if days <= 0:
            return total_return

        base = Decimal("1") + total_return
        if base <= 0:
            return Decimal("-1")  # Total loss

        exponent = Decimal("365") / Decimal(str(days))

        # Use Decimal power operation for full precision.
        # Decimal.__pow__() supports non-integer exponents.
        try:
            return base ** exponent - Decimal("1")
        except decimal.InvalidOperation:
            # Fallback to float for edge cases (extremely large/small values)
            # This should rarely if ever occur in normal financial calculations
            return Decimal(str(float(base) ** float(exponent))) - Decimal("1")

    def _build_not_found_result(
            self,
            portfolio_id: int,
            start_date: date,
            end_date: date,
    ) -> AnalyticsResult:
        """Build result for non-existent portfolio."""
        return AnalyticsResult(
            portfolio_id=portfolio_id,
            portfolio_currency="EUR",
            period=AnalyticsPeriod(
                from_date=start_date,
                to_date=end_date,
                trading_days=0,
                calendar_days=0,
            ),
            performance=PerformanceMetrics(has_sufficient_data=False),
            risk=RiskMetrics(has_sufficient_data=False),
            has_complete_data=False,
            warnings=["Portfolio not found"],
        )

    def _add_scope_warning_if_needed(
            self,
            performance: PerformanceMetrics,
            daily_values: list[DailyValue],
            filtered_daily_values: list[DailyValue],
            scope: str,
    ) -> None:
        """Add warning if multiple investment periods detected."""
        if scope == "current_period" and len(daily_values) != len(filtered_daily_values):
            zero_value_days = sum(1 for dv in daily_values if dv.value <= 0)
            if zero_value_days > 0:
                performance.warnings.append(
                    f"TWR calculated for current investment period only. "
                    f"Portfolio had {zero_value_days} zero-equity days (full liquidation). "
                    f"Use scope=full_history to chain all active periods."
                )

    def _calculate_performance_metrics(
            self,
            db: Session,
            portfolio_id: int,
            start_date: date,
            end_date: date,
            daily_values: list[DailyValue],
            cost_basis: Decimal | None,
            realized_pnl: Decimal | None,
            scope: str,
    ) -> PerformanceMetrics:
        """Calculate performance metrics with cash flow adjustments."""
        # Get cash flows during the period
        cash_flows = self._get_cash_flows(db, portfolio_id, start_date, end_date)

        if daily_values:
            # Add start value as positive cash flow (capital already invested at period start)
            # This is essential for XIRR when the portfolio had value before the period began
            if daily_values[0].value > 0:
                cash_flows.insert(0, CashFlow(
                    date=daily_values[0].date,
                    amount=daily_values[0].value,  # Positive = money in
                ))

            # Add end value as negative cash flow (what you'd get if you sold everything)
            cash_flows.append(CashFlow(
                date=daily_values[-1].date,
                amount=-daily_values[-1].value,  # Negative = money out
            ))

        # Filter to active periods (GIPS-compliant)
        filtered_daily_values = self._filter_to_active_periods(daily_values, scope)

        # Calculate
        performance = ReturnsCalculator.calculate_all(
            filtered_daily_values,
            cash_flows,
            cost_basis=cost_basis,
            realized_pnl=realized_pnl,
        )

        # Add scope warning if needed
        self._add_scope_warning_if_needed(performance, daily_values, filtered_daily_values, scope)

        return performance

    def _filter_to_active_periods(
            self,
            daily_values: list[DailyValue],
            scope: str,
    ) -> list[DailyValue]:
        """
        Filter daily values to exclude zero-equity periods (full liquidation gaps).

        For scope='current_period': Returns only the current (most recent) investment period.
        For scope='full_history': Returns all days with positive equity (chains active periods).

        Investment periods are separated by days where portfolio equity is zero
        (full liquidation). This is GIPS-compliant handling.

        Args:
            daily_values: Full list of daily values (may include zero-value days)
            scope: 'current_period' or 'full_history'

        Returns:
            Filtered list of DailyValue with only active investment days
        """
        if not daily_values:
            return []

        # Sort by date
        sorted_values = sorted(daily_values, key=lambda x: x.date)

        # Identify investment periods (contiguous days with positive equity)
        periods: list[list[DailyValue]] = []
        current_period: list[DailyValue] = []

        for dv in sorted_values:
            if dv.value > 0:
                # Active day - add to current period
                current_period.append(dv)
            else:
                # Zero/negative value - end of period (if any)
                if current_period:
                    periods.append(current_period)
                    current_period = []

        # Don't forget the last period
        if current_period:
            periods.append(current_period)

        if not periods:
            return []

        if scope == "current_period":
            # Return only the most recent (last) investment period
            logger.debug(
                f"Filtering to current period: {len(periods[-1])} days "
                f"(from {periods[-1][0].date} to {periods[-1][-1].date})"
            )
            return periods[-1]
        else:
            # full_history: Chain all active periods together (skip gaps)
            all_active = []
            for period in periods:
                all_active.extend(period)
            logger.debug(
                f"Chaining {len(periods)} investment periods: {len(all_active)} total active days"
            )
            return all_active

    def _build_synthetic_details_dict(
            self,
            history: PortfolioHistory,
    ) -> dict[str, dict]:
        """Convert SyntheticAssetDetail objects to dicts for JSON serialization."""
        if not history.has_synthetic_data:
            return {}
        if not hasattr(history, 'synthetic_details') or not history.synthetic_details:
            return {}

        return {
            ticker: {
                "ticker": detail.ticker,
                "proxy_ticker": detail.proxy_ticker,
                "first_synthetic_date": detail.first_synthetic_date,
                "last_synthetic_date": detail.last_synthetic_date,
                "synthetic_days": detail.synthetic_days,
                "total_days_held": detail.total_days_held,
                "percentage": detail.percentage,
                "synthetic_method": detail.synthetic_method,
            }
            for ticker, detail in history.synthetic_details.items()
        }

    def _build_analytics_result(
            self,
            portfolio: Portfolio,
            portfolio_id: int,
            start_date: date,
            end_date: date,
            daily_values: list[DailyValue],
            history: PortfolioHistory,
            performance: PerformanceMetrics,
            risk: RiskMetrics,
            benchmark: BenchmarkMetrics | None,
    ) -> AnalyticsResult:
        """Build the final AnalyticsResult with all components."""
        # Build period info
        period = AnalyticsPeriod(
            from_date=start_date,
            to_date=end_date,
            trading_days=len(daily_values),
            calendar_days=(end_date - start_date).days,
        )

        # Aggregate warnings
        all_warnings = []
        all_warnings.extend(performance.warnings)
        all_warnings.extend(risk.warnings)
        if benchmark:
            all_warnings.extend(benchmark.warnings)

        # Check completeness
        has_complete = (
            performance.has_sufficient_data and
            risk.has_sufficient_data and
            (benchmark is None or benchmark.has_sufficient_data)
        )

        # Build synthetic details
        synthetic_details_dict = self._build_synthetic_details_dict(history)

        return AnalyticsResult(
            portfolio_id=portfolio_id,
            portfolio_currency=portfolio.currency,
            period=period,
            performance=performance,
            risk=risk,
            benchmark=benchmark,
            has_complete_data=has_complete,
            warnings=all_warnings,
            has_synthetic_data=history.has_synthetic_data,
            synthetic_data_percentage=history.synthetic_percentage if history.has_synthetic_data else None,
            synthetic_holdings=history.synthetic_holdings if history.has_synthetic_data else {},
            synthetic_date_range=history.synthetic_date_range,
            synthetic_details=synthetic_details_dict,
            reliability_notes=self._generate_reliability_notes(
                history.synthetic_percentage
            ) if history.has_synthetic_data else [],
        )

    def _generate_reliability_notes(
            self,
            synthetic_percentage: Decimal | None,
    ) -> list[str]:
        """
        Generate reliability notes based on synthetic data percentage.

        Args:
            synthetic_percentage: Percentage of data points that are synthetic

        Returns:
            List of warning/informational notes about data reliability
        """
        notes: list[str] = []

        if synthetic_percentage is None or synthetic_percentage == Decimal("0"):
            return notes

        if synthetic_percentage >= SYNTHETIC_CRITICAL_THRESHOLD:
            notes.append(
                f"⚠️ CRITICAL: {synthetic_percentage}% of price data is synthetic "
                f"(proxy-backcast). Performance and risk metrics may not reflect "
                f"actual historical behavior. Use with extreme caution."
            )
            notes.append(
                "Risk metrics (Volatility, Sharpe, Sortino, VaR) are based primarily "
                "on proxy asset characteristics, not actual asset performance."
            )
            notes.append(
                "Beta and Alpha calculations may be invalid if synthetic data "
                "was derived from the benchmark or correlated assets."
            )
        elif synthetic_percentage >= SYNTHETIC_WARNING_THRESHOLD:
            notes.append(
                f"⚠️ WARNING: {synthetic_percentage}% of price data is synthetic "
                f"(proxy-backcast). Some metrics may have reduced accuracy."
            )
            notes.append(
                "Risk metrics incorporate estimated volatility from proxy assets "
                "for periods with missing data."
            )
        else:
            # Low percentage - informational only
            notes.append(
                f"ℹ️ {synthetic_percentage}% of price data is synthetic (proxy-backcast). "
                f"Impact on metrics is minimal."
            )

        return notes

    def _build_insufficient_benchmark_result(
            self,
            benchmark_symbol: str,
            warning: str,
    ) -> BenchmarkMetrics:
        """Build a BenchmarkMetrics result for insufficient data cases."""
        return BenchmarkMetrics(
            benchmark_symbol=benchmark_symbol,
            has_sufficient_data=False,
            warnings=[warning],
        )

    def _align_portfolio_and_benchmark(
            self,
            portfolio_values: list[DailyValue],
            benchmark_prices: dict[date, Decimal],
    ) -> tuple[list[date], list[Decimal], list[Decimal]] | None:
        """
        Align portfolio and benchmark data by common dates.

        Args:
            portfolio_values: Portfolio daily values
            benchmark_prices: Benchmark prices by date

        Returns:
            Tuple of (common_dates, aligned_portfolio, aligned_benchmark),
            or None if insufficient overlapping data (< 10 days)
        """
        portfolio_by_date = {dv.date: dv.value for dv in portfolio_values}

        common_dates = sorted(
            set(portfolio_by_date.keys()) & set(benchmark_prices.keys())
        )

        if len(common_dates) < 10:
            return None

        aligned_portfolio = [portfolio_by_date[d] for d in common_dates]
        aligned_benchmark = [benchmark_prices[d] for d in common_dates]

        return common_dates, aligned_portfolio, aligned_benchmark
