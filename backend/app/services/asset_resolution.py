# backend/app/services/asset_resolution.py
"""
Asset resolution service.

This service resolves a ticker + exchange combination to an Asset entity.
It implements the core business logic for automatic asset creation:

1. Check if asset exists in database
2. If found and active → return it
3. If found and deactivated → raise error
4. If not found → fetch from market data provider, create, and return

Design Principles:
- Single Responsibility: Only handles asset resolution
- Dependency Injection: Provider is injected via constructor
- No HTTP Knowledge: Raises domain exceptions, not HTTPException
- Separation of Concerns: Business logic isolated from API layer

Usage:
    from app.services import AssetResolutionService

    service = AssetResolutionService()
    asset = service.resolve_asset(db, ticker="NVDA", exchange="NASDAQ")
"""

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass

from sqlalchemy import select, and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Asset
from app.services.exceptions import (
    AssetNotFoundError,
    AssetDeactivatedError,
    MarketDataError,
    TickerNotFoundError,
)
from app.services.market_data.base import MarketDataProvider, AssetInfo
from app.services.market_data.yahoo import YahooFinanceProvider

logger = logging.getLogger(__name__)


def _is_unique_constraint_violation(integrity_error: IntegrityError) -> bool:
    """
    Check if an IntegrityError is caused by a unique constraint violation.

    Args:
        integrity_error: The SQLAlchemy IntegrityError to check

    Returns:
        True if this is a unique constraint violation, False otherwise
    """
    # PostgreSQL error code 23505 = unique_violation
    if hasattr(integrity_error.orig, 'pgcode'):
        return integrity_error.orig.pgcode == '23505'
    # Fallback for other database backends (SQLite, etc.)
    return 'unique constraint' in str(integrity_error.orig).lower()


class BoundedLRUCache:
    """
    Thread-safe bounded LRU cache.

    Evicts least-recently-used entries when capacity is reached.
    Uses OrderedDict for O(1) access and eviction.
    """

    def __init__(self, maxsize: int = 10000) -> None:
        """
        Initialize the cache.

        Args:
            maxsize: Maximum number of entries to store
        """
        self._maxsize = maxsize
        self._cache: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        """Get item from cache, moving it to end (most recently used)."""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def set(self, key, value) -> None:
        """Set item in cache, evicting oldest if at capacity."""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = value
            else:
                if len(self._cache) >= self._maxsize:
                    self._cache.popitem(last=False)  # Remove oldest
                self._cache[key] = value

    def clear(self) -> None:
        """Clear all entries from the cache."""
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        """Return number of entries in cache."""
        with self._lock:
            return len(self._cache)

    def __contains__(self, key) -> bool:
        """Check if key exists in cache."""
        with self._lock:
            return key in self._cache


@dataclass
class BatchResolutionResult:
    """Result of batch asset resolution."""
    resolved: dict[tuple[str, str], Asset]  # Successfully resolved
    deactivated: list[tuple[str, str]]  # Exist but deactivated
    not_found: list[tuple[str, str]]  # Provider couldn't find
    errors: dict[tuple[str, str], Exception]  # Other errors

    @property
    def all_resolved(self) -> bool:
        return not (self.deactivated or self.not_found or self.errors)


class AssetResolutionService:
    """
    Service for resolving ticker + exchange to database Asset entities.

    This service provides automatic asset creation by:
    1. Looking up existing assets in the database
    2. Fetching metadata from market data providers for unknown assets
    3. Creating new asset records automatically

    The service maintains a bounded LRU cache for provider responses to avoid
    redundant API calls. Cache is limited to CACHE_MAX_SIZE entries to prevent
    memory leaks on long-running server processes.

    Attributes:
        _provider: Market data provider for fetching asset metadata
        _cache: Bounded LRU cache for provider responses
        CACHE_MAX_SIZE: Maximum entries in the cache (default 10,000)

    Example:
        # Using default provider (Yahoo Finance)
        service = AssetResolutionService()
        asset = service.resolve_asset(db, "NVDA", "NASDAQ")

        # Using custom provider (for testing or alternative sources)
        mock_provider = MockMarketDataProvider()
        service = AssetResolutionService(provider=mock_provider)
    """

    CACHE_MAX_SIZE: int = 10000

    def __init__(self, provider: MarketDataProvider | None = None) -> None:
        """
        Initialize the asset resolution service.

        Args:
            provider: Market data provider to use for fetching asset metadata.
                      Defaults to YahooFinanceProvider if not specified.
                      Pass a custom provider for testing or alternative data sources.
        """
        self._provider = provider or YahooFinanceProvider()
        self._cache: BoundedLRUCache = BoundedLRUCache(maxsize=self.CACHE_MAX_SIZE)

        logger.info(f"AssetResolutionService initialized with provider: {self._provider.name}")

    def resolve_asset(self, db: Session, ticker: str, exchange: str) -> Asset:
        """
        Resolve a ticker + exchange combination to a database Asset.

        This is the main entry point for asset resolution. It follows this flow:
        1. Normalize inputs (uppercase, strip whitespace)
        2. Query database for existing asset
        3. If found and active → return existing asset
        4. If found and deactivated → raise AssetDeactivatedError
        5. If not found → fetch from provider, create asset, return new asset

        Args:
            db: SQLAlchemy database session
            ticker: Trading symbol (e.g., "NVDA", "AAPL")
            exchange: Exchange code (e.g., "NASDAQ", "XETRA")

        Returns:
            Asset entity (existing or newly created)

        Raises:
            AssetNotFoundError: Asset not in DB and provider cannot find it
            AssetDeactivatedError: Asset exists but is deactivated
            MarketDataError: Provider failure (network, rate limit, etc.)

        Example:
            try:
                asset = service.resolve_asset(db, "NVDA", "NASDAQ")
                print(f"Resolved asset ID: {asset.id}")
            except AssetNotFoundError:
                print("Unknown ticker/exchange combination")
            except AssetDeactivatedError:
                print("Asset has been deactivated")
            except MarketDataError as e:
                print(f"Provider error: {e}")
        """
        # Step 1: Normalize inputs
        ticker = ticker.strip().upper()
        exchange = exchange.strip().upper() if exchange else ""

        logger.debug(f"Resolving asset: {ticker} on {exchange}")

        # Step 2: Look up in database
        existing_asset = self._lookup_in_db(db, ticker, exchange)

        if existing_asset is not None:
            # Step 3: Found - check if active
            if existing_asset.is_active:
                logger.debug(f"Found existing active asset: {existing_asset.id}")
                return existing_asset
            else:
                # Step 4: Found but deactivated
                logger.warning(f"Asset {ticker} on {exchange} is deactivated")
                raise AssetDeactivatedError(ticker=ticker, exchange=exchange)

        # Step 5: Not found - fetch from provider and create
        logger.info(f"Asset {ticker} on {exchange} not in DB, fetching from provider")

        try:
            asset_info = self._fetch_from_provider(ticker, exchange)
            new_asset = self._create_asset(db, asset_info)
            logger.info(f"Created new asset: {new_asset.id} ({ticker} on {exchange})")
            return new_asset

        except TickerNotFoundError:
            # Provider doesn't recognize this ticker
            raise AssetNotFoundError(ticker=ticker, exchange=exchange)

        except MarketDataError:
            # Propagate provider errors (network, rate limit, etc.)
            raise

    def resolve_assets_batch(
            self,
            db: Session,
            requests: list[tuple[str, str]]
    ) -> BatchResolutionResult:
        """
        Batch resolve assets (Lookup DB -> Fetch Missing -> Create New).

        Efficiently handles multiple asset resolutions in a single pass.

        Args:
            db: Database session
            requests: List of (ticker, exchange) tuples

        Returns:
            BatchResolutionResult with resolved, deactivated, not_found, and errors.
        """
        # Initialize result
        result = BatchResolutionResult(
            resolved={},
            deactivated=[],
            not_found=[],
            errors={},
        )

        if not requests:
            return result

        # 1. Normalize inputs
        normalized_reqs = list(set(
            (t.strip().upper(), e.strip().upper() if e else "")
            for t, e in requests
        ))

        # 2. Batch DB Lookup
        conditions = [
            and_(Asset.ticker == t, Asset.exchange == e)
            for t, e in normalized_reqs
        ]
        existing_assets = db.scalars(select(Asset).where(or_(*conditions))).all()

        # Index existing assets
        found_keys = set()
        for asset in existing_assets:
            key = (asset.ticker, asset.exchange)
            found_keys.add(key)
            if asset.is_active:
                result.resolved[key] = asset
            else:
                result.deactivated.append(key)
                logger.info(f"Batch resolve: Asset {key} is deactivated")

        # 3. Identify missing (not in DB at all)
        missing = [req for req in normalized_reqs if req not in found_keys]

        if not missing:
            return result

        # 4. Check cache for missing assets
        logger.info(f"Batch resolving {len(missing)} missing assets")
        really_missing = []
        cached_infos = []

        for req in missing:
            cached = self._cache.get(req)
            if cached is not None:
                cached_infos.append(cached)
            else:
                really_missing.append(req)

        # 5. Create assets from cache (single transaction)
        if cached_infos:
            try:
                new_assets = self._create_assets_batch(db, cached_infos)
                for asset in new_assets:
                    result.resolved[(asset.ticker, asset.exchange)] = asset
            except Exception as e:
                logger.error(f"Failed to create cached assets: {e}")
                for info in cached_infos:
                    result.errors[(info.ticker, info.exchange)] = e

        if not really_missing:
            return result

        # 6. Batch Provider Fetch
        batch_result = self._provider.get_asset_info_batch(really_missing)

        # 7. Create new assets from provider results (single transaction)
        if batch_result.successful:
            infos_to_create = list(batch_result.successful.values())

            # Update cache
            for key, info in batch_result.successful.items():
                self._cache.set(key, info)

            try:
                new_assets = self._create_assets_batch(db, infos_to_create)
                for asset in new_assets:
                    result.resolved[(asset.ticker, asset.exchange)] = asset
            except Exception as e:
                logger.error(f"Failed to create new assets: {e}")
                for info in infos_to_create:
                    result.errors[(info.ticker, info.exchange)] = e

        # 8. Record provider failures
        for key, error in batch_result.failed.items():
            result.not_found.append(key)
            logger.warning(f"Asset not found by provider: {key}")

        return result

    def _lookup_in_db(self, db: Session, ticker: str, exchange: str) -> Asset | None:
        """
        Query the database for an existing asset.

        Args:
            db: Database session
            ticker: Normalized ticker symbol
            exchange: Normalized exchange code

        Returns:
            Asset if found, None otherwise
        """
        query = select(Asset).where(
            and_(
                Asset.ticker == ticker,
                Asset.exchange == exchange,
            )
        )
        return db.scalar(query)

    def _fetch_from_provider(self, ticker: str, exchange: str) -> AssetInfo:
        """
        Fetch asset metadata from the market data provider.

        Uses an in-memory cache to avoid redundant API calls for the same
        ticker+exchange combination within the application lifecycle.

        Args:
            ticker: Normalized ticker symbol
            exchange: Normalized exchange code

        Returns:
            AssetInfo from provider

        Raises:
            TickerNotFoundError: Provider doesn't recognize ticker
            ProviderUnavailableError: Provider API is unreachable
            RateLimitError: Provider rate limit exceeded
        """
        cache_key = (ticker, exchange)

        # Check cache first
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit for {ticker} on {exchange}")
            return cached

        # Fetch from provider
        logger.debug(f"Cache miss for {ticker} on {exchange}, calling provider")
        asset_info = self._provider.get_asset_info(ticker, exchange)

        # Cache the result
        self._cache.set(cache_key, asset_info)
        logger.debug(f"Cached asset info for {ticker} on {exchange}")

        return asset_info

    def _create_asset(self, db: Session, asset_info: AssetInfo) -> Asset:
        """
        Create a new Asset in the database from provider data.

        Handles race conditions where another request may create the same asset
        concurrently. If an IntegrityError occurs (unique constraint violation),
        we rollback and fetch the existing asset.

        Args:
            db: Database session
            asset_info: Metadata from market data provider

        Returns:
            Newly created Asset, or existing Asset if created by concurrent request
        """
        asset = Asset(
            ticker=asset_info.ticker,
            exchange=asset_info.exchange,
            name=asset_info.name,
            asset_class=asset_info.asset_class,
            currency=asset_info.currency,
            sector=asset_info.sector,
            region=asset_info.region,
            isin=asset_info.isin,
            is_active=True,
        )

        db.add(asset)

        try:
            db.commit()
            db.refresh(asset)
            return asset
        except IntegrityError as e:
            db.rollback()

            if not _is_unique_constraint_violation(e):
                # Not a unique constraint violation - re-raise the error
                logger.error(
                    f"Asset creation failed for {asset_info.ticker} on "
                    f"{asset_info.exchange} with unexpected error: {e}"
                )
                raise

            # Another request created this asset concurrently
            logger.info(
                f"Asset {asset_info.ticker} on {asset_info.exchange} created by "
                "concurrent request, fetching existing"
            )
            existing = self._lookup_in_db(db, asset_info.ticker, asset_info.exchange)
            if existing is not None:
                return existing
            # Shouldn't happen, but re-raise if still not found
            raise

    def _create_assets_batch(
            self,
            db: Session,
            asset_infos: list[AssetInfo]
    ) -> list[Asset]:
        """
        Create multiple assets in a single transaction.

        Handles race conditions where concurrent requests may create the same
        assets. If an IntegrityError occurs, falls back to resolving each
        asset individually.

        Args:
            db: Database session
            asset_infos: List of asset metadata from provider

        Returns:
            List of created or existing Asset entities
        """
        if not asset_infos:
            return []

        assets = []
        for info in asset_infos:
            asset = Asset(
                ticker=info.ticker,
                exchange=info.exchange,
                name=info.name,
                asset_class=info.asset_class,
                currency=info.currency,
                sector=info.sector,
                region=info.region,
                isin=info.isin,
                is_active=True,
            )
            db.add(asset)
            assets.append(asset)

        try:
            db.commit()  # Single commit for all
            for asset in assets:
                db.refresh(asset)
            return assets
        except IntegrityError as e:
            db.rollback()

            if not _is_unique_constraint_violation(e):
                # Not a unique constraint violation - re-raise the error
                # This could be FK violation, check constraint, etc.
                logger.error(f"Batch asset creation failed with unexpected error: {e}")
                raise

            # One or more assets were created by concurrent requests
            logger.warning(
                "Batch asset creation failed due to concurrent request, "
                "resolving individually"
            )
            # Fallback: resolve each asset individually
            result = []
            for info in asset_infos:
                existing = self._lookup_in_db(db, info.ticker, info.exchange)
                if existing is not None:
                    result.append(existing)
                else:
                    # Asset doesn't exist yet, create it individually
                    # (uses the race-condition-safe _create_asset)
                    result.append(self._create_asset(db, info))
            return result

    def clear_cache(self) -> None:
        """
        Clear the in-memory cache.

        Useful for testing or when you want to force fresh data from the provider.
        """
        self._cache.clear()
        logger.debug("Asset resolution cache cleared")

    @property
    def provider_name(self) -> str:
        """Get the name of the configured provider."""
        return self._provider.name

    @property
    def cache_size(self) -> int:
        """Get the current number of cached entries."""
        return len(self._cache)
