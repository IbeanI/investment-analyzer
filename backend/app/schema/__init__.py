# backend/app/schemas/__init__.py
"""
Pydantic schemas for API request/response validation.

Usage:
    from app.schemas import AssetCreate, AssetResponse
    from app.schemas import PortfolioCreate, PortfolioResponse
    from app.schemas import TransactionCreate, TransactionResponse
"""

from app.schema.assets import (
    AssetBase,
    AssetCreate,
    AssetUpdate,
    AssetResponse,
)

# Will be added as we create them:
# from app.schemas.portfolio import (...)
# from app.schemas.transaction import (...)
# from app.schemas.user import (...)

__all__ = [
    # Asset
    "AssetBase",
    "AssetCreate",
    "AssetUpdate",
    "AssetResponse",
]
