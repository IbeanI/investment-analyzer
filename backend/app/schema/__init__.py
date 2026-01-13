# backend/app/schemas/__init__.py
"""
Pydantic schemas for API request/response validation.

Usage:
    from app.schema import AssetCreate, AssetResponse
    from app.schema import PortfolioCreate, PortfolioResponse
    from app.schema import TransactionCreate, TransactionResponse
"""

from app.schema.assets import (
    AssetBase,
    AssetCreate,
    AssetUpdate,
    AssetResponse,
    AssetListResponse,
)

# Will be added as we create them:
# from app.schema.portfolio import (...)
# from app.schema.transaction import (...)
# from app.schema.user import (...)

__all__ = [
    # Asset
    "AssetBase",
    "AssetCreate",
    "AssetUpdate",
    "AssetResponse",
    "AssetListResponse",
]
