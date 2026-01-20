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

from sqlalchemy import select, func, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    Transaction,
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
from app.services.proxy_mapping_service import ProxyMappingService, ProxyMappingResult

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

    # Default staleness threshold (24 hours)
    DEFAULT_STALENESS_HOURS: int = 24

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
                staleness_threshold_hours or self.DEFAULT_STALENESS_HOURS
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
            # 1. Update status to IN_PROGRESS
            self._update_sync_status(
                db, portfolio_id,
                status=SyncStatusEnum.IN_PROGRESS,
                sync_started=sync_started,
            )

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
            backcasting_enabled = self._settings_service.is_backcasting_enabled(
                db, portfolio_id
            )
            result.backcasting_enabled = backcasting_enabled

            # 2c. Apply proxy mappings if backcasting enabled
            if backcasting_enabled:
                logger.info(f"Applying proxy mappings for portfolio {portfolio_id}")
                proxy_result = self._proxy_mapping_service.apply_mappings(
                    db,
                    [db.get(Asset, a.asset_id) for a in analysis.assets]
                )
                result.proxy_mapping_result = proxy_result
                result.proxies_applied = proxy_result.total_applied
                result.warnings.extend(proxy_result.warnings)

                if proxy_result.total_applied > 0:
                    logger.info(
                        f"Applied {proxy_result.total_applied} proxy mappings"
                    )

            # 3. Sync price data for each asset
            for asset_info in analysis.assets:
                asset_result = self._sync_asset_prices(
                    db=db,
                    asset_info=asset_info,
                    end_date=analysis.latest_date or date.today(),
                    force=force,
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

            # 4b. Backcast with proxies if enabled
            if backcasting_enabled:
                total_synthetic = 0
                assets_backcast_count = 0

                for asset_info in analysis.assets:
                    # Reload asset to get proxy_asset_id (may have been set by mapping)
                    asset = db.get(Asset, asset_info.asset_id)
                    if asset and asset.proxy_asset_id:
                        # Detect gap in real price data
                        gap_start, gap_end = self._detect_price_gap(
                            db, asset.id, asset_info.first_transaction_date
                        )

                        if gap_start and gap_end:
                            # Ensure proxy has data for the gap period
                            if self._ensure_proxy_data(
                                    db, asset.proxy_asset_id, gap_start, gap_end
                            ):
                                # Generate synthetic prices
                                created = self._backcast_with_proxy(
                                    db, asset.id, asset.proxy_asset_id,
                                    gap_start, gap_end
                                )
                                if created > 0:
                                    total_synthetic += created
                                    assets_backcast_count += 1
                                    logger.info(
                                        f"Backcast {asset.ticker}: "
                                        f"{created} synthetic prices "
                                        f"({gap_start} to {gap_end})"
                                    )

                result.synthetic_prices_created = total_synthetic
                result.assets_backcast = assets_backcast_count

                if total_synthetic > 0:
                    result.warnings.append(
                        f"Generated {total_synthetic} synthetic prices for "
                        f"{assets_backcast_count} asset(s) using proxy backcasting"
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
                # Find the first real price date
                first_real = db.execute(
                    select(func.min(MarketData.date))
                    .where(
                        MarketData.asset_id == asset_info.asset_id,
                        MarketData.is_synthetic == False,
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
        # Get existing dates
        query = (
            select(MarketData.date)
            .where(
                and_(
                    MarketData.asset_id == asset_id,
                    MarketData.date >= start_date,
                    MarketData.date <= end_date,
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
        all_dates = self._get_business_days(start_date, end_date)

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

    @staticmethod
    def _get_business_days(start_date: date, end_date: date) -> list[date]:
        """Get list of business days (weekdays) in range."""
        days = []
        current = start_date

        while current <= end_date:
            if current.weekday() < 5:  # Monday = 0, Friday = 4
                days.append(current)
            current += timedelta(days=1)

        return days

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

        Uses upsert to handle both insert and update cases.
        """
        # Check if exists
        existing = db.scalar(
            select(SyncStatus).where(SyncStatus.portfolio_id == portfolio_id)
        )

        if existing:
            existing.status = status
            if sync_started:
                existing.last_sync_started = sync_started
            if sync_completed:
                existing.last_sync_completed = sync_completed
            if coverage_summary is not None:
                existing.coverage_summary = coverage_summary
            if last_error is not None:
                existing.last_error = last_error
            elif status == SyncStatusEnum.COMPLETED:
                existing.last_error = None

            db.commit()
            return existing
        else:
            new_status = SyncStatus(
                portfolio_id=portfolio_id,
                status=status,
                last_sync_started=sync_started,
                last_sync_completed=sync_completed,
                coverage_summary=coverage_summary or {},
                last_error=last_error,
            )
            db.add(new_status)
            db.commit()
            db.refresh(new_status)
            return new_status

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

        Uses a scaling approach: find the first real price for the asset,
        calculate a scale factor vs the proxy, then apply that factor to
        all proxy prices in the backcast period.

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
        anchor = db.execute(
            select(MarketData)
            .where(
                MarketData.asset_id == asset_id,
                MarketData.date == backcast_end,
                MarketData.is_synthetic == False,
            )
        ).scalar()

        if not anchor:
            # Try to find closest real price
            anchor = db.execute(
                select(MarketData)
                .where(
                    MarketData.asset_id == asset_id,
                    MarketData.date >= backcast_end,
                    MarketData.is_synthetic == False,
                )
                .order_by(MarketData.date)
                .limit(1)
            ).scalar()

        if not anchor:
            logger.warning(f"No anchor price found for asset {asset_id}")
            return 0

        anchor_price = anchor.close_price
        anchor_date = anchor.date

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

        # Generate synthetic prices
        created = 0
        for proxy_price in proxy_prices:
            # Check if already exists
            existing = db.execute(
                select(MarketData)
                .where(
                    MarketData.asset_id == asset_id,
                    MarketData.date == proxy_price.date,
                )
            ).scalar()

            if existing:
                continue

            # Scale proxy prices
            def scale(val):
                if val is None:
                    return None
                return (Decimal(str(val)) * scale_factor).quantize(
                    Decimal('0.0001'), ROUND_HALF_UP
                )

            synthetic = MarketData(
                asset_id=asset_id,
                date=proxy_price.date,
                open_price=scale(proxy_price.open_price),
                high_price=scale(proxy_price.high_price),
                low_price=scale(proxy_price.low_price),
                close_price=scale(proxy_price.close_price),
                adjusted_close=scale(proxy_price.adjusted_close),
                volume=proxy_price.volume,
                provider='proxy_backcast',
                is_synthetic=True,
                proxy_source_id=proxy_asset_id,
            )
            db.add(synthetic)
            created += 1

        if created > 0:
            db.commit()
            logger.info(f"Created {created} synthetic prices for asset {asset_id}")

        return created

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
        # Check existing coverage
        existing = db.execute(
            select(func.min(MarketData.date), func.max(MarketData.date))
            .where(MarketData.asset_id == proxy_asset_id)
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
        # Find earliest price we have
        earliest_price = db.execute(
            select(func.min(MarketData.date))
            .where(
                MarketData.asset_id == asset_id,
                MarketData.is_synthetic == False,  # Only real prices
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
