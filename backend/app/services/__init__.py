# backend/app/services/__init__.py
"""
Service layer for business logic.

This package contains the service layer which encapsulates business logic
separate from the API (router) layer. Services:
- Have NO knowledge of HTTP (no HTTPException, no status codes)
- Raise domain-specific exceptions
- Receive database sessions as parameters (not via Depends)
- Are easily testable via dependency injection

Usage:
    from app.services import AssetResolutionService
    from app.services import (
        AssetNotFoundError,
        AssetDeactivatedError,
        MarketDataError,
    )

    # In router
    service = AssetResolutionService()
    try:
        asset = service.resolve_asset(db, ticker, exchange)
    except AssetNotFoundError:
        raise HTTPException(status_code=404, ...)

Architecture:
    services/
    ├── __init__.py              # This file - main exports
    ├── exceptions.py            # Domain exceptions
    ├── asset_resolution.py      # Asset resolution service
    └── market_data/             # Market data providers
        ├── base.py              # Abstract interface
        └── yahoo.py             # Yahoo Finance implementation
"""

from app.services.asset_resolution import AssetResolutionService
from app.services.exceptions import (
    # Base exceptions
    ServiceError,
    # Asset resolution exceptions
    AssetResolutionError,
    AssetNotFoundError,
    AssetDeactivatedError,
    # Market data exceptions
    MarketDataError,
    ProviderUnavailableError,
    TickerNotFoundError,
    RateLimitError,
)

__all__ = [
    # Services
    "AssetResolutionService",
    # Base exceptions
    "ServiceError",
    # Asset resolution exceptions
    "AssetResolutionError",
    "AssetNotFoundError",
    "AssetDeactivatedError",
    # Market data exceptions
    "MarketDataError",
    "ProviderUnavailableError",
    "TickerNotFoundError",
    "RateLimitError",
]
