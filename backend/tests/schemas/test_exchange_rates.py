# backend/tests/schemas/test_exchange_rates.py
"""
Tests for exchange rate schemas.

This module tests:
- Currency code validation and normalization
- Date handling
- Response schema structure
"""

import pytest
import datetime as dt
from decimal import Decimal

from pydantic import ValidationError

from app.schemas.exchange_rates import (
    ExchangeRateLookup,
    ExchangeRateResponse,
    ExchangeRateRangeResponse,
)


# =============================================================================
# EXCHANGE RATE LOOKUP TESTS
# =============================================================================

class TestExchangeRateLookup:
    """Tests for ExchangeRateLookup schema."""

    def test_valid_lookup(self):
        """Should accept valid currency codes and date."""
        data = ExchangeRateLookup(
            base_currency="USD",
            quote_currency="EUR",
            date=dt.date(2024, 1, 15),
        )

        assert data.base_currency == "USD"
        assert data.quote_currency == "EUR"
        assert data.date == dt.date(2024, 1, 15)

    def test_currency_must_be_uppercase(self):
        """Should reject lowercase currency codes (pattern validation)."""
        # Note: Pattern validation runs before field_validator normalization
        # So lowercase currencies are rejected before normalization can occur
        with pytest.raises(ValidationError):
            ExchangeRateLookup(
                base_currency="usd",  # Lowercase - fails pattern
                quote_currency="EUR",
                date=dt.date(2024, 1, 15),
            )

    def test_currency_must_be_3_chars(self):
        """Should reject currency codes not exactly 3 characters."""
        with pytest.raises(ValidationError):
            ExchangeRateLookup(
                base_currency="US",  # Too short
                quote_currency="EUR",
                date=dt.date(2024, 1, 15),
            )

        with pytest.raises(ValidationError):
            ExchangeRateLookup(
                base_currency="USD",
                quote_currency="EURO",  # Too long
                date=dt.date(2024, 1, 15),
            )

    def test_currency_must_be_letters(self):
        """Should reject currency codes with non-letter characters."""
        with pytest.raises(ValidationError):
            ExchangeRateLookup(
                base_currency="US1",  # Contains digit
                quote_currency="EUR",
                date=dt.date(2024, 1, 15),
            )

    def test_required_fields(self):
        """Should require all fields."""
        with pytest.raises(ValidationError):
            ExchangeRateLookup()


# =============================================================================
# EXCHANGE RATE RESPONSE TESTS
# =============================================================================

class TestExchangeRateResponse:
    """Tests for ExchangeRateResponse schema."""

    def test_valid_response(self):
        """Should accept valid response data."""
        data = ExchangeRateResponse(
            id=1,
            base_currency="USD",
            quote_currency="EUR",
            date=dt.date(2024, 1, 15),
            rate=Decimal("0.92"),
            provider="yahoo",
        )

        assert data.id == 1
        assert data.rate == Decimal("0.92")

    def test_from_attributes_config(self):
        """Should have from_attributes=True for ORM compatibility."""
        assert ExchangeRateResponse.model_config.get("from_attributes") is True


# =============================================================================
# EXCHANGE RATE RANGE RESPONSE TESTS
# =============================================================================

class TestExchangeRateRangeResponse:
    """Tests for ExchangeRateRangeResponse schema."""

    def test_valid_range_response(self):
        """Should accept valid range response data."""
        rate1 = ExchangeRateResponse(
            id=1,
            base_currency="USD",
            quote_currency="EUR",
            date=dt.date(2024, 1, 15),
            rate=Decimal("0.92"),
            provider="yahoo",
        )
        rate2 = ExchangeRateResponse(
            id=2,
            base_currency="USD",
            quote_currency="EUR",
            date=dt.date(2024, 1, 16),
            rate=Decimal("0.93"),
            provider="yahoo",
        )

        data = ExchangeRateRangeResponse(
            base_currency="USD",
            quote_currency="EUR",
            from_date=dt.date(2024, 1, 15),
            to_date=dt.date(2024, 1, 16),
            rates=[rate1, rate2],
            total=2,
        )

        assert data.total == 2
        assert len(data.rates) == 2

    def test_empty_rates_list(self):
        """Should accept empty rates list."""
        data = ExchangeRateRangeResponse(
            base_currency="USD",
            quote_currency="EUR",
            from_date=dt.date(2024, 1, 15),
            to_date=dt.date(2024, 1, 16),
            rates=[],
            total=0,
        )

        assert data.total == 0
        assert len(data.rates) == 0
