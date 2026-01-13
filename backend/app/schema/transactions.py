# backend/app/schema/transactions.py
"""
Pydantic schemas for Transaction validation.

These schemas define:
- What data clients must send (Create)
- What data clients can update (Update)
- What data the API returns (Response)

IMPORTANT: All financial values use Decimal for precision.
Never use float for money!
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import TransactionType


class TransactionBase(BaseModel):
    """
    Base schema with fields common to Create and Response.

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

    fee_currency: str = Field(
        default="EUR",
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="Currency of the fee (may differ from trade currency)",
        examples=["EUR", "USD"]
    )

    exchange_rate: Decimal | None = Field(
        default=Decimal("1"),
        gt=0,
        max_digits=18,
        decimal_places=8,
        description="Exchange rate to portfolio base currency at time of trade",
        examples=["1", "1.0856", "0.8543"]
    )


class TransactionCreate(TransactionBase):
    """
    Schema for creating a new transaction.

    Requires portfolio_id, asset_id, and type which cannot be changed after creation.
    """

    portfolio_id: int = Field(
        ...,
        gt=0,
        description="ID of the portfolio this transaction belongs to"
    )

    asset_id: int = Field(
        ...,
        gt=0,
        description="ID of the asset being traded"
    )

    type: TransactionType = Field(
        ...,
        description="Type of transaction",
        examples=[TransactionType.BUY, TransactionType.SELL]
    )


class TransactionUpdate(BaseModel):
    """
    Schema for updating an existing transaction.

    All fields are optional — client only sends fields to update.

    Note: portfolio_id, asset_id, and type CANNOT be changed.
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


class TransactionResponse(TransactionBase):
    """
    Schema for API responses.

    Includes all database-generated fields and foreign keys.
    """

    id: int = Field(..., description="Unique identifier")
    portfolio_id: int = Field(..., description="ID of the portfolio")
    asset_id: int = Field(..., description="ID of the asset")
    type: TransactionType = Field(..., description="Transaction type (BUY/SELL)")
    created_at: datetime = Field(..., description="When the transaction was recorded")

    model_config = ConfigDict(from_attributes=True)


class TransactionListResponse(BaseModel):
    """
    Response schema for paginated transaction list.
    """

    items: list[TransactionResponse]
    total: int = Field(..., description="Total number of transactions matching filters")
    skip: int = Field(..., description="Number of records skipped")
    limit: int = Field(..., description="Maximum number of records returned")


# =============================================================================
# COMPUTED RESPONSE (for convenience)
# =============================================================================

class TransactionWithTotalsResponse(TransactionResponse):
    """
    Extended response that includes computed totals.

    Useful for displaying transaction details with calculated values.

    TODO: Implement in Phase 3 when building the analytics engine.
    Will be used for transaction details with calculated values.
    """

    total_value: Decimal = Field(
        ...,
        description="quantity × price_per_share"
    )

    total_cost: Decimal = Field(
        ...,
        description="total_value + fee (for BUY) or total_value - fee (for SELL)"
    )
