# backend/tests/schemas/test_transactions.py
"""
Tests for transaction schemas.

This module tests:
- Field validation (required fields, type constraints)
- Normalizers (currency uppercase, whitespace trimming)
- Date validation (future dates rejected)
- Decimal precision handling
"""

import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from pydantic import ValidationError

from app.models import TransactionType
from app.schemas.transactions import (
    TransactionCreate,
    TransactionUpdate,
    TransactionBase,
)


# =============================================================================
# TRANSACTION CREATE TESTS
# =============================================================================

class TestTransactionCreate:
    """Tests for TransactionCreate schema."""

    def test_valid_transaction_create(self):
        """Should accept valid transaction data."""
        data = TransactionCreate(
            portfolio_id=1,
            ticker="NVDA",
            exchange="NASDAQ",
            transaction_type=TransactionType.BUY,
            date=datetime(2024, 1, 15, 14, 30, tzinfo=timezone.utc),
            quantity=Decimal("10"),
            price_per_share=Decimal("500.50"),
            currency="USD",
            fee=Decimal("9.99"),
            fee_currency="USD",
            exchange_rate=Decimal("1"),
        )

        assert data.ticker == "NVDA"
        assert data.quantity == Decimal("10")

    def test_required_fields(self):
        """Should require portfolio_id, ticker, exchange, transaction_type, date, quantity, price_per_share."""
        with pytest.raises(ValidationError) as exc_info:
            TransactionCreate()

        errors = exc_info.value.errors()
        required_fields = {"portfolio_id", "ticker", "exchange", "transaction_type", "date", "quantity", "price_per_share"}
        error_fields = {e["loc"][0] for e in errors}

        assert required_fields.issubset(error_fields)

    def test_ticker_normalization(self):
        """Should normalize ticker to uppercase and trim whitespace."""
        data = TransactionCreate(
            portfolio_id=1,
            ticker="  nvda  ",
            exchange="NASDAQ",
            transaction_type=TransactionType.BUY,
            date=datetime(2024, 1, 15, tzinfo=timezone.utc),
            quantity=Decimal("10"),
            price_per_share=Decimal("100"),
        )

        assert data.ticker == "NVDA"

    def test_exchange_normalization(self):
        """Should normalize exchange to uppercase and trim whitespace."""
        data = TransactionCreate(
            portfolio_id=1,
            ticker="NVDA",
            exchange="  nasdaq  ",
            transaction_type=TransactionType.BUY,
            date=datetime(2024, 1, 15, tzinfo=timezone.utc),
            quantity=Decimal("10"),
            price_per_share=Decimal("100"),
        )

        assert data.exchange == "NASDAQ"

    def test_currency_must_be_uppercase(self):
        """Should reject lowercase currency (pattern validation)."""
        # Note: Pattern validation runs before field_validator normalization
        with pytest.raises(ValidationError):
            TransactionCreate(
                portfolio_id=1,
                ticker="NVDA",
                exchange="NASDAQ",
                transaction_type=TransactionType.BUY,
                date=datetime(2024, 1, 15, tzinfo=timezone.utc),
                quantity=Decimal("10"),
                price_per_share=Decimal("100"),
                currency="usd",  # Lowercase - fails pattern
            )

    def test_fee_currency_must_be_uppercase(self):
        """Should reject lowercase fee_currency (pattern validation)."""
        with pytest.raises(ValidationError):
            TransactionCreate(
                portfolio_id=1,
                ticker="NVDA",
                exchange="NASDAQ",
                transaction_type=TransactionType.BUY,
                date=datetime(2024, 1, 15, tzinfo=timezone.utc),
                quantity=Decimal("10"),
                price_per_share=Decimal("100"),
                fee_currency="eur",  # Lowercase - fails pattern
            )

    def test_fee_currency_none_allowed(self):
        """Should allow None for fee_currency."""
        data = TransactionCreate(
            portfolio_id=1,
            ticker="NVDA",
            exchange="NASDAQ",
            transaction_type=TransactionType.BUY,
            date=datetime(2024, 1, 15, tzinfo=timezone.utc),
            quantity=Decimal("10"),
            price_per_share=Decimal("100"),
            fee_currency=None,
        )

        assert data.fee_currency is None

    def test_portfolio_id_must_be_positive(self):
        """Should reject non-positive portfolio_id."""
        with pytest.raises(ValidationError) as exc_info:
            TransactionCreate(
                portfolio_id=0,
                ticker="NVDA",
                exchange="NASDAQ",
                transaction_type=TransactionType.BUY,
                date=datetime(2024, 1, 15, tzinfo=timezone.utc),
                quantity=Decimal("10"),
                price_per_share=Decimal("100"),
            )

        assert any("portfolio_id" in str(e["loc"]) for e in exc_info.value.errors())

    def test_ticker_max_length(self):
        """Should reject tickers longer than 10 characters."""
        with pytest.raises(ValidationError):
            TransactionCreate(
                portfolio_id=1,
                ticker="TOOLONGTICKER",
                exchange="NASDAQ",
                transaction_type=TransactionType.BUY,
                date=datetime(2024, 1, 15, tzinfo=timezone.utc),
                quantity=Decimal("10"),
                price_per_share=Decimal("100"),
            )

    def test_currency_must_be_3_chars(self):
        """Should reject currency codes not exactly 3 characters."""
        with pytest.raises(ValidationError):
            TransactionCreate(
                portfolio_id=1,
                ticker="NVDA",
                exchange="NASDAQ",
                transaction_type=TransactionType.BUY,
                date=datetime(2024, 1, 15, tzinfo=timezone.utc),
                quantity=Decimal("10"),
                price_per_share=Decimal("100"),
                currency="US",  # Too short
            )


# =============================================================================
# DATE VALIDATION TESTS
# =============================================================================

class TestDateValidation:
    """Tests for date validation rules."""

    def test_past_date_accepted(self):
        """Should accept dates in the past."""
        past_date = datetime.now(timezone.utc) - timedelta(days=30)
        data = TransactionCreate(
            portfolio_id=1,
            ticker="NVDA",
            exchange="NASDAQ",
            transaction_type=TransactionType.BUY,
            date=past_date,
            quantity=Decimal("10"),
            price_per_share=Decimal("100"),
        )

        assert data.date <= datetime.now(timezone.utc)

    def test_future_date_rejected(self):
        """Should reject dates in the future."""
        future_date = datetime.now(timezone.utc) + timedelta(days=1)

        with pytest.raises(ValidationError) as exc_info:
            TransactionCreate(
                portfolio_id=1,
                ticker="NVDA",
                exchange="NASDAQ",
                transaction_type=TransactionType.BUY,
                date=future_date,
                quantity=Decimal("10"),
                price_per_share=Decimal("100"),
            )

        # Check that the error is about the date being in the future
        assert any("future" in str(e).lower() for e in exc_info.value.errors())

    def test_naive_datetime_gets_utc_timezone(self):
        """Should add UTC timezone to naive datetime."""
        naive_date = datetime(2024, 1, 15, 14, 30)

        data = TransactionCreate(
            portfolio_id=1,
            ticker="NVDA",
            exchange="NASDAQ",
            transaction_type=TransactionType.BUY,
            date=naive_date,
            quantity=Decimal("10"),
            price_per_share=Decimal("100"),
        )

        assert data.date.tzinfo == timezone.utc


# =============================================================================
# NUMERIC VALIDATION TESTS
# =============================================================================

class TestNumericValidation:
    """Tests for quantity, price, and fee validation."""

    def test_quantity_must_be_positive(self):
        """Should reject zero or negative quantity."""
        with pytest.raises(ValidationError):
            TransactionCreate(
                portfolio_id=1,
                ticker="NVDA",
                exchange="NASDAQ",
                transaction_type=TransactionType.BUY,
                date=datetime(2024, 1, 15, tzinfo=timezone.utc),
                quantity=Decimal("0"),
                price_per_share=Decimal("100"),
            )

    def test_price_must_be_positive(self):
        """Should reject zero or negative price."""
        with pytest.raises(ValidationError):
            TransactionCreate(
                portfolio_id=1,
                ticker="NVDA",
                exchange="NASDAQ",
                transaction_type=TransactionType.BUY,
                date=datetime(2024, 1, 15, tzinfo=timezone.utc),
                quantity=Decimal("10"),
                price_per_share=Decimal("-50"),
            )

    def test_fee_can_be_zero(self):
        """Should accept zero fee."""
        data = TransactionCreate(
            portfolio_id=1,
            ticker="NVDA",
            exchange="NASDAQ",
            transaction_type=TransactionType.BUY,
            date=datetime(2024, 1, 15, tzinfo=timezone.utc),
            quantity=Decimal("10"),
            price_per_share=Decimal("100"),
            fee=Decimal("0"),
        )

        assert data.fee == Decimal("0")

    def test_fee_cannot_be_negative(self):
        """Should reject negative fee."""
        with pytest.raises(ValidationError):
            TransactionCreate(
                portfolio_id=1,
                ticker="NVDA",
                exchange="NASDAQ",
                transaction_type=TransactionType.BUY,
                date=datetime(2024, 1, 15, tzinfo=timezone.utc),
                quantity=Decimal("10"),
                price_per_share=Decimal("100"),
                fee=Decimal("-5"),
            )

    def test_exchange_rate_must_be_positive(self):
        """Should reject zero or negative exchange rate."""
        with pytest.raises(ValidationError):
            TransactionCreate(
                portfolio_id=1,
                ticker="NVDA",
                exchange="NASDAQ",
                transaction_type=TransactionType.BUY,
                date=datetime(2024, 1, 15, tzinfo=timezone.utc),
                quantity=Decimal("10"),
                price_per_share=Decimal("100"),
                exchange_rate=Decimal("0"),
            )

    def test_decimal_precision_preserved(self):
        """Should preserve high decimal precision (8 decimal places)."""
        data = TransactionCreate(
            portfolio_id=1,
            ticker="BTC",
            exchange="CRYPTO",
            transaction_type=TransactionType.BUY,
            date=datetime(2024, 1, 15, tzinfo=timezone.utc),
            quantity=Decimal("0.00001234"),
            price_per_share=Decimal("45000.12345678"),
        )

        assert data.quantity == Decimal("0.00001234")
        assert data.price_per_share == Decimal("45000.12345678")


# =============================================================================
# TRANSACTION UPDATE TESTS
# =============================================================================

class TestTransactionUpdate:
    """Tests for TransactionUpdate schema."""

    def test_all_fields_optional(self):
        """Should accept empty update (all fields optional)."""
        data = TransactionUpdate()

        assert data.date is None
        assert data.quantity is None
        assert data.price_per_share is None

    def test_partial_update(self):
        """Should accept partial updates."""
        data = TransactionUpdate(
            quantity=Decimal("20"),
            fee=Decimal("5.99"),
        )

        assert data.quantity == Decimal("20")
        assert data.fee == Decimal("5.99")
        assert data.price_per_share is None

    def test_currency_must_be_uppercase_in_update(self):
        """Should reject lowercase currency in update (pattern validation)."""
        with pytest.raises(ValidationError):
            TransactionUpdate(currency="eur")  # Lowercase - fails pattern

    def test_future_date_rejected_in_update(self):
        """Should reject future dates in update."""
        future_date = datetime.now(timezone.utc) + timedelta(days=1)

        with pytest.raises(ValidationError):
            TransactionUpdate(date=future_date)

    def test_update_validation_respects_constraints(self):
        """Should validate constraints on provided fields."""
        with pytest.raises(ValidationError):
            TransactionUpdate(quantity=Decimal("-10"))  # Must be positive


# =============================================================================
# TRANSACTION TYPE TESTS
# =============================================================================

class TestTransactionType:
    """Tests for transaction_type field."""

    def test_buy_type_accepted(self):
        """Should accept BUY transaction type."""
        data = TransactionCreate(
            portfolio_id=1,
            ticker="NVDA",
            exchange="NASDAQ",
            transaction_type=TransactionType.BUY,
            date=datetime(2024, 1, 15, tzinfo=timezone.utc),
            quantity=Decimal("10"),
            price_per_share=Decimal("100"),
        )

        assert data.transaction_type == TransactionType.BUY

    def test_sell_type_accepted(self):
        """Should accept SELL transaction type."""
        data = TransactionCreate(
            portfolio_id=1,
            ticker="NVDA",
            exchange="NASDAQ",
            transaction_type=TransactionType.SELL,
            date=datetime(2024, 1, 15, tzinfo=timezone.utc),
            quantity=Decimal("10"),
            price_per_share=Decimal("100"),
        )

        assert data.transaction_type == TransactionType.SELL

    def test_invalid_type_rejected(self):
        """Should reject invalid transaction types."""
        with pytest.raises(ValidationError):
            TransactionCreate(
                portfolio_id=1,
                ticker="NVDA",
                exchange="NASDAQ",
                transaction_type="INVALID",
                date=datetime(2024, 1, 15, tzinfo=timezone.utc),
                quantity=Decimal("10"),
                price_per_share=Decimal("100"),
            )
