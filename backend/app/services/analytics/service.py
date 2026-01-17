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
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction, TransactionType, Portfolio, Asset, MarketData
from app.services.analytics.benchmark import BenchmarkCalculator
from app.services.analytics.returns import ReturnsCalculator
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

# Default risk-free rate (2% annual)
DEFAULT_RISK_FREE_RATE = Decimal("0.02")

# Default benchmarks by portfolio currency
# ^SPX = S&P 500 Index
# IWDA.AS = iShares MSCI World ETF (Amsterdam)
DEFAULT_BENCHMARKS: dict[str, str] = {
    "USD": "^SPX",
    "EUR": "IWDA.AS",
    "GBP": "^SPX",  # Fallback to S&P 500
    "CHF": "^SPX",  # Fallback to S&P 500
    "DEFAULT": "^SPX",  # Default fallback
}

# Cache TTL in seconds (1 hour)
CACHE_TTL_SECONDS = 3600


# =============================================================================
# CACHE
# =============================================================================

class AnalyticsCache:
    """
    Simple in-memory TTL cache for analytics results.
    
    Analytics calculations are CPU-intensive, so we cache results
    for 1 hour to avoid redundant recalculation.
    
    Cache key format: "analytics:{portfolio_id}:{start}:{end}:{benchmark}"
    
    Note: This is a simple in-memory cache. For production with multiple
    workers, consider using Redis instead.
    """

    def __init__(self, ttl_seconds: int = CACHE_TTL_SECONDS):
        """
        Initialize cache with TTL.
        
        Args:
            ttl_seconds: Time-to-live in seconds (default 1 hour)
        """
        self._cache: dict[str, tuple[datetime, Any]] = {}
        self._ttl = timedelta(seconds=ttl_seconds)

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
        
        Returns:
            Cached AnalyticsResult or None if not found/expired
        """
        key = self._make_key(portfolio_id, start_date, end_date, benchmark)

        if key in self._cache:
            timestamp, result = self._cache[key]
            if datetime.now() - timestamp < self._ttl:
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
        """Store result in cache."""
        key = self._make_key(portfolio_id, start_date, end_date, benchmark)
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
        keys_to_delete = [k for k in self._cache.keys() if k.startswith(prefix)]

        for key in keys_to_delete:
            del self._cache[key]

        if keys_to_delete:
            logger.debug(f"Invalidated {len(keys_to_delete)} cache entries for portfolio {portfolio_id}")

        return len(keys_to_delete)

    def clear(self) -> None:
        """Clear all cached entries."""
        count = len(self._cache)
        self._cache.clear()
        logger.debug(f"Cleared {count} cache entries")


# =============================================================================
# EXCEPTIONS
# =============================================================================

class BenchmarkNotSyncedError(Exception):
    """
    Raised when benchmark data is not available in the database.
    
    The benchmark must be added as an Asset and its market data
    must be synced before analytics can run.
    """

    def __init__(self, symbol: str, message: str | None = None):
        self.symbol = symbol
        self.message = message or (
            f"Benchmark '{symbol}' not found in database. "
            f"Add it as an asset and run market data sync first."
        )
        super().__init__(self.message)


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
            valuation_service=None,
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

        self._valuation_service = valuation_service

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

        # Add final value as negative cash flow (money out)
        if daily_values:
            cash_flows.append(CashFlow(
                date=daily_values[-1].date,
                amount=-daily_values[-1].value,  # Negative = outflow
            ))

        # Calculate all return metrics
        result = ReturnsCalculator.calculate_all(daily_values, cash_flows)

        return result

    def get_risk(
            self,
            db: Session,
            portfolio_id: int,
            start_date: date,
            end_date: date,
            risk_free_rate: Decimal = DEFAULT_RISK_FREE_RATE,
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

        # Get performance metrics for CAGR (needed for Calmar ratio)
        performance = ReturnsCalculator.calculate_all(daily_values)

        # Calculate all risk metrics
        result = RiskCalculator.calculate_all(
            daily_values=daily_values,
            total_return_annualized=performance.twr_annualized,
            cagr=performance.cagr,
            risk_free_rate=risk_free_rate,
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
            BenchmarkMetrics with comparison analysis.

        Raises:
            BenchmarkNotSyncedError: If benchmark not found or has no data.
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
            return BenchmarkMetrics(
                benchmark_symbol=benchmark_symbol,
                has_sufficient_data=False,
                warnings=["No portfolio valuation data available"],
            )

        # Get benchmark prices (raises BenchmarkNotSyncedError if not found)
        benchmark_prices = self._get_benchmark_prices(
            db, benchmark_symbol, start_date, end_date
        )

        if not benchmark_prices:
            return BenchmarkMetrics(
                benchmark_symbol=benchmark_symbol,
                has_sufficient_data=False,
                warnings=[f"No price data available for benchmark {benchmark_symbol}"],
            )

        # Align dates - only use dates where both have data
        portfolio_by_date = {dv.date: dv.value for dv in portfolio_values}
        benchmark_by_date = benchmark_prices

        common_dates = sorted(
            set(portfolio_by_date.keys()) & set(benchmark_by_date.keys())
        )

        if len(common_dates) < 10:
            return BenchmarkMetrics(
                benchmark_symbol=benchmark_symbol,
                has_sufficient_data=False,
                warnings=["Insufficient overlapping data between portfolio and benchmark"],
            )

        # Build aligned series
        aligned_portfolio = [portfolio_by_date[d] for d in common_dates]
        aligned_benchmark = [benchmark_by_date[d] for d in common_dates]

        # Calculate returns
        portfolio_returns = self._calculate_returns(aligned_portfolio)
        benchmark_returns = self._calculate_returns(aligned_benchmark)

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
            benchmark_symbol: Optional benchmark for comparison
            risk_free_rate: Annual risk-free rate
            
        Returns:
            AnalyticsResult with all metrics combined
        """
        # Check cache first
        cached_result = self._cache.get(
            portfolio_id, start_date, end_date, benchmark_symbol
        )
        if cached_result is not None:
            logger.info(f"Returning cached analytics for portfolio {portfolio_id}")
            return cached_result

        logger.info(
            f"Calculating full analytics for portfolio {portfolio_id} "
            f"from {start_date} to {end_date}"
        )

        # Get portfolio info
        portfolio = db.get(Portfolio, portfolio_id)
        if not portfolio:
            return AnalyticsResult(
                portfolio_id=portfolio_id,
                portfolio_currency="USD",
                period=AnalyticsPeriod(
                    from_date=start_date,
                    to_date=end_date,
                    trading_days=0,
                    calendar_days=(end_date - start_date).days,
                ),
                performance=PerformanceMetrics(has_sufficient_data=False),
                risk=RiskMetrics(has_sufficient_data=False),
                has_complete_data=False,
                warnings=["Portfolio not found"],
            )

        # Get daily values once (reuse for all calculations)
        daily_values = self._get_daily_values(db, portfolio_id, start_date, end_date)

        # Performance metrics
        cash_flows = self._get_cash_flows(db, portfolio_id, start_date, end_date)
        if daily_values:
            cash_flows.append(CashFlow(
                date=daily_values[-1].date,
                amount=-daily_values[-1].value,
            ))
        performance = ReturnsCalculator.calculate_all(daily_values, cash_flows)

        # Risk metrics
        risk = RiskCalculator.calculate_all(
            daily_values=daily_values,
            total_return_annualized=performance.twr_annualized,
            cagr=performance.cagr,
            risk_free_rate=risk_free_rate,
        )

        # Benchmark (optional)
        benchmark = None
        if benchmark_symbol:
            benchmark = self.get_benchmark(
                db, portfolio_id, start_date, end_date,
                benchmark_symbol, risk_free_rate
            )

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

        has_complete = (
                performance.has_sufficient_data and
                risk.has_sufficient_data and
                (benchmark is None or benchmark.has_sufficient_data)
        )

        result = AnalyticsResult(
            portfolio_id=portfolio_id,
            portfolio_currency=portfolio.currency,
            period=period,
            performance=performance,
            risk=risk,
            benchmark=benchmark,
            has_complete_data=has_complete,
            warnings=all_warnings,
        )

        # Cache the result
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
    ) -> list[DailyValue]:
        """
        Get daily portfolio values from ValuationService.
        
        IMPORTANT: Always uses daily interval internally.
        Risk metrics (Volatility, Sharpe, Beta) require daily data points.
        
        Converts PortfolioHistory to list of DailyValue for calculators.
        """
        try:
            # CRITICAL: Always use daily interval for risk metrics
            history = self._valuation_service.get_history(
                db=db,
                portfolio_id=portfolio_id,
                start_date=start_date,
                end_date=end_date,
                interval=_INTERNAL_INTERVAL,  # Always "daily"
            )

            daily_values = []
            for point in history.data:
                if point.equity is not None:
                    daily_values.append(DailyValue(
                        date=point.date,
                        value=point.equity,
                        cash_flow=Decimal("0"),  # Will be filled from transactions
                    ))

            # Add cash flows from transactions
            cash_flow_map = self._get_cash_flow_map(db, portfolio_id, start_date, end_date)
            for dv in daily_values:
                if dv.date in cash_flow_map:
                    dv.cash_flow = cash_flow_map[dv.date]

            return daily_values

        except Exception as e:
            logger.error(f"Error getting daily values: {e}")
            return []

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
        # First, check if portfolio has DEPOSIT/WITHDRAWAL transactions
        deposit_withdrawal_stmt = select(Transaction).where(
            Transaction.portfolio_id == portfolio_id,
            Transaction.transaction_type.in_([
                TransactionType.DEPOSIT,
                TransactionType.WITHDRAWAL,
            ])
        ).limit(1)

        has_cash_tracking = db.execute(deposit_withdrawal_stmt).scalar() is not None

        if has_cash_tracking:
            # Portfolio tracks cash - use DEPOSIT/WITHDRAWAL only
            stmt = select(Transaction).where(
                Transaction.portfolio_id == portfolio_id,
                Transaction.date >= start_date,
                Transaction.date <= end_date,
                Transaction.transaction_type.in_([
                    TransactionType.DEPOSIT,
                    TransactionType.WITHDRAWAL,
                ])
            ).order_by(Transaction.date)

            transactions = db.execute(stmt).scalars().all()

            cash_flows = []
            for txn in transactions:
                if txn.transaction_type == TransactionType.DEPOSIT:
                    # Money into portfolio (positive cash flow)
                    amount = txn.quantity * txn.exchange_rate
                    cash_flows.append(CashFlow(date=txn.date.date(), amount=amount))
                elif txn.transaction_type == TransactionType.WITHDRAWAL:
                    # Money out of portfolio (negative cash flow)
                    amount = -txn.quantity * txn.exchange_rate
                    cash_flows.append(CashFlow(date=txn.date.date(), amount=amount))

        else:
            # Portfolio does NOT track cash - use BUY/SELL as cash flows
            # BUY = investor adds money, SELL = investor removes money
            stmt = select(Transaction).where(
                Transaction.portfolio_id == portfolio_id,
                Transaction.date >= start_date,
                Transaction.date <= end_date,
                Transaction.transaction_type.in_([
                    TransactionType.BUY,
                    TransactionType.SELL,
                ])
            ).order_by(Transaction.date)

            transactions = db.execute(stmt).scalars().all()

            cash_flows = []
            for txn in transactions:
                # Calculate transaction value in portfolio currency
                txn_value = txn.quantity * txn.price_per_share * txn.exchange_rate

                if txn.transaction_type == TransactionType.BUY:
                    # Money INTO portfolio (investor adds money to buy assets)
                    cash_flows.append(CashFlow(date=txn.date.date(), amount=txn_value))
                elif txn.transaction_type == TransactionType.SELL:
                    # Money OUT of portfolio (investor removes money from selling)
                    cash_flows.append(CashFlow(date=txn.date.date(), amount=-txn_value))

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

        # Get market data
        stmt = select(MarketData).where(
            MarketData.asset_id == asset.id,
            MarketData.date >= start_date,
            MarketData.date <= end_date,
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

    def _calculate_returns(self, values: list[Decimal]) -> list[Decimal]:
        """Calculate period-over-period returns."""
        if len(values) < 2:
            return []

        returns = []
        for i in range(1, len(values)):
            if values[i - 1] != 0:
                ret = (values[i] - values[i - 1]) / values[i - 1]
                returns.append(ret)

        return returns

    def _annualize_return(self, total_return: Decimal, days: int) -> Decimal:
        """Annualize a return."""
        if days <= 0:
            return total_return

        base = Decimal("1") + total_return
        if base <= 0:
            return Decimal("-1")

        exponent = Decimal("365") / Decimal(str(days))
        return Decimal(str(float(base) ** float(exponent))) - Decimal("1")
