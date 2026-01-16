# backend/app/schemas/__init__.py
"""
Pydantic schemas for API request/response validation.

Usage:
    from app.schemas import AssetCreate, AssetResponse
    from app.schemas import PortfolioCreate, PortfolioResponse
    from app.schemas import TransactionCreate, TransactionResponse
    from app.schemas import UploadResponse, UploadErrorResponse
    from app.schemas import SyncResult, SyncStatusResponse
    from app.schemas import PortfolioValuationResponse
    from app.schemas import ExchangeRateResponse
"""

from app.schemas.assets import (
    AssetBase,
    AssetCreate,
    AssetUpdate,
    AssetResponse,
    AssetListResponse,
)
from app.schemas.exchange_rates import (
    ExchangeRateResponse,
    ExchangeRateRangeResponse,
    ExchangeRateLookup,
)
from app.schemas.market_data import (
    MarketDataSyncRequest,
    MarketDataRefreshRequest,
    SyncStatusResponse,
    SyncResult,
    SyncWarning,
    AssetCoverage,
    FXCoverage,
    CoverageSummary,
    MarketDataPointResponse,
    MarketDataRangeResponse,
)
from app.schemas.portfolio_settings import (
    PortfolioSettingsResponse,
    PortfolioSettingsUpdate,
    PortfolioSettingsUpdateResponse,
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
from app.schemas.upload import (
    UploadResponse,
    UploadErrorResponse,
    SupportedFormatsResponse,
)
from app.schemas.valuation import (
    CostBasisDetail,
    CurrentValueDetail,
    PnLDetail,
    HoldingValuation,
    CashBalanceDetail,
    PortfolioValuationSummary,
    PortfolioValuationResponse,
    ValuationHistoryPoint,
    PortfolioHistoryResponse,
    ValuationRequest,
    ValuationHistoryRequest,
)
from app.schemas.errors import (
    ErrorDetail,
    ValidationErrorDetail,
)

# =============================================================================
# PHASE 3: Market Data Engine
# =============================================================================

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

    # Upload
    "UploadResponse",
    "UploadErrorResponse",
    "SupportedFormatsResponse",

    # ==========================================================================
    # Phase 3: Market Data Engine
    # ==========================================================================

    # Exchange Rates
    "ExchangeRateResponse",
    "ExchangeRateRangeResponse",
    "ExchangeRateLookup",

    # Portfolio Settings
    "PortfolioSettingsResponse",
    "PortfolioSettingsUpdate",
    "PortfolioSettingsUpdateResponse",

    # Market Data Sync
    "MarketDataSyncRequest",
    "MarketDataRefreshRequest",
    "SyncStatusResponse",
    "SyncResult",
    "SyncWarning",
    "AssetCoverage",
    "FXCoverage",
    "CoverageSummary",
    "MarketDataPointResponse",
    "MarketDataRangeResponse",

    # Valuation
    "CostBasisDetail",
    "CurrentValueDetail",
    "PnLDetail",
    "HoldingValuation",
    "CashBalanceDetail",
    "PortfolioValuationSummary",
    "PortfolioValuationResponse",
    "ValuationHistoryPoint",
    "PortfolioHistoryResponse",
    "ValuationRequest",
    "ValuationHistoryRequest",

    # Errors
    "ErrorDetail",
    "ValidationErrorDetail",
]
