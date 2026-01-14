# backend/app/schemas/__init__.py
"""
Pydantic schemas for API request/response validation.

Usage:
    from app.schemas import AssetCreate, AssetResponse
    from app.schemas import PortfolioCreate, PortfolioResponse
    from app.schemas import TransactionCreate, TransactionResponse
"""

from app.schemas.assets import (
    AssetBase,
    AssetCreate,
    AssetUpdate,
    AssetResponse,
    AssetListResponse,
)

from app.schemas.portfolios import (
    PortfolioBase,
    PortfolioCreate,
    PortfolioUpdate,
    PortfolioResponse,
    PortfolioListResponse
)

from app.schemas.transactions import (
    TransactionBase,
    TransactionCreate,
    TransactionUpdate,
    TransactionResponse,
    TransactionListResponse,
    TransactionWithTotalsResponse,
)

# Will be added as we create them:
# from app.schemas.user import (...)

__all__ = [
    # Asset
    "AssetBase",
    "AssetCreate",
    "AssetUpdate",
    "AssetResponse",
    "AssetListResponse",

    # Portfolio
    "PortfolioBase",
    "PortfolioCreate",
    "PortfolioUpdate",
    "PortfolioResponse",
    "PortfolioListResponse",

    # Transaction
    "TransactionBase",
    "TransactionCreate",
    "TransactionUpdate",
    "TransactionResponse",
    "TransactionListResponse",
    "TransactionWithTotalsResponse",
]
