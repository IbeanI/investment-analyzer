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

from sqlalchemy import select, and_, or_
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


class AssetResolutionService:
    """
    Service for resolving ticker + exchange to database Asset entities.

    This service provides automatic asset creation by:
    1. Looking up existing assets in the database
    2. Fetching metadata from market data providers for unknown assets
    3. Creating new asset records automatically

    The service maintains an in-memory cache for provider responses to avoid
    redundant API calls within the same application lifecycle.

    Attributes:
        _provider: Market data provider for fetching asset metadata
        _cache: In-memory cache for provider responses

    Example:
        # Using default provider (Yahoo Finance)
        service = AssetResolutionService()
        asset = service.resolve_asset(db, "NVDA", "NASDAQ")

        # Using custom provider (for testing or alternative sources)
        mock_provider = MockMarketDataProvider()
        service = AssetResolutionService(provider=mock_provider)
    """

    def __init__(self, provider: MarketDataProvider | None = None) -> None:
        """
        Initialize the asset resolution service.

        Args:
            provider: Market data provider to use for fetching asset metadata.
                      Defaults to YahooFinanceProvider if not specified.
                      Pass a custom provider for testing or alternative data sources.
        """
        self._provider = provider or YahooFinanceProvider()
        self._cache: dict[tuple[str, str], AssetInfo] = {}

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
        exchange = exchange.strip().upper() if exchange else "NYSE"  # Explicit default here

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
    ) -> dict[tuple[str, str], Asset]:
        """
        Batch resolve assets (Lookup DB -> Fetch Missing -> Create New).

        Efficiently handles multiple asset resolutions in a single pass.

        Args:
            db: Database session
            requests: List of (ticker, exchange) tuples

        Returns:
            Map of (ticker, exchange) -> Asset object.
            Failed resolutions are simply omitted from the result.
        """
        # 1. Normalize inputs
        normalized_reqs = list(set((t.strip().upper(), e.strip().upper()) for t, e in requests))
        results = {}
        missing = []

        if not normalized_reqs:
            return {}

        # 2. Batch DB Lookup
        # Build OR conditions to match any of the pairs
        conditions = [
            and_(Asset.ticker == t, Asset.exchange == e)
            for t, e in normalized_reqs
        ]

        # Fetch existing assets (one query instead of N)
        existing_assets = db.scalars(select(Asset).where(or_(*conditions))).all()

        # Index existing assets
        for asset in existing_assets:
            key = (asset.ticker, asset.exchange)
            if asset.is_active:
                results[key] = asset
            else:
                logger.warning(f"Batch resolve: Asset {key} is deactivated")

        # 3. Identify Missing
        for req in normalized_reqs:
            if req not in results:
                missing.append(req)

        if not missing:
            return results

        # 4. Batch Provider Fetch
        logger.info(f"Batch resolving {len(missing)} missing assets")

        # Check cache first
        really_missing = []
        for req in missing:
            if req in self._cache:
                # We have the metadata in memory, but need to create the DB object
                info = self._cache[req]
                try:
                    new_asset = self._create_asset(db, info)
                    results[req] = new_asset
                except Exception as e:
                    logger.error(f"Failed to create cached asset {req}: {e}")
            else:
                really_missing.append(req)

        if not really_missing:
            return results

        # Call Provider (Batch)
        batch_result = self._provider.get_asset_info_batch(really_missing)

        # 5. Create New Assets from Provider Results
        for key, info in batch_result.successful.items():
            self._cache[key] = info  # Update cache
            try:
                new_asset = self._create_asset(db, info)
                results[key] = new_asset
            except Exception as e:
                logger.error(f"Failed to create new asset {key}: {e}")

        # Log failures from provider
        for key, error in batch_result.failed.items():
            logger.error(f"Failed to resolve {key} from provider: {error}")

        return results

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
        if cache_key in self._cache:
            logger.debug(f"Cache hit for {ticker} on {exchange}")
            return self._cache[cache_key]

        # Fetch from provider
        logger.debug(f"Cache miss for {ticker} on {exchange}, calling provider")
        asset_info = self._provider.get_asset_info(ticker, exchange)

        # Cache the result
        self._cache[cache_key] = asset_info
        logger.debug(f"Cached asset info for {ticker} on {exchange}")

        return asset_info

    def _create_asset(self, db: Session, asset_info: AssetInfo) -> Asset:
        """
        Create a new Asset in the database from provider data.

        Args:
            db: Database session
            asset_info: Metadata from market data provider

        Returns:
            Newly created and persisted Asset entity
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
        db.commit()
        db.refresh(asset)

        return asset

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
