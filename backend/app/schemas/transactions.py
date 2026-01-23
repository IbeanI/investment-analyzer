# backend/app/schemas/transactions.py
"""
Pydantic schemas for Transaction validation.

These schemas define:
- What data clients must send (Create)
- What data clients can update (Update)
- What data the API returns (Response)

Validation layers:
- Field constraints: type, length, pattern, numeric limits
- Field validators: normalization (uppercase, trim), logical checks
- Router: existence checks, ownership verification

IMPORTANT: All financial values use Decimal for precision.
Never use float for money!
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import TransactionType
from app.schemas.assets import AssetResponse
from app.schemas.pagination import PaginationMeta
from app.schemas.validators import validate_ticker, validate_exchange


# =============================================================================
# BASE SCHEMA
# =============================================================================

class TransactionBase(BaseModel):
    """
    Base schemas with fields common to Create and Response.

    Financial fields use Decimal for precision.
    """

    date: datetime = Field(
        ...,
        description="Date and time when the trade was executed",
        examples=["2026-01-15T14:30:00Z"]
    )

    quantity: Decimal = Field(
        ...,
        gt=0,
        max_digits=18,
        decimal_places=8,
        description="Number of shares/units traded (must be positive)",
        examples=["10", "0.5", "100.12345678"]
    )

    price_per_share: Decimal = Field(
        ...,
        gt=0,
        max_digits=18,
        decimal_places=8,
        description="Price per share at time of trade (must be positive)",
        examples=["150.50", "0.00001234"]
    )

    currency: str = Field(
        default="EUR",
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="Currency of the trade (ISO 4217)",
        examples=["EUR", "USD", "GBP"]
    )

    fee: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        max_digits=18,
        decimal_places=8,
        description="Transaction fee/commission (0 or positive)",
        examples=["0", "9.99", "0.001"]
    )

    fee_currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="Currency of the fee (defaults to transaction currency if not provided)",
        examples=["EUR", "USD"]
    )

    exchange_rate: Decimal | None = Field(
        default=Decimal("1"),
        gt=0,
        max_digits=18,
        decimal_places=8,
        description=(
            "Broker's FX rate at time of trade. Format: 1 portfolio_currency = X transaction_currency. "
            "Example: If portfolio is EUR and you buy USD stock, rate 1.10 means 1 EUR = 1.10 USD. "
            "Set to 1 if transaction currency matches portfolio currency."
        ),
        examples=["1", "1.0856", "0.8543"]
    )

    # =========================================================================
    # FIELD VALIDATORS (Normalization & Validation)
    # =========================================================================

    @field_validator('date')
    @classmethod
    def validate_date_not_in_future(cls, v: datetime) -> datetime:
        """Prevent recording transactions that haven't happened yet."""
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)

        current_time = datetime.now(timezone.utc)
        if v > current_time:
            raise ValueError(f"Transaction date cannot be in the future (sent: {v}, now: {current_time})")
        return v

    @field_validator('currency')
    @classmethod
    def normalize_currency(cls, v: str) -> str:
        """Normalize currency: trim whitespace and uppercase."""
        return v.strip().upper()

    @field_validator('fee_currency')
    @classmethod
    def normalize_fee_currency(cls, v: str | None) -> str | None:
        """Normalize fee_currency: trim whitespace and uppercase, or None."""
        if v is None:
            return None
        return v.strip().upper()


# =============================================================================
# CREATE SCHEMA
# =============================================================================

class TransactionCreate(TransactionBase):
    """
    Schema for creating a new transaction.

    Requires portfolio_id, ticker, exchange, and transaction_type which cannot be changed after creation.
    """

    portfolio_id: int = Field(
        ...,
        gt=0,
        description="ID of the portfolio this transaction belongs to"
    )

    ticker: str = Field(
        ...,
        min_length=1,
        max_length=10,
        description="Trading symbol (e.g., 'AAPL', 'NVDA')",
        examples=["AAPL", "NVDA", "MSFT"]
    )

    exchange: str = Field(
        ...,
        min_length=0,
        max_length=10,
        description="Stock exchange (e.g., 'NASDAQ', 'XETRA')",
        examples=["NASDAQ", "NYSE", "XETRA"]
    )

    transaction_type: TransactionType = Field(
        ...,
        description="Type of transaction",
        examples=[TransactionType.BUY, TransactionType.SELL]
    )

    # =========================================================================
    # FIELD VALIDATORS (Normalization)
    # =========================================================================

    @field_validator('ticker')
    @classmethod
    def validate_and_normalize_ticker(cls, v: str) -> str:
        """Validate and normalize ticker symbol."""
        return validate_ticker(v)

    @field_validator('exchange')
    @classmethod
    def validate_and_normalize_exchange(cls, v: str) -> str:
        """Validate and normalize exchange code."""
        return validate_exchange(v)


# =============================================================================
# UPDATE SCHEMA
# =============================================================================

class TransactionUpdate(BaseModel):
    """
    Schema for updating an existing transaction.

    All fields are optional — client only sends fields to update.

    Note: portfolio_id, asset_id, and transaction_type CANNOT be changed.
    To change these, delete the transaction and create a new one.
    """

    date: datetime | None = Field(
        default=None,
        description="Corrected trade date"
    )

    quantity: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=8,
        description="Corrected quantity"
    )

    price_per_share: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=8,
        description="Corrected price per share"
    )

    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$"
    )

    fee: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=8
    )

    fee_currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$"
    )

    exchange_rate: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=8
    )

    # =========================================================================
    # FIELD VALIDATORS (Normalization & Validation)
    # =========================================================================

    @field_validator('date')
    @classmethod
    def validate_date_not_in_future(cls, v: datetime | None) -> datetime | None:
        """Prevent recording transactions that haven't happened yet."""
        if v is None:
            return None
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)

        current_time = datetime.now(timezone.utc)
        if v > current_time:
            raise ValueError(f"Transaction date cannot be in the future")
        return v

    @field_validator('currency', 'fee_currency')
    @classmethod
    def normalize_currency(cls, v: str | None) -> str | None:
        """Normalize currency: trim whitespace and uppercase."""
        if v is None:
            return None
        return v.strip().upper()


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================

class TransactionResponse(TransactionBase):
    """
    Schema for API responses.

    Includes all database-generated fields and foreign keys.
    """

    id: int = Field(..., description="Unique identifier")
    portfolio_id: int = Field(..., description="ID of the portfolio")
    asset_id: int = Field(..., description="ID of the asset")
    transaction_type: TransactionType = Field(..., description="Transaction type (BUY/SELL)")
    created_at: datetime = Field(..., description="When the transaction was recorded")
    asset: AssetResponse = Field(..., description="Full asset details")

    model_config = ConfigDict(from_attributes=True)


class TransactionListResponse(BaseModel):
    """
    Response schema for paginated transaction list.

    Attributes:
        items: List of transactions for current page
        pagination: Pagination metadata with computed fields
    """

    items: list[TransactionResponse] = Field(..., description="List of transactions for current page")
    pagination: PaginationMeta = Field(..., description="Pagination metadata")


# =============================================================================
# EXTENDED RESPONSE (Future Use)
# =============================================================================

class TransactionWithTotalsResponse(TransactionResponse):
    """
    Extended response that includes computed totals.

    This schema is defined but not yet used in any endpoint.
    It will be used for transaction details with calculated values
    when detailed transaction views are implemented.
    """

    total_value: Decimal = Field(
        ...,
        description="quantity × price_per_share"
    )

    total_cost: Decimal = Field(
        ...,
        description="total_value + fee (for BUY) or total_value - fee (for SELL)"
    )


# =============================================================================
# BATCH OPERATION SCHEMAS
# =============================================================================


class BatchTransactionError(BaseModel):
    """
    Detailed error information for a single transaction in a batch operation.

    Attributes:
        index: 0-based index of the transaction in the request array
        ticker: Asset ticker (if available)
        stage: Processing stage where error occurred
        error_type: Category of error
        message: Human-readable error description
        field: Specific field that caused the error (if applicable)
    """

    index: int = Field(..., description="0-based index in the batch request array")
    ticker: str | None = Field(default=None, description="Asset ticker symbol")
    stage: str = Field(
        ...,
        description="Processing stage: 'validation', 'asset_resolution', 'sell_quantity', 'persistence'"
    )
    error_type: str = Field(
        ...,
        description="Error category: 'not_found', 'deactivated', 'insufficient_quantity', etc."
    )
    message: str = Field(..., description="Human-readable error description")
    field: str | None = Field(default=None, description="Specific field that caused the error")


class BatchTransactionErrorResponse(BaseModel):
    """
    Response schema for batch transaction failures.

    This response is returned when a batch create operation fails validation.
    All errors are aggregated and returned together so clients can show
    comprehensive error information to users.

    The operation is atomic: if ANY transaction fails validation,
    NONE are created. This prevents partial states in financial data.

    Attributes:
        status: Always "error" for this response type
        total_requested: Number of transactions in the request
        error_count: Number of transactions that failed
        errors: Detailed per-transaction error information
    """

    status: Literal["error"] = Field(default="error", description="Status indicator")
    total_requested: int = Field(..., description="Number of transactions in request")
    error_count: int = Field(..., description="Number of transactions with errors")
    errors: list[BatchTransactionError] = Field(..., description="Detailed error list")
