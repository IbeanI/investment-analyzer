# backend/app/schemas/assets.py
"""
Pydantic schemas for Asset validation.

These schemas define:
- What data clients must send (Create)
- What data clients can update (Update)
- What data the API returns (Response)

Validation layers:
- Field constraints: type, length, pattern
- Field validators: normalization (uppercase, trim)
- Router: existence checks, uniqueness
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import AssetClass


# =============================================================================
# BASE SCHEMA
# =============================================================================

class AssetBase(BaseModel):
    """
    Base schemas with fields common to Create and Response.
    """

    ticker: str = Field(
        ...,  # ... means required
        min_length=1,
        max_length=10,
        examples=["AAPL", "MSFT", "BTC-USD"],
        description="Trading symbol (e.g., 'AAPL' for Apple)"
    )

    exchange: str = Field(
        ...,
        min_length=1,
        max_length=10,
        examples=["NASDAQ", "NYSE", "XETRA"],
        description="Stock exchange where the asset is traded"
    )

    isin: str | None = Field(
        default=None,
        min_length=12,
        max_length=12,
        pattern=r"^[A-Z]{2}[A-Z0-9]{10}$",  # ISIN format: 2 letters + 10 alphanumeric
        examples=["US0378331005"],
        description="International Securities Identification Number"
    )

    name: str | None = Field(
        default=None,
        max_length=255,
        examples=["Apple Inc.", "Microsoft Corporation"],
        description="Full name of the asset"
    )

    asset_class: AssetClass = Field(
        ...,
        description="Type of asset",
        examples=[AssetClass.STOCK, AssetClass.ETF]
    )

    currency: str = Field(
        default="EUR",
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",  # ISO 4217 currency code
        examples=["EUR", "USD", "GBP"],
        description="Currency the asset is priced in (ISO 4217)"
    )

    sector: str | None = Field(
        default=None,
        max_length=100,
        examples=["Technology", "Healthcare", "Financial Services"],
        description="Industry sector"
    )

    region: str | None = Field(
        default=None,
        max_length=100,
        examples=["North America", "Europe", "Asia Pacific"],
        description="Geographic region"
    )

    # =========================================================================
    # FIELD VALIDATORS (Normalization)
    # =========================================================================

    @field_validator('ticker')
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        """Normalize ticker: trim whitespace and uppercase."""
        return v.strip().upper()

    @field_validator('exchange')
    @classmethod
    def normalize_exchange(cls, v: str) -> str:
        """Normalize exchange: trim whitespace and uppercase."""
        return v.strip().upper()

    @field_validator('isin')
    @classmethod
    def normalize_isin(cls, v: str | None) -> str | None:
        """Normalize ISIN: trim whitespace and uppercase."""
        if v is None:
            return None
        return v.strip().upper()

    @field_validator('currency')
    @classmethod
    def normalize_currency(cls, v: str) -> str:
        """Normalize currency: trim whitespace and uppercase."""
        return v.strip().upper()

    @field_validator('name')
    @classmethod
    def normalize_name(cls, v: str | None) -> str | None:
        """Normalize name: trim whitespace."""
        if v is None:
            return None
        return v.strip()

    @field_validator('sector')
    @classmethod
    def normalize_sector(cls, v: str | None) -> str | None:
        """Normalize sector: trim whitespace."""
        if v is None:
            return None
        return v.strip()

    @field_validator('region')
    @classmethod
    def normalize_region(cls, v: str | None) -> str | None:
        """Normalize region: trim whitespace."""
        if v is None:
            return None
        return v.strip()


# =============================================================================
# CREATE SCHEMA
# =============================================================================

class AssetCreate(AssetBase):
    """
    Schema for creating a new asset.

    Inherits all fields and validators from AssetBase.
    """

    is_active: bool = Field(
        default=True,
        description="Whether the asset is currently active/tradeable"
    )


# =============================================================================
# UPDATE SCHEMA
# =============================================================================

class AssetUpdate(BaseModel):
    """
    Schema for updating an existing asset.

    All fields are optional — client only sends fields to update.
    """

    ticker: str | None = Field(default=None, min_length=1, max_length=10)
    exchange: str | None = Field(default=None, min_length=1, max_length=10)
    isin: str | None = Field(default=None, min_length=12, max_length=12, pattern=r"^[A-Z]{2}[A-Z0-9]{10}$")
    name: str | None = Field(default=None, max_length=255)
    asset_class: AssetClass | None = Field(default=None)
    currency: str | None = Field(default=None, min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    sector: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    is_active: bool | None = Field(default=None)

    # =========================================================================
    # FIELD VALIDATORS (Normalization)
    # =========================================================================

    @field_validator('ticker')
    @classmethod
    def normalize_ticker(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip().upper()

    @field_validator('exchange')
    @classmethod
    def normalize_exchange(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip().upper()

    @field_validator('isin')
    @classmethod
    def normalize_isin(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip().upper()

    @field_validator('currency')
    @classmethod
    def normalize_currency(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip().upper()

    @field_validator('name', 'sector', 'region')
    @classmethod
    def normalize_string(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip()


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================

class AssetResponse(AssetBase):
    """
    Schema for API responses.

    Includes database-generated fields.
    """

    id: int = Field(..., description="Unique identifier")
    is_active: bool = Field(..., description="Whether the asset is currently active")
    created_at: datetime = Field(...)
    updated_at: datetime = Field(...)

    model_config = ConfigDict(from_attributes=True)


class AssetListResponse(BaseModel):
    """Response schemas for paginated asset list."""

    items: list[AssetResponse]
    total: int = Field(..., description="Total number of assets matching filters")
    skip: int = Field(..., description="Number of records skipped")
    limit: int = Field(..., description="Maximum number of records returned")
