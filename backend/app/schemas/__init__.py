# backend/app/schemas/__init__.py
"""
Pydantic schemas for API request/response validation.

This package contains all Pydantic schemas organized by domain:
- analytics: Portfolio analytics (performance, risk, benchmark)
- assets: Asset CRUD operations
- errors: Error response formats
- exchange_rates: FX rate responses and lookups
- market_data: Market data sync requests/responses
- pagination: Standardized pagination for list endpoints
- portfolio_settings: Portfolio preferences (backcasting, etc.)
- portfolios: Portfolio CRUD operations
- transactions: Transaction CRUD operations
- upload: File upload responses and error details
- validators: Reusable validation functions (ticker, exchange, currency)
- valuation: Portfolio valuation (holdings, P&L, history)

Usage:
    from app.schemas import AssetCreate, AssetResponse
    from app.schemas import PortfolioCreate, PortfolioResponse
    from app.schemas import TransactionCreate, TransactionResponse
    from app.schemas import UploadResponse, UploadErrorResponse
    from app.schemas import SyncResult, SyncStatusResponse
    from app.schemas import PortfolioValuationResponse
    from app.schemas import ExchangeRateResponse
    from app.schemas import PaginationMeta, PaginatedResponse
"""

from app.schemas.analytics import (
    # Period info
    PeriodInfo,
    # Performance
    PerformanceMetricsResponse,
    PerformanceResponse,
    # Risk
    DrawdownPeriodResponse,
    RiskMetricsResponse,
    RiskResponse,
    # Benchmark
    BenchmarkMetricsResponse,
    BenchmarkResponse,
    # Combined
    AnalyticsResponse,
    AnalyticsQueryParams,
)
from app.schemas.assets import (
    AssetBase,
    AssetCreate,
    AssetUpdate,
    AssetResponse,
    AssetListResponse,
)
from app.schemas.errors import (
    ErrorDetail,
    ValidationErrorDetail,
)
from app.schemas.exchange_rates import (
    ExchangeRateResponse,
    ExchangeRateRangeResponse,
    ExchangeRateLookup,
)
from app.schemas.pagination import (
    PaginationMeta,
    PaginatedResponse,
    create_pagination_meta,
    paginate_dict,
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

    # Analytics schemas
    "PeriodInfo",
    "PerformanceMetricsResponse",
    "PerformanceResponse",
    "DrawdownPeriodResponse",
    "RiskMetricsResponse",
    "RiskResponse",
    "BenchmarkMetricsResponse",
    "BenchmarkResponse",
    "AnalyticsResponse",
    "AnalyticsQueryParams",

    # Pagination
    "PaginationMeta",
    "PaginatedResponse",
    "create_pagination_meta",
    "paginate_dict",
]
