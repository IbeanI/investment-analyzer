# backend/app/schemas/exchange_rates.py
"""
Pydantic schemas for Exchange Rate operations.

These schemas handle:
- FX rate responses
- FX sync requests
"""

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================

class ExchangeRateResponse(BaseModel):
    """Schema for a single exchange rate record."""

    id: int
    base_currency: str = Field(..., description="Base currency (e.g., USD)")
    quote_currency: str = Field(..., description="Quote currency (e.g., EUR)")
    date: dt.date = Field(..., description="Date of the rate")
    rate: Decimal = Field(..., description="Exchange rate (1 base = X quote)")
    provider: str = Field(..., description="Data provider (e.g., yahoo)")

    model_config = ConfigDict(from_attributes=True)


class ExchangeRateRangeResponse(BaseModel):
    """Schema for exchange rates over a date range."""

    base_currency: str
    quote_currency: str
    from_date: dt.date
    to_date: dt.date
    rates: list[ExchangeRateResponse]
    total: int = Field(..., description="Total number of rates in range")


# =============================================================================
# REQUEST SCHEMAS
# =============================================================================

class ExchangeRateLookup(BaseModel):
    """Schema for looking up a specific exchange rate."""

    base_currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="Base currency code (ISO 4217)"
    )
    quote_currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="Quote currency code (ISO 4217)"
    )
    date: dt.date = Field(..., description="Date for the rate lookup")

    @field_validator('base_currency', 'quote_currency')
    @classmethod
    def normalize_currency(cls, v: str) -> str:
        """Normalize currency: uppercase and strip."""
        return v.strip().upper()
