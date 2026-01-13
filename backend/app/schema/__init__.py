# backend/app/schema/__init__.py
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

from app.schema.portfolios import (
    PortfolioBase,
    PortfolioCreate,
    PortfolioUpdate,
    PortfolioResponse,
    PortfolioListResponse
)

from app.schema.transactions import (
    TransactionBase,
    TransactionCreate,
    TransactionUpdate,
    TransactionResponse,
    TransactionListResponse,
    TransactionWithTotalsResponse,
)

# Will be added as we create them:
# from app.schema.user import (...)

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
