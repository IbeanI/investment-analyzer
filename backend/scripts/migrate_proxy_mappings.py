# backend/scripts/migrate_proxy_mappings.py
"""
One-time migration script to populate proxy_asset_id from legacy JSON config.

Uses AssetResolutionService to auto-create proxy assets if they don't exist.

Usage:
    cd backend
    python -m scripts.migrate_proxy_mappings

After successful migration, delete:
    - This script
    - The JSON file (scripts/seed_data/proxy_mappings.json)
"""

import json
import logging
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Asset
from app.services.asset_resolution import AssetResolutionService
from app.services.exceptions import (
    AssetNotFoundError,
    AssetDeactivatedError,
    MarketDataError,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Path to JSON file
JSON_PATH = Path(__file__).parent / "seed_data" / "proxy_mappings.json"


def parse_yahoo_symbol(symbol: str) -> tuple[str, str]:
    """
    Parse Yahoo-style symbol into (ticker, exchange).

    Examples:
        "CLWD.PA" -> ("CLWD", "EPA")
        "D6RP.DE" -> ("D6RP", "XETRA")
        "AAPL" -> ("AAPL", "NASDAQ")
    """
    yahoo_to_exchange = {
        "PA": "EPA",
        "DE": "XETRA",
        "AS": "AEB",
        "L": "LSE",
        "MI": "BVME",
        "SW": "SWX",
    }

    if "." in symbol:
        ticker, suffix = symbol.rsplit(".", 1)
        exchange = yahoo_to_exchange.get(suffix, suffix.upper())
    else:
        ticker = symbol
        exchange = "NASDAQ"

    return ticker.upper(), exchange.upper()


def migrate_proxy_mappings() -> None:
    """Load JSON and update database with proxy relationships."""

    if not JSON_PATH.exists():
        logger.error(f"JSON file not found: {JSON_PATH}")
        return

    with open(JSON_PATH) as f:
        mappings = json.load(f)

    logger.info(f"Loaded {len(mappings)} proxy mappings from JSON")

    db = SessionLocal()
    service = AssetResolutionService()

    try:
        success_count = 0
        skip_count = 0
        error_count = 0
        created_count = 0

        for target_symbol, config in mappings.items():
            proxy_symbol = config["proxy_ticker"]
            description = config.get("description", "")

            # Parse symbols
            target_ticker, target_exchange = parse_yahoo_symbol(target_symbol)
            proxy_ticker, proxy_exchange = parse_yahoo_symbol(proxy_symbol)

            logger.info(f"Processing: {target_ticker} -> {proxy_ticker}")

            # -----------------------------------------------------------------
            # STEP 1: Find TARGET (must exist — you own it)
            # -----------------------------------------------------------------
            target = db.scalar(
                select(Asset).where(
                    Asset.ticker == target_ticker,
                    Asset.exchange == target_exchange
                )
            )

            if not target:
                logger.warning(
                    f"  ⏭️  Target not in DB: {target_ticker} on {target_exchange}. "
                    f"Skipping (you don't own this asset)."
                )
                skip_count += 1
                continue

            # -----------------------------------------------------------------
            # STEP 2: Resolve PROXY (auto-create if missing)
            # -----------------------------------------------------------------
            try:
                proxy = service.resolve_asset(db, proxy_ticker, proxy_exchange)

                # Check if this was a new creation (not in DB before)
                # We can infer this by checking if it was just created
                if proxy.created_at == proxy.updated_at:
                    logger.info(f"  🆕 Created proxy asset: {proxy.ticker} ({proxy.id})")
                    created_count += 1

            except AssetNotFoundError:
                logger.error(
                    f"  ❌ Proxy not found on Yahoo: {proxy_ticker} on {proxy_exchange}. "
                    f"Cannot link."
                )
                error_count += 1
                continue

            except AssetDeactivatedError:
                logger.error(
                    f"  ❌ Proxy is deactivated: {proxy_ticker}. Cannot link."
                )
                error_count += 1
                continue

            except MarketDataError as e:
                logger.error(
                    f"  ❌ Market data error for {proxy_ticker}: {e}"
                )
                error_count += 1
                continue

            # -----------------------------------------------------------------
            # STEP 3: Link target to proxy
            # -----------------------------------------------------------------
            target.proxy_asset_id = proxy.id
            target.proxy_notes = description

            logger.info(
                f"  ✅ Linked: {target.ticker} ({target.id}) -> "
                f"{proxy.ticker} ({proxy.id})"
            )
            success_count += 1

        # Commit all changes
        db.commit()

        # Summary
        logger.info("=" * 60)
        logger.info("MIGRATION COMPLETE")
        logger.info("=" * 60)
        logger.info(f"  ✅ Successfully linked: {success_count}")
        logger.info(f"  🆕 Proxy assets created: {created_count}")
        logger.info(f"  ⏭️  Skipped (target not owned): {skip_count}")
        logger.info(f"  ❌ Errors: {error_count}")
        logger.info("=" * 60)

        if success_count > 0 and error_count == 0:
            logger.info("✨ Migration successful! You can now delete:")
            logger.info(f"   - {JSON_PATH}")
            logger.info(f"   - {__file__}")

    except Exception as e:
        db.rollback()
        logger.error(f"Migration failed with unexpected error: {e}")
        raise

    finally:
        db.close()


if __name__ == "__main__":
    migrate_proxy_mappings()
