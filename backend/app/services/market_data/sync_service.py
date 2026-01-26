# backend/app/services/market_data/sync_service.py
"""
Market Data Sync Service for orchestrating portfolio data synchronization.

This service handles:
- Analyzing portfolio to determine sync requirements
- Fetching missing OHLCV price data for all assets
- Fetching FX rates via FXRateService
- Tracking sync status and coverage
- Staleness detection for hybrid sync trigger

Design Principles:
- Single Responsibility: Orchestrates sync, delegates to specialized services
- Dependency Injection: Provider and FX service injected via constructor
- No HTTP Knowledge: Raises domain exceptions, not HTTPException
- Partial Success: Continues if some assets fail, reports warnings
- Idempotent: Safe to call multiple times (incremental sync)

Usage:
    from app.services.market_data import MarketDataSyncService

    service = MarketDataSyncService()

    # Check if data is stale
    is_stale, reason = service.is_data_stale(db, portfolio_id)

    # Sync portfolio data
    result = service.sync_portfolio(db, portfolio_id)

    if result.status == "completed":
        print(f"Synced {result.prices_fetched} prices")
    else:
        print(f"Warnings: {result.warnings}")
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select, func, and_, update, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    Transaction,
    TransactionType,
    Portfolio,
    MarketData,
    SyncStatus,
    SyncStatusEnum,
)
from app.services.fx_rate_service import FXRateService
from app.services.market_data.base import (
    MarketDataProvider,
    OHLCVData,
)
from app.services.market_data.yahoo import YahooFinanceProvider
from app.services.portfolio_settings_service import PortfolioSettingsService
from app.schemas.portfolio_settings import BackcastingMethod
from app.services.proxy_mapping_service import ProxyMappingService, ProxyMappingResult
from app.services.constants import DEFAULT_STALENESS_HOURS
from app.utils.date_utils import get_business_days

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class AssetSyncInfo:
    """Information about an asset to sync."""

    asset_id: int
    ticker: str
    exchange: str
    currency: str
    first_transaction_date: date


@dataclass
class PortfolioAnalysis:
    """Result of analyzing a portfolio for sync requirements."""

    portfolio_id: int
    portfolio_currency: str
    assets: list[AssetSyncInfo] = field(default_factory=list)
    earliest_date: date | None = None
    latest_date: date | None = None  # Usually today
    currencies_needed: set[str] = field(default_factory=set)
    fx_pairs_needed: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class AssetSyncResult:
    """Result of syncing a single asset."""

    asset_id: int
    ticker: str
    exchange: str
    success: bool = True
    prices_fetched: int = 0
    from_date: date | None = None
    to_date: date | None = None
    error: str | None = None


@dataclass
class SyncResult:
    """Complete result of a portfolio sync operation."""

    portfolio_id: int
    status: str  # "completed", "partial", "failed"
    sync_started: datetime
    sync_completed: datetime | None = None

    # Statistics
    assets_synced: int = 0
    assets_failed: int = 0
    prices_fetched: int = 0
    fx_pairs_synced: int = 0
    fx_rates_fetched: int = 0

    # Backcasting results
    backcasting_enabled: bool = False
    proxies_applied: int = 0
    assets_backcast: int = 0
    synthetic_prices_created: int = 0
    proxy_mapping_result: ProxyMappingResult | None = None

    # Date range
    from_date: date | None = None
    to_date: date | None = None

    # Details
    asset_results: list[AssetSyncResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    # Coverage summary (for storage in sync_status)
    coverage_summary: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# SYNC SERVICE
# =============================================================================

class MarketDataSyncService:
    """
    Orchestrates market data synchronization for portfolios.

    This service is the main entry point for syncing market data. It:
    1. Analyzes the portfolio to determine what data is needed
    2. Fetches missing price data for each asset
    3. Fetches missing FX rates
    4. Updates the sync status

    Attributes:
        _provider: Market data provider for fetching prices
        _fx_service: FX rate service for fetching exchange rates
        _staleness_threshold_hours: Hours after which data is considered stale

    Example:
        service = MarketDataSyncService()

        # Full sync
        result = service.sync_portfolio(db, portfolio_id=1)

        # Force re-fetch
        result = service.sync_portfolio(db, portfolio_id=1, force=True)

        # Check staleness
        is_stale, reason = service.is_data_stale(db, portfolio_id=1)
    """

    def __init__(
            self,
            provider: MarketDataProvider | None = None,
            fx_service: FXRateService | None = None,
            settings_service: PortfolioSettingsService | None = None,
            proxy_mapping_service: ProxyMappingService | None = None,
            staleness_threshold_hours: int | None = None,
    ) -> None:
        """
        Initialize the market data sync service.

        Args:
            provider: Market data provider (defaults to YahooFinanceProvider)
            fx_service: FX rate service (defaults to new FXRateService with same provider)
            settings_service: Portfolio settings service (defaults to new instance)
            proxy_mapping_service: Proxy mapping service (defaults to new instance)
            staleness_threshold_hours: Hours after which data is stale (default: 24)
        """
        self._provider = provider or YahooFinanceProvider()
        self._fx_service = fx_service or FXRateService(provider=self._provider)
        self._settings_service = settings_service or PortfolioSettingsService()
        self._proxy_mapping_service = proxy_mapping_service or ProxyMappingService()
        self._staleness_threshold_hours = (
                staleness_threshold_hours or DEFAULT_STALENESS_HOURS
        )

        logger.info(
            f"MarketDataSyncService initialized "
            f"(provider={self._provider.name}, "
            f"staleness_threshold={self._staleness_threshold_hours}h)"
        )

    # =========================================================================
    # MAIN SYNC METHOD
    # =========================================================================

    def sync_portfolio(
            self,
            db: Session,
            portfolio_id: int,
            force: bool = False,
    ) -> SyncResult:
        """
        Sync all market data for a portfolio.

        This is the main entry point. It:
        1. Sets sync status to IN_PROGRESS
        2. Analyzes portfolio (assets, dates, currencies)
        2b. Check backcasting settings (NEW)
        2c. Apply proxy mappings if enabled (NEW)
        3. Fetches missing price data for each asset
        4. Fetches missing FX rates
        5. Backcast with proxies if enabled (NEW)
        6. Updates sync status to COMPLETED/PARTIAL/FAILED

        Args:
            db: Database session
            portfolio_id: Portfolio to sync
            force: If True, re-fetch all data (ignore existing)

        Returns:
            SyncResult with statistics and any warnings
        """
        sync_started = datetime.now(timezone.utc)

        result = SyncResult(
            portfolio_id=portfolio_id,
            status="in_progress",
            sync_started=sync_started,
        )

        try:
            # 1. Atomically acquire sync job (prevents duplicate concurrent syncs)
            job_acquired = self._try_acquire_sync_job(db, portfolio_id, sync_started)

            if not job_acquired:
                logger.info(
                    f"Sync already in progress for portfolio {portfolio_id}, skipping"
                )
                result.status = "already_running"
                result.sync_completed = datetime.now(timezone.utc)
                result.warnings.append(
                    "Another sync is already in progress for this portfolio"
                )
                return result

            # 2. Analyze portfolio
            analysis = self.analyze_portfolio(db, portfolio_id)

            if not analysis.assets:
                logger.info(f"Portfolio {portfolio_id} has no assets to sync")
                result.status = "completed"
                result.sync_completed = datetime.now(timezone.utc)
                self._update_sync_status(
                    db, portfolio_id,
                    status=SyncStatusEnum.COMPLETED,
                    sync_completed=result.sync_completed,
                    coverage_summary={"assets": [], "fx_pairs": []},
                )
                return result

            result.from_date = analysis.earliest_date
            result.to_date = analysis.latest_date

            # 2b. Check backcasting setting
            backcasting_method = self._settings_service.get_backcasting_method(
                db, portfolio_id
            )
            # For backwards compatibility with result field
            result.backcasting_enabled = backcasting_method != BackcastingMethod.DISABLED

            # 2c. Apply proxy mappings if backcasting is proxy_preferred
            if backcasting_method == BackcastingMethod.PROXY_PREFERRED:
                logger.info(f"Applying proxy mappings for portfolio {portfolio_id}")
                # Batch fetch all assets (avoid N+1 queries)
                asset_ids = [a.asset_id for a in analysis.assets]
                assets_for_proxy = db.scalars(
                    select(Asset).where(Asset.id.in_(asset_ids))
                ).all()
                proxy_result = self._proxy_mapping_service.apply_mappings(
                    db,
                    list(assets_for_proxy)
                )
                result.proxy_mapping_result = proxy_result
                result.proxies_applied = proxy_result.total_applied
                result.warnings.extend(proxy_result.warnings)

                if proxy_result.total_applied > 0:
                    logger.info(
                        f"Applied {proxy_result.total_applied} proxy mappings"
                    )

            # 3. Sync price data for each asset (with batched commits)
            # Accumulate all prices first, then commit in batches for efficiency
            # This reduces database round-trips while still allowing partial success
            accumulated_prices: list[tuple[int, list[OHLCVData]]] = []

            for asset_info in analysis.assets:
                asset_result = self._sync_asset_prices_no_commit(
                    db=db,
                    asset_info=asset_info,
                    end_date=analysis.latest_date or date.today(),
                    force=force,
                    accumulated_prices=accumulated_prices,
                )
                result.asset_results.append(asset_result)

                if asset_result.success:
                    result.assets_synced += 1
                    result.prices_fetched += asset_result.prices_fetched
                else:
                    result.assets_failed += 1
                    result.warnings.append(
                        f"Failed to sync {asset_info.ticker}: {asset_result.error}"
                    )

            # Batch commit all accumulated prices
            if accumulated_prices:
                self._store_prices_batch(db, accumulated_prices)

            # 4. Sync FX rates
            if analysis.fx_pairs_needed:
                fx_results = self._fx_service.sync_portfolio_rates(
                    db=db,
                    portfolio_id=portfolio_id,
                    start_date=analysis.earliest_date,
                    end_date=analysis.latest_date or date.today(),
                    force=force,
                )

                for fx_result in fx_results:
                    if fx_result.success:
                        result.fx_pairs_synced += 1
                        result.fx_rates_fetched += fx_result.rates_fetched
                    else:
                        result.warnings.append(
                            f"FX sync warning for "
                            f"{fx_result.base_currency}/{fx_result.quote_currency}: "
                            f"{fx_result.errors}"
                        )

            # 4b. Backcast with proxies if enabled, with cost-carry fallback
            # Only run backcasting when:
            # - force=True (full re-sync requested)
            # - OR any asset has a gap (first_transaction_date < first_real_price_date)
            # This detects assets needing historical data even after prices are fetched
            # Respects backcasting_method setting:
            # - DISABLED: skip entirely
            # - COST_CARRY_ONLY: only run cost-carry
            # - PROXY_PREFERRED: run proxy backcasting first, then cost-carry fallback
            should_backcast = False
            if backcasting_method != BackcastingMethod.DISABLED:
                if force:
                    # Full re-sync always runs backcast
                    should_backcast = True
                    logger.info("Running backcast (force=True)")
                else:
                    # Check if any asset has a gap that needs backcasting
                    # A gap exists when first_transaction_date < first_real_price_date
                    asset_ids = [a.asset_id for a in analysis.assets]

                    # Get first REAL (non-synthetic) price date for each asset
                    # Must also exclude no_data_available records (Yahoo placeholders with no actual prices)
                    first_price_query = db.execute(
                        select(
                            MarketData.asset_id,
                            func.min(MarketData.date).label('first_price_date')
                        )
                        .where(
                            MarketData.asset_id.in_(asset_ids),
                            MarketData.is_synthetic == False,
                            MarketData.no_data_available == False,  # Exclude placeholder records
                        )
                        .group_by(MarketData.asset_id)
                    ).all()

                    first_price_map = {row.asset_id: row.first_price_date for row in first_price_query}

                    # Check if any asset has a gap
                    for asset_info in analysis.assets:
                        first_price = first_price_map.get(asset_info.asset_id)
                        # Gap exists if: no price at all, OR first price is after first transaction
                        if first_price is None or first_price > asset_info.first_transaction_date:
                            should_backcast = True
                            logger.info(
                                f"Running backcast (gap detected: {asset_info.ticker} "
                                f"first_txn={asset_info.first_transaction_date}, "
                                f"first_price={first_price})"
                            )
                            break

            if should_backcast:
                backcast_result = self._backcast_assets_batch(
                    db, analysis.assets, portfolio_id=portfolio_id,
                    backcasting_method=backcasting_method
                )
                result.synthetic_prices_created = backcast_result["total_synthetic"]
                result.assets_backcast = backcast_result["assets_backcast_count"]

                if backcast_result["total_synthetic"] > 0:
                    # Build descriptive warning message
                    parts = []
                    if backcast_result["assets_backcast_count"] > 0:
                        parts.append(
                            f"{backcast_result['assets_backcast_count']} asset(s) using proxy backcasting"
                        )
                    if backcast_result.get("cost_carry_count", 0) > 0:
                        parts.append(
                            f"{backcast_result['cost_carry_count']} asset(s) valued at cost"
                        )

                    result.warnings.append(
                        f"Generated {backcast_result['total_synthetic']} synthetic prices for "
                        + " and ".join(parts)
                    )

            # 5. Determine final status  (was step 5, now renumbered)
            result.sync_completed = datetime.now(timezone.utc)

            if result.assets_failed == 0:
                result.status = "completed"
                final_status = SyncStatusEnum.COMPLETED
            elif result.assets_synced > 0:
                result.status = "partial"
                final_status = SyncStatusEnum.PARTIAL
            else:
                result.status = "failed"
                final_status = SyncStatusEnum.FAILED

            # 6. Build coverage summary
            result.coverage_summary = self._build_coverage_summary(
                db, portfolio_id, analysis, result
            )

            # 7. Update final status
            self._update_sync_status(
                db, portfolio_id,
                status=final_status,
                sync_completed=result.sync_completed,
                coverage_summary=result.coverage_summary,
                last_error=result.warnings[0] if result.warnings else None,
            )

            logger.info(
                f"Sync completed for portfolio {portfolio_id}: "
                f"status={result.status}, "
                f"assets={result.assets_synced}/{len(analysis.assets)}, "
                f"prices={result.prices_fetched}, "
                f"fx_pairs={result.fx_pairs_synced}"
                f"{f', synthetic={result.synthetic_prices_created}' if result.synthetic_prices_created else ''}"
            )

            return result

        except Exception as e:
            logger.error(f"Sync failed for portfolio {portfolio_id}: {e}")
            result.status = "failed"
            result.error = str(e)
            result.sync_completed = datetime.now(timezone.utc)

            self._update_sync_status(
                db, portfolio_id,
                status=SyncStatusEnum.FAILED,
                sync_completed=result.sync_completed,
                last_error=str(e),
            )

            return result

    # =========================================================================
    # STATUS METHODS
    # =========================================================================

    def get_sync_status(
            self,
            db: Session,
            portfolio_id: int,
    ) -> SyncStatus | None:
        """
        Get the current sync status for a portfolio.

        Returns:
            SyncStatus or None if never synced
        """
        return db.scalar(
            select(SyncStatus).where(SyncStatus.portfolio_id == portfolio_id)
        )

    def _try_acquire_sync_job(
            self,
            db: Session,
            portfolio_id: int,
            sync_started: datetime,
    ) -> bool:
        """
        Atomically attempt to acquire a sync job for the portfolio.

        Uses a conditional UPDATE to ensure only one sync can run at a time.
        This prevents race conditions where multiple concurrent requests
        could all start syncing the same portfolio.

        The algorithm:
        1. Try to UPDATE status to IN_PROGRESS only if current status
           is NOT already IN_PROGRESS
        2. If no rows updated, another sync is already running
        3. If row updated (or inserted), we have the job

        Args:
            db: Database session
            portfolio_id: Portfolio to acquire sync job for
            sync_started: Timestamp when sync started

        Returns:
            True if job was acquired, False if another sync is in progress
        """
        # Check if record exists and its current status
        existing = db.scalar(
            select(SyncStatus).where(SyncStatus.portfolio_id == portfolio_id)
        )

        if existing is None:
            # No record exists - create one with IN_PROGRESS status
            # Use database-agnostic approach: INSERT then check
            new_status = SyncStatus(
                portfolio_id=portfolio_id,
                status=SyncStatusEnum.IN_PROGRESS,
                last_sync_started=sync_started,
                coverage_summary={},
            )
            db.add(new_status)
            try:
                db.commit()
                return True
            except Exception:
                # Concurrent insert - rollback and check status
                db.rollback()
                existing = db.scalar(
                    select(SyncStatus).where(SyncStatus.portfolio_id == portfolio_id)
                )
                if existing and existing.status == SyncStatusEnum.IN_PROGRESS:
                    return False
                # Status is not IN_PROGRESS, try conditional update
                pass

        # Record exists - check if already in progress
        if existing and existing.status == SyncStatusEnum.IN_PROGRESS:
            return False

        # Try conditional UPDATE (atomic check-and-set)
        # This UPDATE only succeeds if status is NOT IN_PROGRESS
        stmt = (
            update(SyncStatus)
            .where(
                SyncStatus.portfolio_id == portfolio_id,
                SyncStatus.status != SyncStatusEnum.IN_PROGRESS,
            )
            .values(
                status=SyncStatusEnum.IN_PROGRESS,
                last_sync_started=sync_started,
            )
        )

        result = db.execute(stmt)
        db.commit()

        # rowcount tells us if the UPDATE succeeded
        # If 0 rows updated, status was already IN_PROGRESS (race condition)
        return result.rowcount > 0

    def is_data_stale(
            self,
            db: Session,
            portfolio_id: int,
            threshold_hours: int | None = None,
    ) -> tuple[bool, str]:
        """
        Check if market data is stale and needs refresh.

        Args:
            db: Database session
            portfolio_id: Portfolio to check
            threshold_hours: Override default staleness threshold

        Returns:
            Tuple of (is_stale, reason)

        Examples:
            (True, "never_synced")
            (True, "last_sync_48_hours_ago")
            (True, "last_sync_failed")
            (False, "synced_2_hours_ago")
        """
        threshold = threshold_hours or self._staleness_threshold_hours

        status = self.get_sync_status(db, portfolio_id)

        if status is None:
            return True, "never_synced"

        if status.status == SyncStatusEnum.NEVER:
            return True, "never_synced"

        if status.status == SyncStatusEnum.FAILED:
            return True, "last_sync_failed"

        if status.status == SyncStatusEnum.IN_PROGRESS:
            return False, "sync_in_progress"

        # Check time since last successful sync
        if status.last_sync_completed is None:
            return True, "never_completed"

        now = datetime.now(timezone.utc)

        # Handle timezone-naive datetimes
        last_sync = status.last_sync_completed
        if last_sync.tzinfo is None:
            last_sync = last_sync.replace(tzinfo=timezone.utc)

        hours_since_sync = (now - last_sync).total_seconds() / 3600

        if hours_since_sync > threshold:
            return True, f"last_sync_{int(hours_since_sync)}_hours_ago"

        return False, f"synced_{int(hours_since_sync)}_hours_ago"

    # =========================================================================
    # ANALYSIS METHODS
    # =========================================================================

    def analyze_portfolio(
            self,
            db: Session,
            portfolio_id: int,
    ) -> PortfolioAnalysis:
        """
        Analyze a portfolio to determine sync requirements.

        Queries transactions to find:
        - All unique assets
        - First transaction date for each asset
        - Required FX pairs

        Args:
            db: Database session
            portfolio_id: Portfolio to analyze

        Returns:
            PortfolioAnalysis with sync requirements
        """
        # Get portfolio
        portfolio = db.get(Portfolio, portfolio_id)
        if not portfolio:
            return PortfolioAnalysis(
                portfolio_id=portfolio_id,
                portfolio_currency="EUR",
            )

        analysis = PortfolioAnalysis(
            portfolio_id=portfolio_id,
            portfolio_currency=portfolio.currency.upper(),
        )

        # Query: Get all assets with their first transaction date
        query = (
            select(
                Asset.id,
                Asset.ticker,
                Asset.exchange,
                Asset.currency,
                func.min(Transaction.date).label('first_txn_date'),
            )
            .join(Transaction, Transaction.asset_id == Asset.id)
            .where(Transaction.portfolio_id == portfolio_id)
            .group_by(Asset.id, Asset.ticker, Asset.exchange, Asset.currency)
        )

        results = db.execute(query).all()

        earliest_date = None
        currencies = set()

        for row in results:
            # Handle datetime vs date
            first_txn = row.first_txn_date
            if hasattr(first_txn, 'date'):
                first_txn = first_txn.date()

            asset_info = AssetSyncInfo(
                asset_id=row.id,
                ticker=row.ticker,
                exchange=row.exchange or "",
                currency=row.currency.upper(),
                first_transaction_date=first_txn,
            )
            analysis.assets.append(asset_info)

            currencies.add(asset_info.currency)

            if earliest_date is None or first_txn < earliest_date:
                earliest_date = first_txn

        analysis.earliest_date = earliest_date
        analysis.latest_date = date.today()
        analysis.currencies_needed = currencies

        # Determine FX pairs needed
        for currency in currencies:
            if currency != analysis.portfolio_currency:
                analysis.fx_pairs_needed.append(
                    (currency, analysis.portfolio_currency)
                )

        logger.debug(
            f"Portfolio {portfolio_id} analysis: "
            f"{len(analysis.assets)} assets, "
            f"date range {analysis.earliest_date} to {analysis.latest_date}, "
            f"FX pairs: {analysis.fx_pairs_needed}"
        )

        return analysis

    # =========================================================================
    # PRIVATE METHODS - Price Fetching
    # =========================================================================

    def _sync_asset_prices_no_commit(
            self,
            db: Session,
            asset_info: AssetSyncInfo,
            end_date: date,
            force: bool = False,
            accumulated_prices: list[tuple[int, list[OHLCVData]]] | None = None,
    ) -> AssetSyncResult:
        """
        Fetch prices for a single asset without committing.

        Accumulates prices in the provided list for batch commit later.
        This is more efficient than committing after each asset.

        Also stores "no data" markers for dates that have no market data
        (holidays, weekends, etc.) to prevent repeated API calls.

        Args:
            db: Database session
            asset_info: Asset to sync
            end_date: End date for sync
            force: If True, re-fetch all data (clears no-data markers first)
            accumulated_prices: List to accumulate (asset_id, prices) tuples

        Returns:
            AssetSyncResult with sync outcome
        """
        result = AssetSyncResult(
            asset_id=asset_info.asset_id,
            ticker=asset_info.ticker,
            exchange=asset_info.exchange,
            from_date=asset_info.first_transaction_date,
            to_date=end_date,
        )

        try:
            # For force sync, clear existing no-data markers to allow re-fetching
            if force:
                self._clear_no_data_markers(
                    db,
                    asset_info.asset_id,
                    asset_info.first_transaction_date,
                    end_date,
                )
                date_ranges = [(asset_info.first_transaction_date, end_date)]
            else:
                date_ranges = self._get_missing_date_ranges(
                    db,
                    asset_info.asset_id,
                    asset_info.first_transaction_date,
                    end_date,
                )

            if not date_ranges:
                logger.debug(
                    f"No missing dates for {asset_info.ticker}/{asset_info.exchange}"
                )
                result.success = True
                return result

            # Track all requested dates to identify dates with no data
            all_requested_dates: set[date] = set()
            for start, end in date_ranges:
                all_requested_dates.update(get_business_days(start, end))

            # Fetch prices for each missing range
            total_prices = 0
            all_prices: list[OHLCVData] = []

            for start, end in date_ranges:
                logger.debug(
                    f"Fetching {asset_info.ticker}/{asset_info.exchange}: "
                    f"{start} to {end}"
                )

                prices_result = self._provider.get_historical_prices(
                    ticker=asset_info.ticker,
                    exchange=asset_info.exchange,
                    start_date=start,
                    end_date=end,
                )

                if not prices_result.success:
                    result.success = False
                    result.error = prices_result.error
                    return result

                if prices_result.prices:
                    all_prices.extend(prices_result.prices)
                    total_prices += len(prices_result.prices)

            # Accumulate for batch commit (if accumulator provided)
            if all_prices:
                if accumulated_prices is not None:
                    accumulated_prices.append((asset_info.asset_id, all_prices))
                else:
                    # Fallback: commit immediately if no accumulator
                    self._store_prices(db, asset_info.asset_id, all_prices)

            # Identify dates that were requested but had no data returned
            dates_with_data = {p.date for p in all_prices}
            dates_with_no_data = sorted(all_requested_dates - dates_with_data)

            # Store "no data" markers to prevent re-fetching these dates
            if dates_with_no_data:
                self._store_no_data_markers(db, asset_info.asset_id, dates_with_no_data)
                logger.debug(
                    f"Marked {len(dates_with_no_data)} dates as no-data for "
                    f"{asset_info.ticker}/{asset_info.exchange}"
                )

            result.prices_fetched = total_prices
            result.success = True

            logger.info(
                f"Fetched {asset_info.ticker}/{asset_info.exchange}: "
                f"{total_prices} prices, {len(dates_with_no_data)} no-data markers"
            )

            return result

        except Exception as e:
            logger.error(
                f"Error syncing {asset_info.ticker}/{asset_info.exchange}: {e}"
            )
            result.success = False
            result.error = str(e)
            return result

    def _store_prices_batch(
            self,
            db: Session,
            accumulated_prices: list[tuple[int, list[OHLCVData]]],
    ) -> int:
        """
        Store accumulated prices for multiple assets in a single transaction.

        More efficient than individual commits per asset.

        Args:
            db: Database session
            accumulated_prices: List of (asset_id, prices) tuples

        Returns:
            Total number of records stored
        """
        if not accumulated_prices:
            return 0

        total_stored = 0
        all_records = []

        # Check if OHLC columns exist
        has_ohlc = hasattr(MarketData, 'open_price')
        provider_name = getattr(self._provider, 'name', 'unknown')
        if not isinstance(provider_name, str):
            provider_name = str(provider_name) if provider_name else 'unknown'

        # Build all records for bulk insert
        for asset_id, prices in accumulated_prices:
            for p in prices:
                record = {
                    "asset_id": asset_id,
                    "date": p.date,
                    "close_price": p.close,
                    "adjusted_close": p.adjusted_close,
                    "volume": p.volume,
                    "provider": provider_name,
                    "is_synthetic": False,
                    "proxy_source_id": None,
                }

                if has_ohlc:
                    record["open_price"] = p.open
                    record["high_price"] = p.high
                    record["low_price"] = p.low

                all_records.append(record)

        if not all_records:
            return 0

        try:
            # PostgreSQL bulk upsert
            stmt = pg_insert(MarketData).values(all_records)

            update_columns = {
                "close_price": stmt.excluded.close_price,
                "adjusted_close": stmt.excluded.adjusted_close,
                "volume": stmt.excluded.volume,
                "provider": stmt.excluded.provider,
            }

            if has_ohlc:
                update_columns["open_price"] = stmt.excluded.open_price
                update_columns["high_price"] = stmt.excluded.high_price
                update_columns["low_price"] = stmt.excluded.low_price

            upsert_stmt = stmt.on_conflict_do_update(
                index_elements=["asset_id", "date"],
                set_=update_columns,
            )

            db.execute(upsert_stmt)
            db.commit()

            total_stored = len(all_records)
            logger.info(f"Batch stored {total_stored} prices for {len(accumulated_prices)} assets")

            return total_stored

        except Exception as e:
            logger.error(f"Error batch storing prices: {e}")
            db.rollback()
            raise

    def _store_no_data_markers(
            self,
            db: Session,
            asset_id: int,
            dates_with_no_data: list[date],
    ) -> int:
        """
        Store markers for dates where no market data is available.

        These markers prevent repeated API calls for holidays, weekends,
        and dates where assets weren't trading.

        Args:
            db: Database session
            asset_id: Asset ID
            dates_with_no_data: Dates that had no data from API

        Returns:
            Number of markers stored
        """
        if not dates_with_no_data:
            return 0

        provider_name = getattr(self._provider, 'name', 'unknown')
        if not isinstance(provider_name, str):
            provider_name = str(provider_name) if provider_name else 'unknown'

        records = [
            {
                "asset_id": asset_id,
                "date": d,
                "close_price": None,
                "no_data_available": True,
                "provider": provider_name,
                "is_synthetic": False,
            }
            for d in dates_with_no_data
        ]

        try:
            stmt = pg_insert(MarketData).values(records)
            # On conflict, update to mark as no_data_available
            # (in case a previous sync stored partial data)
            upsert_stmt = stmt.on_conflict_do_update(
                index_elements=["asset_id", "date"],
                set_={
                    "no_data_available": True,
                    "close_price": None,
                },
            )
            db.execute(upsert_stmt)
            db.commit()

            logger.debug(f"Stored {len(records)} no-data markers for asset {asset_id}")
            return len(records)

        except Exception as e:
            logger.error(f"Error storing no-data markers: {e}")
            db.rollback()
            return 0

    def _clear_no_data_markers(
            self,
            db: Session,
            asset_id: int,
            start_date: date,
            end_date: date,
    ) -> int:
        """
        Clear no-data markers for an asset to allow re-fetching.

        Used during full re-sync to retry dates that previously had no data.

        Args:
            db: Database session
            asset_id: Asset ID
            start_date: Start of range to clear
            end_date: End of range to clear

        Returns:
            Number of markers cleared
        """
        try:
            result = db.execute(
                MarketData.__table__.delete().where(
                    and_(
                        MarketData.asset_id == asset_id,
                        MarketData.date >= start_date,
                        MarketData.date <= end_date,
                        MarketData.no_data_available == True,
                    )
                )
            )
            db.commit()
            deleted = result.rowcount
            if deleted > 0:
                logger.debug(f"Cleared {deleted} no-data markers for asset {asset_id}")
            return deleted

        except Exception as e:
            logger.error(f"Error clearing no-data markers: {e}")
            db.rollback()
            return 0

    def _sync_asset_prices(
            self,
            db: Session,
            asset_info: AssetSyncInfo,
            end_date: date,
            force: bool = False,
    ) -> AssetSyncResult:
        """
        Fetch and store prices for a single asset.

        Args:
            db: Database session
            asset_info: Asset to sync
            end_date: End date for sync (usually today)
            force: If True, re-fetch all data

        Returns:
            AssetSyncResult with sync outcome
        """
        result = AssetSyncResult(
            asset_id=asset_info.asset_id,
            ticker=asset_info.ticker,
            exchange=asset_info.exchange,
            from_date=asset_info.first_transaction_date,
            to_date=end_date,
        )

        try:
            # Determine what dates need fetching
            if force:
                date_ranges = [(asset_info.first_transaction_date, end_date)]
            else:
                date_ranges = self._get_missing_date_ranges(
                    db,
                    asset_info.asset_id,
                    asset_info.first_transaction_date,
                    end_date,
                )

            if not date_ranges:
                logger.debug(
                    f"No missing dates for {asset_info.ticker}/{asset_info.exchange}"
                )
                result.success = True
                return result

            # Fetch prices for each missing range
            total_prices = 0

            for start, end in date_ranges:
                logger.debug(
                    f"Fetching {asset_info.ticker}/{asset_info.exchange}: "
                    f"{start} to {end}"
                )

                prices_result = self._provider.get_historical_prices(
                    ticker=asset_info.ticker,
                    exchange=asset_info.exchange,
                    start_date=start,
                    end_date=end,
                )

                if not prices_result.success:
                    result.success = False
                    result.error = prices_result.error
                    return result

                if prices_result.prices:
                    # Store prices in database
                    self._store_prices(
                        db,
                        asset_info.asset_id,
                        prices_result.prices,
                    )
                    total_prices += len(prices_result.prices)

            result.prices_fetched = total_prices
            result.success = True

            logger.info(
                f"Synced {asset_info.ticker}/{asset_info.exchange}: "
                f"{total_prices} prices"
            )

            asset = db.get(Asset, asset_info.asset_id)
            if asset and asset.proxy_asset_id:
                # Find the first real price date (exclude no_data_available placeholders)
                first_real = db.execute(
                    select(func.min(MarketData.date))
                    .where(
                        MarketData.asset_id == asset_info.asset_id,
                        MarketData.is_synthetic == False,
                        MarketData.no_data_available == False,
                    )
                ).scalar()

                if first_real and first_real > asset_info.first_transaction_date:
                    # Need to backcast
                    logger.info(
                        f"Asset {asset_info.ticker} needs backcasting: "
                        f"first_txn={asset_info.first_transaction_date}, first_real={first_real}"
                    )

                    # Ensure proxy has data
                    if self._ensure_proxy_data(
                            db, asset.proxy_asset_id,
                            asset_info.first_transaction_date, first_real
                    ):
                        # Generate synthetic prices
                        synthetic_count = self._backcast_with_proxy(
                            db,
                            asset_info.asset_id,
                            asset.proxy_asset_id,
                            asset_info.first_transaction_date,
                            first_real,
                        )
                        result.prices_fetched += synthetic_count

            return result

        except Exception as e:
            logger.error(
                f"Error syncing {asset_info.ticker}/{asset_info.exchange}: {e}"
            )
            result.success = False
            result.error = str(e)
            return result

    def _get_missing_date_ranges(
            self,
            db: Session,
            asset_id: int,
            start_date: date,
            end_date: date,
    ) -> list[tuple[date, date]]:
        """
        Find date ranges that don't have price data.

        Returns ranges that need to be fetched, collapsing consecutive
        missing dates into single ranges for efficiency.

        Args:
            db: Database session
            asset_id: Asset to check
            start_date: Start of range
            end_date: End of range

        Returns:
            List of (start, end) date ranges to fetch
        """
        # Get existing dates (INCLUDE no_data_available markers - we already tried those dates)
        # This prevents re-fetching dates we know have no data from the provider
        query = (
            select(MarketData.date)
            .where(
                and_(
                    MarketData.asset_id == asset_id,
                    MarketData.date >= start_date,
                    MarketData.date <= end_date,
                    # Include ALL records - both real prices and no_data markers
                )
            )
        )

        existing_dates = set()
        for row in db.execute(query).scalars():
            if hasattr(row, 'date'):
                existing_dates.add(row.date())
            else:
                existing_dates.add(row)

        # Generate all business days in range
        all_dates = get_business_days(start_date, end_date)

        # Find missing dates
        missing_dates = sorted([d for d in all_dates if d not in existing_dates])

        if not missing_dates:
            return []

        # Collapse consecutive dates into ranges
        ranges = []
        range_start = missing_dates[0]
        range_end = missing_dates[0]

        for d in missing_dates[1:]:
            # Check if consecutive (allowing for weekends)
            days_diff = (d - range_end).days
            if days_diff <= 3:  # Allow gaps up to 3 days (weekend + 1)
                range_end = d
            else:
                ranges.append((range_start, range_end))
                range_start = d
                range_end = d

        ranges.append((range_start, range_end))

        return ranges

    def _store_prices(
            self,
            db: Session,
            asset_id: int,
            prices: list[OHLCVData],
    ) -> int:
        """
        Store OHLCV prices in the database using bulk upsert.

        Uses PostgreSQL's INSERT ... ON CONFLICT DO UPDATE for efficient
        bulk operations. This is significantly faster than individual
        SELECT + INSERT/UPDATE per record.

        Args:
            db: Database session
            asset_id: Asset ID
            prices: List of OHLCV data to store

        Returns:
            Number of records stored
        """
        if not prices:
            return 0

        # Check if OHLC columns exist by inspecting the model
        has_ohlc = hasattr(MarketData, 'open_price')

        # Get provider name safely
        provider_name = getattr(self._provider, 'name', 'unknown')
        if not isinstance(provider_name, str):
            provider_name = str(provider_name) if provider_name else 'unknown'

        # Build list of records for bulk upsert
        records = []
        for p in prices:
            record = {
                "asset_id": asset_id,
                "date": p.date,
                "close_price": p.close,
                "adjusted_close": p.adjusted_close,
                "volume": p.volume,
                "provider": provider_name,
                "is_synthetic": False,
                "proxy_source_id": None,
            }

            # Add OHLC if columns exist
            if has_ohlc:
                record["open_price"] = p.open
                record["high_price"] = p.high
                record["low_price"] = p.low

            records.append(record)

        try:
            # PostgreSQL bulk upsert using ON CONFLICT DO UPDATE
            stmt = pg_insert(MarketData).values(records)

            # Define columns to update on conflict
            update_columns = {
                "close_price": stmt.excluded.close_price,
                "adjusted_close": stmt.excluded.adjusted_close,
                "volume": stmt.excluded.volume,
                "provider": stmt.excluded.provider,
            }

            # Add OHLC columns if they exist
            if has_ohlc:
                update_columns["open_price"] = stmt.excluded.open_price
                update_columns["high_price"] = stmt.excluded.high_price
                update_columns["low_price"] = stmt.excluded.low_price

            # Conflict on unique constraint (asset_id, date)
            upsert_stmt = stmt.on_conflict_do_update(
                index_elements=["asset_id", "date"],
                set_=update_columns,
            )

            db.execute(upsert_stmt)
            db.commit()

            return len(records)

        except Exception as e:
            logger.error(f"Error storing prices for asset {asset_id}: {e}")
            raise

    # =========================================================================
    # PRIVATE METHODS - Status Management
    # =========================================================================

    def _update_sync_status(
            self,
            db: Session,
            portfolio_id: int,
            status: SyncStatusEnum,
            sync_started: datetime | None = None,
            sync_completed: datetime | None = None,
            coverage_summary: dict | None = None,
            last_error: str | None = None,
    ) -> SyncStatus:
        """
        Update or create sync status for a portfolio.

        Uses PostgreSQL's INSERT ... ON CONFLICT DO UPDATE for atomic upsert,
        preventing race conditions under concurrent sync requests.
        """
        # Build the values for insert
        values = {
            "portfolio_id": portfolio_id,
            "status": status,
            "last_sync_started": sync_started,
            "last_sync_completed": sync_completed,
            "coverage_summary": coverage_summary or {},
            "last_error": last_error if last_error is not None else (
                None if status == SyncStatusEnum.COMPLETED else None
            ),
        }

        # Build update set - only update fields that were explicitly provided
        update_set = {"status": status}
        if sync_started is not None:
            update_set["last_sync_started"] = sync_started
        if sync_completed is not None:
            update_set["last_sync_completed"] = sync_completed
        if coverage_summary is not None:
            update_set["coverage_summary"] = coverage_summary
        if last_error is not None:
            update_set["last_error"] = last_error
        elif status == SyncStatusEnum.COMPLETED:
            update_set["last_error"] = None

        # Use PostgreSQL upsert for atomic operation
        stmt = pg_insert(SyncStatus).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["portfolio_id"],
            set_=update_set,
        )

        db.execute(stmt)
        db.commit()

        # Fetch and return the updated/created record
        return db.scalar(
            select(SyncStatus).where(SyncStatus.portfolio_id == portfolio_id)
        )

    def _build_coverage_summary(
            self,
            db: Session,
            portfolio_id: int,
            analysis: PortfolioAnalysis,
            result: SyncResult,
    ) -> dict[str, Any]:
        """
        Build coverage summary for storage in sync_status.

        Returns dict with asset and FX coverage details.
        """
        summary = {
            "sync_date": date.today().isoformat(),
            "date_range": {
                "from": analysis.earliest_date.isoformat() if analysis.earliest_date else None,
                "to": analysis.latest_date.isoformat() if analysis.latest_date else None,
            },
            "assets": {
                "total": len(analysis.assets),
                "synced": result.assets_synced,
                "failed": result.assets_failed,
                "details": [],
            },
            "fx_pairs": {
                "total": len(analysis.fx_pairs_needed),
                "synced": result.fx_pairs_synced,
                "details": [],
            },
        }

        # Add asset details
        for asset_result in result.asset_results:
            asset_detail = {
                "asset_id": asset_result.asset_id,
                "ticker": asset_result.ticker,
                "exchange": asset_result.exchange,
                "status": "complete" if asset_result.success else "failed",
                "prices_fetched": asset_result.prices_fetched,
            }
            if asset_result.error:
                asset_detail["error"] = asset_result.error

            summary["assets"]["details"].append(asset_detail)

        # Add FX pair details
        for base, quote in analysis.fx_pairs_needed:
            coverage = self._fx_service.get_coverage(db, base, quote)
            fx_detail = {
                "pair": f"{base}/{quote}",
                "from_date": coverage["from_date"].isoformat() if coverage["from_date"] else None,
                "to_date": coverage["to_date"].isoformat() if coverage["to_date"] else None,
                "total_days": coverage["total_days"],
            }
            summary["fx_pairs"]["details"].append(fx_detail)

        return summary

    def _backcast_assets_batch(
            self,
            db: Session,
            assets: list[AssetSyncInfo],
            portfolio_id: int | None = None,
            backcasting_method: BackcastingMethod = BackcastingMethod.PROXY_PREFERRED,
    ) -> dict:
        """
        Batch backcast multiple assets using a fallback chain:

        1. Proxy Backcasting (if proxy configured): Use similar asset to model prices
        2. Cost-Carry Fallback (if no proxy or proxy fails): Value at purchase price

        This two-tier approach prioritizes accuracy over completeness:
        - Proxy backcasting provides market-like movement for correlated assets
        - Cost-carry is legally safe when no correlation assumption is valid

        Respects backcasting_method setting:
        - PROXY_PREFERRED: Try proxy first, then cost-carry fallback
        - COST_CARRY_ONLY: Skip proxy backcasting, only use cost-carry
        - DISABLED: Should not reach this method (handled by caller)

        Args:
            db: Database session
            assets: List of asset sync info
            portfolio_id: Portfolio ID (needed for cost-carry to find transactions)
            backcasting_method: User preference for backcasting approach

        Returns:
            Dict with total_synthetic, assets_backcast_count, and cost_carry_count
        """
        total_synthetic = 0
        assets_backcast_count = 0
        cost_carry_count = 0

        if not assets:
            return {
                "total_synthetic": 0,
                "assets_backcast_count": 0,
                "cost_carry_count": 0,
            }

        # Step 1: Batch fetch all assets with proxy relationships
        asset_ids = [a.asset_id for a in assets]
        refreshed_assets = db.scalars(
            select(Asset).where(Asset.id.in_(asset_ids))
        ).all()
        asset_lookup = {a.id: a for a in refreshed_assets}

        # Step 2: Separate assets with and without proxies
        # If backcasting_method is COST_CARRY_ONLY, treat all assets as "without proxies"
        assets_with_proxies = []
        assets_without_proxies = []

        for asset_info in assets:
            asset = asset_lookup.get(asset_info.asset_id)
            if not asset:
                continue
            # Only use proxy if method is PROXY_PREFERRED and proxy is configured
            if backcasting_method == BackcastingMethod.PROXY_PREFERRED and asset.proxy_asset_id:
                assets_with_proxies.append((asset_info, asset))
            else:
                assets_without_proxies.append((asset_info, asset))

        # Step 3: Batch detect price gaps for ALL assets (with and without proxies)
        all_asset_ids = [a.asset_id for a in assets]

        # Query: Get first real (non-synthetic) price date for each asset
        min_real_dates = db.execute(
            select(
                MarketData.asset_id,
                func.min(MarketData.date).label('first_real_date')
            )
            .where(
                MarketData.asset_id.in_(all_asset_ids),
                MarketData.is_synthetic == False,
                MarketData.no_data_available == False,
            )
            .group_by(MarketData.asset_id)
        ).all()

        first_real_date_map = {row.asset_id: row.first_real_date for row in min_real_dates}

        # Step 4: Identify which assets with proxies need backcasting
        proxy_backcast_requirements = []  # List of (asset_info, asset, gap_start, gap_end)
        proxy_ids_needed = set()

        for asset_info, asset in assets_with_proxies:
            first_real_date = first_real_date_map.get(asset.id)

            if first_real_date is None:
                # No prices at all - gap is entire history
                gap_start = asset_info.first_transaction_date
                gap_end = date.today()
            elif first_real_date > asset_info.first_transaction_date:
                # Gap exists
                gap_start = asset_info.first_transaction_date
                gap_end = first_real_date - timedelta(days=1)
            else:
                # No gap
                continue

            proxy_backcast_requirements.append((asset_info, asset, gap_start, gap_end))
            proxy_ids_needed.add(asset.proxy_asset_id)

        # Step 5: Batch ensure proxy data is available
        if proxy_ids_needed:
            proxy_coverage = db.execute(
                select(
                    MarketData.asset_id,
                    func.min(MarketData.date).label('min_date'),
                    func.max(MarketData.date).label('max_date')
                )
                .where(
                    MarketData.asset_id.in_(proxy_ids_needed),
                    MarketData.no_data_available == False,
                )
                .group_by(MarketData.asset_id)
            ).all()
            proxy_coverage_map = {
                row.asset_id: (row.min_date, row.max_date)
                for row in proxy_coverage
            }

            # Fetch proxy assets that need data
            proxy_assets = {
                a.id: a for a in db.scalars(
                    select(Asset).where(Asset.id.in_(proxy_ids_needed))
                ).all()
            }

            # Determine overall date range needed for proxies
            if proxy_backcast_requirements:
                overall_start = min(req[2] for req in proxy_backcast_requirements)
                overall_end = max(req[3] for req in proxy_backcast_requirements)

                # Fetch missing proxy data
                for proxy_id in proxy_ids_needed:
                    coverage = proxy_coverage_map.get(proxy_id)
                    proxy_asset = proxy_assets.get(proxy_id)

                    if not proxy_asset:
                        continue

                    needs_fetch = False
                    if coverage is None:
                        needs_fetch = True
                    elif coverage[0] is None or coverage[0] > overall_start:
                        needs_fetch = True

                    if needs_fetch:
                        logger.info(f"Fetching proxy data for {proxy_asset.ticker}/{proxy_asset.exchange}")
                        result = self._provider.get_historical_prices(
                            ticker=proxy_asset.ticker,
                            exchange=proxy_asset.exchange,
                            start_date=overall_start,
                            end_date=overall_end,
                        )
                        if result.success and result.prices:
                            self._store_prices(db, proxy_id, result.prices)

        # Step 6: Process proxy backcasting for assets with proxies
        # Track which assets fail proxy backcasting (for cost-carry fallback)
        failed_proxy_backcast = []

        for asset_info, asset, gap_start, gap_end in proxy_backcast_requirements:
            created = self._backcast_with_proxy(
                db, asset.id, asset.proxy_asset_id,
                gap_start, gap_end
            )
            if created > 0:
                total_synthetic += created
                assets_backcast_count += 1
                logger.info(
                    f"Backcast {asset.ticker}: {created} synthetic prices "
                    f"({gap_start} to {gap_end})"
                )
            else:
                # Proxy backcasting failed - add to cost-carry fallback list
                logger.warning(
                    f"Proxy backcasting failed for {asset.ticker}, "
                    f"falling back to cost-carry"
                )
                failed_proxy_backcast.append((asset_info, asset, gap_start, gap_end))

        # Step 7: Process cost-carry for assets WITHOUT proxies
        cost_carry_requirements = []

        for asset_info, asset in assets_without_proxies:
            first_real_date = first_real_date_map.get(asset.id)

            if first_real_date is None:
                # No prices at all - gap is entire history
                gap_start = asset_info.first_transaction_date
                gap_end = date.today()
            elif first_real_date > asset_info.first_transaction_date:
                # Gap exists
                gap_start = asset_info.first_transaction_date
                gap_end = first_real_date - timedelta(days=1)
            else:
                # No gap
                continue

            cost_carry_requirements.append((asset_info, asset, gap_start, gap_end))

        # Add failed proxy backcasts to cost-carry list
        cost_carry_requirements.extend(failed_proxy_backcast)

        # Step 8: Process cost-carry fallback (requires portfolio_id)
        if cost_carry_requirements and portfolio_id:
            for asset_info, asset, gap_start, gap_end in cost_carry_requirements:
                created = self._carry_at_cost(
                    db, asset.id, portfolio_id,
                    gap_start, gap_end
                )
                if created > 0:
                    total_synthetic += created
                    cost_carry_count += 1
                    logger.info(
                        f"Cost-carry {asset.ticker}: {created} synthetic prices "
                        f"({gap_start} to {gap_end})"
                    )
        elif cost_carry_requirements and not portfolio_id:
            logger.warning(
                f"Cannot apply cost-carry fallback: portfolio_id not provided. "
                f"{len(cost_carry_requirements)} assets have gaps without proxies."
            )

        return {
            "total_synthetic": total_synthetic,
            "assets_backcast_count": assets_backcast_count,
            "cost_carry_count": cost_carry_count,
        }

    def _backcast_with_proxy(
            self,
            db: Session,
            asset_id: int,
            proxy_asset_id: int,
            backcast_start: date,
            backcast_end: date,
    ) -> int:
        """
        Generate synthetic prices for an asset using proxy data.

        Algorithm (Price Scaling Method):
        =================================
        Uses the relationship between the asset and proxy at the "anchor point"
        (first available real price) to scale proxy prices backwards in time.

        Formula:
            scale_factor = asset_price_anchor / proxy_price_anchor
            synthetic_price[t] = proxy_price[t] × scale_factor

        This assumes the asset tracks the proxy with a constant ratio, which is
        reasonable for ETFs tracking similar indices (e.g., MSCI World variants).

        Example:
            - Asset first real price: $50 on 2024-03-01
            - Proxy price on 2024-03-01: $100
            - scale_factor = 50 / 100 = 0.5
            - For 2024-01-15 where proxy = $95:
              synthetic_price = 95 × 0.5 = $47.50

        Design Properties:
        - Safe from division by zero (guards against zero proxy price)
        - Free from N+1 queries (batch fetches existing dates)
        - Race-condition safe (uses ON CONFLICT DO NOTHING for atomic upsert)

        Args:
            db: Database session
            asset_id: Asset needing synthetic data
            proxy_asset_id: Proxy asset to use as source
            backcast_start: Start of period needing synthetic data
            backcast_end: End of period (exclusive - first real price date)

        Returns:
            Number of synthetic prices created
        """
        from decimal import Decimal, ROUND_HALF_UP

        # Get anchor price (first real price for the asset)
        # Must exclude no_data_available placeholders (Yahoo creates these with close_price=None)
        anchor = db.execute(
            select(MarketData)
            .where(
                MarketData.asset_id == asset_id,
                MarketData.date == backcast_end,
                MarketData.is_synthetic == False,
                MarketData.no_data_available == False,
            )
        ).scalar()

        if not anchor:
            # Try to find closest real price (excluding placeholders)
            anchor = db.execute(
                select(MarketData)
                .where(
                    MarketData.asset_id == asset_id,
                    MarketData.date >= backcast_end,
                    MarketData.is_synthetic == False,
                    MarketData.no_data_available == False,
                )
                .order_by(MarketData.date)
                .limit(1)
            ).scalar()

        if not anchor:
            logger.warning(f"No anchor price found for asset {asset_id}")
            return 0

        anchor_price = anchor.close_price
        anchor_date = anchor.date

        # Guard against invalid anchor price
        if anchor_price is None or anchor_price == Decimal("0"):
            logger.warning(
                f"Anchor price is zero or None for asset {asset_id} "
                f"on {anchor_date}, cannot calculate scale factor"
            )
            return 0

        # Get proxy price on anchor date
        proxy_anchor = db.execute(
            select(MarketData)
            .where(
                MarketData.asset_id == proxy_asset_id,
                MarketData.date <= anchor_date,
            )
            .order_by(MarketData.date.desc())
            .limit(1)
        ).scalar()

        if not proxy_anchor:
            logger.warning(f"No proxy anchor price found for proxy {proxy_asset_id}")
            return 0

        proxy_anchor_price = proxy_anchor.close_price

        # Guard against division by zero
        if proxy_anchor_price is None or proxy_anchor_price == Decimal("0"):
            logger.warning(
                f"Proxy anchor price is zero or None for proxy {proxy_asset_id} "
                f"on {anchor_date}, cannot calculate scale factor"
            )
            return 0

        # Calculate scaling factor
        scale_factor = anchor_price / proxy_anchor_price

        logger.info(
            f"Backcasting asset {asset_id} with proxy {proxy_asset_id}: "
            f"scale_factor={scale_factor:.6f}"
        )

        # Get all proxy prices in backcast period
        proxy_prices = db.execute(
            select(MarketData)
            .where(
                MarketData.asset_id == proxy_asset_id,
                MarketData.date >= backcast_start,
                MarketData.date < backcast_end,
            )
            .order_by(MarketData.date)
        ).scalars().all()

        if not proxy_prices:
            logger.debug(f"No proxy prices found for backcast period {backcast_start} to {backcast_end}")
            return 0

        # Batch fetch existing dates that already have real prices for this asset
        # (We want to skip dates that have actual price data, but replace no_data_available markers)
        proxy_dates = [p.date for p in proxy_prices]
        existing_dates_query = (
            select(MarketData.date)
            .where(
                MarketData.asset_id == asset_id,
                MarketData.date.in_(proxy_dates),
                MarketData.close_price.isnot(None),  # Only skip if has actual price
                MarketData.no_data_available == False,  # Don't skip no_data markers
            )
        )
        existing_dates = set(db.scalars(existing_dates_query).all())

        # Delete no_data_available markers for dates we're about to backcast
        # This allows us to replace them with synthetic prices
        from sqlalchemy import delete
        dates_to_backcast = [d for d in proxy_dates if d not in existing_dates]
        if dates_to_backcast:
            delete_stmt = (
                delete(MarketData)
                .where(
                    MarketData.asset_id == asset_id,
                    MarketData.date.in_(dates_to_backcast),
                    MarketData.no_data_available == True,
                )
            )
            deleted = db.execute(delete_stmt)
            if deleted.rowcount > 0:
                logger.debug(f"Deleted {deleted.rowcount} no_data markers for backcast")

        # Helper function to scale values with proper precision
        def scale(val):
            if val is None:
                return None
            return (Decimal(str(val)) * scale_factor).quantize(
                Decimal('0.0001'), ROUND_HALF_UP
            )

        # Build records for bulk insert, excluding dates that already exist
        records = []
        for proxy_price in proxy_prices:
            if proxy_price.date in existing_dates:
                continue

            records.append({
                "asset_id": asset_id,
                "date": proxy_price.date,
                "open_price": scale(proxy_price.open_price),
                "high_price": scale(proxy_price.high_price),
                "low_price": scale(proxy_price.low_price),
                "close_price": scale(proxy_price.close_price),
                "adjusted_close": scale(proxy_price.adjusted_close),
                "volume": None,  # Volume is unknown for synthetic data
                "provider": "proxy_backcast",
                "is_synthetic": True,
                "proxy_source_id": proxy_asset_id,
            })

        if not records:
            logger.debug(f"All dates already have prices for asset {asset_id}")
            return 0

        # Use bulk upsert with ON CONFLICT DO NOTHING for race-condition safety
        # This ensures that if a concurrent request creates the same record,
        # we simply skip it rather than failing with IntegrityError
        try:
            stmt = pg_insert(MarketData).values(records)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["asset_id", "date"]
            )
            result = db.execute(stmt)
            db.commit()

            # rowcount reflects actual inserts (excludes conflicts)
            created = result.rowcount if result.rowcount >= 0 else len(records)

            if created > 0:
                logger.info(f"Created {created} synthetic prices for asset {asset_id}")

            return created

        except Exception as e:
            db.rollback()
            logger.error(f"Error creating synthetic prices for asset {asset_id}: {e}")
            raise

    def _ensure_proxy_data(
            self,
            db: Session,
            proxy_asset_id: int,
            start_date: date,
            end_date: date,
    ) -> bool:
        """
        Ensure proxy asset has data for the required period.
        Fetches from provider if missing.

        Returns True if proxy has sufficient data.
        """
        # Check existing coverage (exclude no_data_available placeholders)
        existing = db.execute(
            select(func.min(MarketData.date), func.max(MarketData.date))
            .where(
                MarketData.asset_id == proxy_asset_id,
                MarketData.no_data_available == False,
            )
        ).fetchone()

        min_date, max_date = existing

        # If no data or insufficient coverage, fetch
        if min_date is None or min_date > start_date:
            # Get proxy asset info
            proxy_asset = db.get(Asset, proxy_asset_id)
            if not proxy_asset:
                return False

            logger.info(f"Fetching proxy data for {proxy_asset.ticker}/{proxy_asset.exchange}")

            result = self._provider.get_historical_prices(
                ticker=proxy_asset.ticker,
                exchange=proxy_asset.exchange,
                start_date=start_date,
                end_date=end_date,
            )

            if result.success and result.prices:
                self._store_prices(db, proxy_asset_id, result.prices)
                return True
            else:
                logger.error(f"Failed to fetch proxy data: {result.error}")
                return False

        return True

    def _detect_price_gap(
            self,
            db: Session,
            asset_id: int,
            first_transaction_date: date,
    ) -> tuple[date | None, date | None]:
        """
        Detect if there's a gap in price data before the first available price.

        Returns:
            Tuple of (gap_start, gap_end) or (None, None) if no gap
        """
        # Find earliest price we have (exclude no_data_available placeholders)
        earliest_price = db.execute(
            select(func.min(MarketData.date))
            .where(
                MarketData.asset_id == asset_id,
                MarketData.is_synthetic == False,  # Only real prices
                MarketData.no_data_available == False,  # Exclude placeholders
            )
        ).scalar()

        if earliest_price is None:
            # No prices at all - gap is entire history
            return first_transaction_date, date.today()

        if earliest_price > first_transaction_date:
            # Gap exists between first transaction and first price
            return first_transaction_date, earliest_price - timedelta(days=1)

        # No gap
        return None, None

    def _carry_at_cost(
            self,
            db: Session,
            asset_id: int,
            portfolio_id: int,
            gap_start: date,
            gap_end: date,
    ) -> int:
        """
        Fallback: Value asset at cost basis when no proxy or market data is available.

        This is the "last resort" synthetic data method. When:
        1. No specific proxy is configured for the asset
        2. OR proxy backcasting fails (no proxy data available)

        We fill the gap by valuing the asset at its purchase price.
        This is financially conservative and legally safe.

        Implementation Details:
        - Only creates prices for dates AFTER the first BUY transaction
        - Price = average cost per share at each point in time
        - Volume = None (no trading data to infer)
        - Clearly marked as synthetic with provider="cost_carry"

        Args:
            db: Database session
            asset_id: Asset needing synthetic data
            portfolio_id: Portfolio ID (needed to find transactions)
            gap_start: Start of period needing synthetic data
            gap_end: End of period (exclusive - first real price date)

        Returns:
            Number of synthetic prices created
        """
        from decimal import Decimal, ROUND_HALF_UP
        from sqlalchemy import delete

        # Get all BUY transactions for this asset in this portfolio, sorted by date
        buy_transactions = db.execute(
            select(Transaction)
            .where(
                Transaction.portfolio_id == portfolio_id,
                Transaction.asset_id == asset_id,
                Transaction.transaction_type == TransactionType.BUY,
            )
            .order_by(Transaction.date)
        ).scalars().all()

        if not buy_transactions:
            logger.debug(f"No BUY transactions for asset {asset_id} in portfolio {portfolio_id}")
            return 0

        # Find the first buy date - we only create synthetic prices from this date
        first_buy = buy_transactions[0]
        first_buy_date = first_buy.date.date() if hasattr(first_buy.date, 'date') else first_buy.date

        # Adjust gap_start to not be before first buy
        effective_start = max(gap_start, first_buy_date)

        if effective_start > gap_end:
            # No gap to fill (first buy is after the gap period)
            return 0

        # Calculate running average cost at each transaction point
        # We'll use the cost at the last transaction before each date
        cost_timeline = []
        running_shares = Decimal("0")
        running_cost = Decimal("0")

        for txn in buy_transactions:
            txn_date = txn.date.date() if hasattr(txn.date, 'date') else txn.date
            running_shares += txn.quantity
            # Calculate total cost as quantity * price_per_share (+ fee if applicable)
            txn_total = txn.quantity * txn.price_per_share + (txn.fee or Decimal("0"))
            running_cost += txn_total

            if running_shares > Decimal("0"):
                avg_cost = running_cost / running_shares
                cost_timeline.append((txn_date, avg_cost))

        if not cost_timeline:
            return 0

        # Build dates to fill (only trading days would be ideal, but we'll create
        # for all dates and let the history calculator handle weekend gaps)
        # Actually, let's only create for dates where we'd need a price
        # For simplicity, create for all dates in the gap period

        # Get existing dates that have real prices (to avoid overwriting)
        existing_dates_query = (
            select(MarketData.date)
            .where(
                MarketData.asset_id == asset_id,
                MarketData.date >= effective_start,
                MarketData.date <= gap_end,
                MarketData.close_price.isnot(None),
                MarketData.no_data_available == False,
            )
        )
        existing_dates = set(db.scalars(existing_dates_query).all())

        # Delete no_data_available markers in the gap period
        dates_in_range = []
        current_date = effective_start
        while current_date <= gap_end:
            if current_date not in existing_dates:
                dates_in_range.append(current_date)
            current_date += timedelta(days=1)

        if dates_in_range:
            delete_stmt = (
                delete(MarketData)
                .where(
                    MarketData.asset_id == asset_id,
                    MarketData.date.in_(dates_in_range),
                    MarketData.no_data_available == True,
                )
            )
            deleted = db.execute(delete_stmt)
            if deleted.rowcount > 0:
                logger.debug(f"Deleted {deleted.rowcount} no_data markers for cost-carry")

        # Helper to find the applicable cost for a given date
        def get_cost_for_date(d: date) -> Decimal | None:
            """Get the average cost that was applicable on a given date."""
            applicable_cost = None
            for txn_date, cost in cost_timeline:
                if txn_date <= d:
                    applicable_cost = cost
                else:
                    break
            return applicable_cost

        # Build records for bulk insert
        records = []
        for d in dates_in_range:
            cost = get_cost_for_date(d)
            if cost is None:
                continue  # This date is before first buy

            # Round to 4 decimal places for price precision
            price = cost.quantize(Decimal('0.0001'), ROUND_HALF_UP)

            records.append({
                "asset_id": asset_id,
                "date": d,
                "open_price": price,
                "high_price": price,
                "low_price": price,
                "close_price": price,
                "adjusted_close": price,
                "volume": None,  # No volume data for cost-carry
                "provider": "cost_carry",
                "is_synthetic": True,
                "proxy_source_id": None,  # No proxy used
            })

        if not records:
            return 0

        # Bulk upsert with ON CONFLICT DO NOTHING
        try:
            stmt = pg_insert(MarketData).values(records)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["asset_id", "date"]
            )
            result = db.execute(stmt)
            db.commit()

            created = result.rowcount if result.rowcount >= 0 else len(records)

            if created > 0:
                logger.info(
                    f"Created {created} cost-carry prices for asset {asset_id} "
                    f"({effective_start} to {gap_end})"
                )

            return created

        except Exception as e:
            db.rollback()
            logger.error(f"Error creating cost-carry prices for asset {asset_id}: {e}")
            raise
