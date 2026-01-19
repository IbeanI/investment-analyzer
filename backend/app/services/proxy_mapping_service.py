# backend/app/services/proxy_mapping_service.py
"""
Proxy Mapping Service for managing asset proxy relationships.

This service handles:
- Loading proxy mappings from configuration (JSON file)
- Applying mappings to portfolio assets during sync
- Resolving proxy assets (creating if needed via AssetResolutionService)
- Reporting which mappings were applied/skipped/failed

Design Principles:
- Single Responsibility: Only handles proxy mapping logic
- Dependency Injection: AssetResolutionService injected via constructor
- Configuration Driven: Mappings loaded from JSON (future: database)
- Fail Gracefully: Continue if some mappings fail, report all issues
- Idempotent: Safe to call multiple times (won't overwrite existing proxies)

Mapping File Format (proxy_mappings.json):
    {
        "CLWD.SBF": {
            "proxy_ticker": "D6RP.DE",
            "description": "Lyxor MSCI World Climate → Deka MSCI World Climate ESG"
        }
    }

Usage:
    from app.services.proxy_mapping_service import ProxyMappingService

    service = ProxyMappingService()

    # Apply mappings to portfolio assets
    result = service.apply_mappings(db, assets)

    print(f"Applied: {result.total_applied}")
    print(f"Skipped: {len(result.skipped)}")
    for warning in result.warnings:
        print(f"Warning: {warning}")
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.models import Asset
from app.services.exceptions import AssetNotFoundError, AssetDeactivatedError

if TYPE_CHECKING:
    from app.services.asset_resolution import AssetResolutionService

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

# Default path to proxy mappings JSON file
DEFAULT_MAPPINGS_PATH = (
        Path(__file__).parent.parent.parent / "scripts" / "seed_data" / "proxy_mappings.json"
)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ProxyConfig:
    """Configuration for a single proxy mapping."""

    proxy_ticker: str
    proxy_exchange: str
    description: str


@dataclass
class ProxyApplied:
    """Record of a successfully applied proxy mapping."""

    asset_id: int
    ticker: str
    exchange: str
    proxy_asset_id: int
    proxy_ticker: str
    proxy_exchange: str
    description: str


@dataclass
class ProxySkipped:
    """Record of a skipped proxy mapping."""

    asset_id: int
    ticker: str
    exchange: str
    reason: str  # "already_has_proxy" | "no_mapping_found"


@dataclass
class ProxyFailed:
    """Record of a failed proxy mapping."""

    asset_id: int
    ticker: str
    exchange: str
    proxy_ticker: str
    proxy_exchange: str
    error: str


@dataclass
class ProxyMappingResult:
    """Complete result of applying proxy mappings to portfolio assets."""

    applied: list[ProxyApplied] = field(default_factory=list)
    skipped: list[ProxySkipped] = field(default_factory=list)
    failed: list[ProxyFailed] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_applied(self) -> int:
        """Number of proxy mappings successfully applied."""
        return len(self.applied)

    @property
    def total_skipped(self) -> int:
        """Number of assets skipped (already had proxy or no mapping)."""
        return len(self.skipped)

    @property
    def total_failed(self) -> int:
        """Number of proxy mappings that failed."""
        return len(self.failed)

    @property
    def has_failures(self) -> bool:
        """True if any mappings failed to apply."""
        return len(self.failed) > 0

    @property
    def has_changes(self) -> bool:
        """True if any mappings were applied."""
        return len(self.applied) > 0


# =============================================================================
# ASSET INFO TYPE (for apply_mappings input)
# =============================================================================

@dataclass
class AssetInfo:
    """
    Minimal asset information needed for proxy mapping.

    This matches the AssetSyncInfo pattern from sync_service.py
    to allow easy integration.
    """

    asset_id: int
    ticker: str
    exchange: str


# =============================================================================
# SERVICE
# =============================================================================

class ProxyMappingService:
    """
    Service for managing proxy asset mappings.

    Handles loading proxy configurations from JSON and applying them
    to assets during sync operations.

    The service maintains an in-memory cache of mappings, loaded once
    at initialization. Call reload_mappings() to refresh from disk.

    Attributes:
        _mappings: Dict of normalized key → ProxyConfig
        _asset_service: Service for resolving/creating proxy assets
        _mappings_path: Path to JSON configuration file

    Example:
        service = ProxyMappingService()

        # Check if a mapping exists
        config = service.get_mapping("CLWD", "SBF")
        if config:
            print(f"Proxy: {config.proxy_ticker}")

        # Apply mappings to a list of assets
        assets = [AssetInfo(1, "CLWD", "SBF"), AssetInfo(2, "IWDA", "AEB")]
        result = service.apply_mappings(db, assets)
    """

    def __init__(
            self,
            asset_service: AssetResolutionService | None = None,
            mappings_path: Path | None = None,
    ) -> None:
        """
        Initialize the proxy mapping service.

        Args:
            asset_service: Asset resolution service for creating proxy assets.
                          If None, creates a new instance.
            mappings_path: Path to JSON mappings file.
                          If None, uses default path.
        """
        # Lazy import to avoid circular dependencies
        if asset_service is None:
            from app.services.asset_resolution import AssetResolutionService
            asset_service = AssetResolutionService()

        self._asset_service = asset_service
        self._mappings_path = mappings_path or DEFAULT_MAPPINGS_PATH
        self._mappings: dict[str, ProxyConfig] = {}

        # Load mappings on init
        self._load_mappings()

        logger.info(
            f"ProxyMappingService initialized with {len(self._mappings)} mappings"
        )

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def get_mapping(
            self,
            ticker: str,
            exchange: str,
    ) -> ProxyConfig | None:
        """
        Get proxy configuration for a ticker/exchange combination.

        Args:
            ticker: Asset ticker (e.g., "CLWD")
            exchange: Asset exchange (e.g., "SBF")

        Returns:
            ProxyConfig if mapping exists, None otherwise
        """
        key = self._normalize_key(ticker, exchange)
        return self._mappings.get(key)

    def has_mapping(
            self,
            ticker: str,
            exchange: str,
    ) -> bool:
        """
        Check if a proxy mapping exists for a ticker/exchange.

        Args:
            ticker: Asset ticker
            exchange: Asset exchange

        Returns:
            True if mapping exists
        """
        return self.get_mapping(ticker, exchange) is not None

    def apply_mappings(
            self,
            db: Session,
            assets: list[AssetInfo] | list[Asset],
    ) -> ProxyMappingResult:
        """
        Apply proxy mappings to a list of assets.

        For each asset:
        1. Skip if asset already has a proxy_asset_id set
        2. Skip if no mapping exists for this ticker/exchange
        3. Resolve proxy asset (create if needed)
        4. Update asset.proxy_asset_id and asset.proxy_notes

        This method is idempotent - calling it multiple times won't
        overwrite existing proxy assignments.

        Args:
            db: Database session
            assets: List of assets to apply mappings to

        Returns:
            ProxyMappingResult with details of what was applied/skipped/failed
        """
        result = ProxyMappingResult()

        if not assets:
            logger.debug("No assets to apply mappings to")
            return result

        logger.info(f"Applying proxy mappings to {len(assets)} assets")

        for asset_info in assets:
            # Normalize to AssetInfo if Asset model passed
            if isinstance(asset_info, Asset):
                asset_id = asset_info.id
                ticker = asset_info.ticker
                exchange = asset_info.exchange
            else:
                asset_id = asset_info.asset_id
                ticker = asset_info.ticker
                exchange = asset_info.exchange

            # Get the actual Asset from DB to check/update proxy
            asset = db.get(Asset, asset_id)
            if asset is None:
                result.warnings.append(f"Asset {asset_id} not found in database")
                continue

            # Skip if already has proxy
            if asset.proxy_asset_id is not None:
                result.skipped.append(ProxySkipped(
                    asset_id=asset_id,
                    ticker=ticker,
                    exchange=exchange,
                    reason="already_has_proxy",
                ))
                continue

            # Check if mapping exists
            config = self.get_mapping(ticker, exchange)
            if config is None:
                result.skipped.append(ProxySkipped(
                    asset_id=asset_id,
                    ticker=ticker,
                    exchange=exchange,
                    reason="no_mapping_found",
                ))
                continue

            # Try to resolve and apply proxy
            try:
                proxy_asset = self._resolve_proxy(
                    db, config.proxy_ticker, config.proxy_exchange
                )

                # Update asset with proxy
                asset.proxy_asset_id = proxy_asset.id
                asset.proxy_notes = config.description
                db.commit()

                result.applied.append(ProxyApplied(
                    asset_id=asset_id,
                    ticker=ticker,
                    exchange=exchange,
                    proxy_asset_id=proxy_asset.id,
                    proxy_ticker=config.proxy_ticker,
                    proxy_exchange=config.proxy_exchange,
                    description=config.description,
                ))

                logger.info(
                    f"Applied proxy mapping: {ticker}/{exchange} → "
                    f"{config.proxy_ticker}/{config.proxy_exchange}"
                )

            except (AssetNotFoundError, AssetDeactivatedError) as e:
                result.failed.append(ProxyFailed(
                    asset_id=asset_id,
                    ticker=ticker,
                    exchange=exchange,
                    proxy_ticker=config.proxy_ticker,
                    proxy_exchange=config.proxy_exchange,
                    error=str(e),
                ))
                result.warnings.append(
                    f"Failed to resolve proxy {config.proxy_ticker}/{config.proxy_exchange} "
                    f"for {ticker}/{exchange}: {e}"
                )

            except Exception as e:
                result.failed.append(ProxyFailed(
                    asset_id=asset_id,
                    ticker=ticker,
                    exchange=exchange,
                    proxy_ticker=config.proxy_ticker,
                    proxy_exchange=config.proxy_exchange,
                    error=str(e),
                ))
                result.warnings.append(
                    f"Unexpected error applying proxy for {ticker}/{exchange}: {e}"
                )
                logger.exception(f"Error applying proxy mapping for {ticker}/{exchange}")

        # Log summary
        logger.info(
            f"Proxy mapping complete: {result.total_applied} applied, "
            f"{result.total_skipped} skipped, {result.total_failed} failed"
        )

        return result

    def reload_mappings(self) -> int:
        """
        Reload mappings from the configuration file.

        Call this if the JSON file has been updated and you want
        to pick up the changes without restarting the service.

        Returns:
            Number of mappings loaded
        """
        self._load_mappings()
        return len(self._mappings)

    def get_all_mappings(self) -> dict[str, ProxyConfig]:
        """
        Get all loaded proxy mappings.

        Returns:
            Dict of normalized key → ProxyConfig
        """
        return self._mappings.copy()

    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================

    def _load_mappings(self) -> None:
        """Load proxy mappings from JSON file."""
        self._mappings = {}

        if not self._mappings_path.exists():
            logger.warning(
                f"Proxy mappings file not found: {self._mappings_path}. "
                f"No proxy mappings will be available."
            )
            return

        try:
            with open(self._mappings_path, "r") as f:
                raw_mappings = json.load(f)

            for symbol, config in raw_mappings.items():
                # Parse the symbol (e.g., "CLWD.SBF" → ticker="CLWD", exchange="SBF")
                ticker, exchange = self._parse_symbol(symbol)
                proxy_ticker, proxy_exchange = self._parse_symbol(config["proxy_ticker"])

                key = self._normalize_key(ticker, exchange)
                self._mappings[key] = ProxyConfig(
                    proxy_ticker=proxy_ticker,
                    proxy_exchange=proxy_exchange,
                    description=config.get("description", ""),
                )

            logger.info(f"Loaded {len(self._mappings)} proxy mappings from {self._mappings_path}")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in proxy mappings file: {e}")
        except Exception as e:
            logger.exception(f"Error loading proxy mappings: {e}")

    def _parse_symbol(self, symbol: str) -> tuple[str, str]:
        """
        Parse a Yahoo-style symbol into ticker and exchange.

        Examples:
            "CLWD.SBF" → ("CLWD", "SBF")
            "D6RP.DE" → ("D6RP", "XETRA")
            "AAPL" → ("AAPL", "NASDAQ")

        Args:
            symbol: Yahoo-style symbol

        Returns:
            Tuple of (ticker, exchange)
        """
        # Mapping of Yahoo suffixes to exchange codes
        yahoo_to_exchange = {
            "DE": "XETRA",
            "AS": "AEB",
            "L": "LSE",
            "PA": "EPA",
            "MI": "BVME",
            "SW": "SWX",
            "TO": "TSX",
            "AX": "ASX",
            "HK": "HKEX",
            "T": "TSE",
            "SBF": "SBF",
            "IBIS2": "IBIS2",
            "TGATE": "TGATE",
        }

        if "." in symbol:
            parts = symbol.rsplit(".", 1)
            ticker = parts[0].upper()
            suffix = parts[1].upper()
            exchange = yahoo_to_exchange.get(suffix, suffix)
        else:
            ticker = symbol.upper()
            exchange = "NASDAQ"  # Default for symbols without suffix

        return ticker, exchange

    def _normalize_key(self, ticker: str, exchange: str) -> str:
        """
        Create a normalized lookup key from ticker and exchange.

        Args:
            ticker: Asset ticker
            exchange: Asset exchange

        Returns:
            Normalized key string (e.g., "CLWD:SBF")
        """
        return f"{ticker.upper()}:{exchange.upper()}"

    def _resolve_proxy(
            self,
            db: Session,
            proxy_ticker: str,
            proxy_exchange: str,
    ) -> Asset:
        """
        Resolve a proxy asset, creating it if needed.

        Args:
            db: Database session
            proxy_ticker: Proxy asset ticker
            proxy_exchange: Proxy asset exchange

        Returns:
            Resolved Asset

        Raises:
            AssetNotFoundError: If proxy can't be found on Yahoo
            AssetDeactivatedError: If proxy exists but is deactivated
        """
        return self._asset_service.resolve_asset(
            db=db,
            ticker=proxy_ticker,
            exchange=proxy_exchange,
        )
