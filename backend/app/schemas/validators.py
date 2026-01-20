# backend/app/schemas/validators.py
"""
Reusable validation functions for Pydantic schemas.

This module provides:
- Ticker validation and normalization
- Exchange validation and normalization
- Date range validation
- Currency code validation

These validators ensure consistent input handling across all schemas.
"""

import re
from datetime import date

# =============================================================================
# CONSTANTS
# =============================================================================

# Ticker: 1-20 chars, alphanumeric + dots + carets (for indices like ^SPX)
TICKER_PATTERN = re.compile(r'^[\^]?[A-Z0-9][A-Z0-9.]{0,19}$')
TICKER_MAX_LENGTH = 20

# Exchange: 1-20 chars, alphanumeric only
EXCHANGE_PATTERN = re.compile(r'^[A-Z0-9]{1,20}$')
EXCHANGE_MAX_LENGTH = 20

# Currency: ISO 4217 format (3 uppercase letters)
CURRENCY_PATTERN = re.compile(r'^[A-Z]{3}$')

# Date limits for reasonable financial data
MIN_VALID_DATE = date(1970, 1, 1)  # Unix epoch
MAX_FUTURE_DAYS = 365  # Don't allow dates more than 1 year in future


# =============================================================================
# TICKER VALIDATION
# =============================================================================

def validate_ticker(value: str) -> str:
    """
    Validate and normalize a ticker symbol.

    Valid formats:
    - Standard tickers: AAPL, NVDA, MSFT
    - With dots: BRK.A, BRK.B
    - Indices with caret: ^SPX, ^IXIC
    - Numeric: 600519 (Chinese stocks)

    Args:
        value: Raw ticker input

    Returns:
        Normalized ticker (uppercase, trimmed)

    Raises:
        ValueError: If ticker format is invalid
    """
    if not value:
        raise ValueError("Ticker cannot be empty")

    normalized = value.strip().upper()

    if len(normalized) > TICKER_MAX_LENGTH:
        raise ValueError(f"Ticker cannot exceed {TICKER_MAX_LENGTH} characters")

    if not TICKER_PATTERN.match(normalized):
        raise ValueError(
            f"Invalid ticker format: '{normalized}'. "
            "Ticker must be alphanumeric, may include dots (.) or start with caret (^)"
        )

    return normalized


def normalize_ticker(value: str) -> str:
    """
    Normalize ticker without strict validation.

    Use this for cases where you want normalization but more lenient validation
    (e.g., accepting user input that might have minor issues).

    Args:
        value: Raw ticker input

    Returns:
        Normalized ticker (uppercase, trimmed)
    """
    return value.strip().upper() if value else ""


# =============================================================================
# EXCHANGE VALIDATION
# =============================================================================

def validate_exchange(value: str) -> str:
    """
    Validate and normalize an exchange code.

    Valid formats:
    - Standard: NASDAQ, NYSE, XETRA, LSE
    - Alphanumeric: HKEX, TSE

    Args:
        value: Raw exchange input

    Returns:
        Normalized exchange (uppercase, trimmed)

    Raises:
        ValueError: If exchange format is invalid
    """
    if not value:
        raise ValueError("Exchange cannot be empty")

    normalized = value.strip().upper()

    if len(normalized) > EXCHANGE_MAX_LENGTH:
        raise ValueError(f"Exchange cannot exceed {EXCHANGE_MAX_LENGTH} characters")

    if not EXCHANGE_PATTERN.match(normalized):
        raise ValueError(
            f"Invalid exchange format: '{normalized}'. "
            "Exchange must be alphanumeric only"
        )

    return normalized


def normalize_exchange(value: str) -> str:
    """
    Normalize exchange without strict validation.

    Args:
        value: Raw exchange input

    Returns:
        Normalized exchange (uppercase, trimmed)
    """
    return value.strip().upper() if value else ""


# =============================================================================
# DATE VALIDATION
# =============================================================================

def validate_date_not_future(value: date, field_name: str = "Date") -> date:
    """
    Validate that a date is not in the future.

    Args:
        value: Date to validate
        field_name: Name of field for error message

    Returns:
        The validated date

    Raises:
        ValueError: If date is in the future
    """
    if value > date.today():
        raise ValueError(f"{field_name} cannot be in the future")
    return value


def validate_date_range(
    from_date: date,
    to_date: date,
    allow_same_day: bool = True,
) -> tuple[date, date]:
    """
    Validate a date range.

    Args:
        from_date: Start of range
        to_date: End of range
        allow_same_day: If True, from_date == to_date is valid

    Returns:
        Tuple of (from_date, to_date)

    Raises:
        ValueError: If range is invalid
    """
    if from_date < MIN_VALID_DATE:
        raise ValueError(f"from_date cannot be before {MIN_VALID_DATE}")

    if to_date < MIN_VALID_DATE:
        raise ValueError(f"to_date cannot be before {MIN_VALID_DATE}")

    max_date = date.today()
    if to_date > max_date:
        raise ValueError(f"to_date cannot be in the future")

    if allow_same_day:
        if from_date > to_date:
            raise ValueError("from_date must be before or equal to to_date")
    else:
        if from_date >= to_date:
            raise ValueError("from_date must be before to_date")

    return from_date, to_date


# =============================================================================
# CURRENCY VALIDATION
# =============================================================================

def validate_currency(value: str) -> str:
    """
    Validate and normalize a currency code.

    Args:
        value: Raw currency input (e.g., "usd", "EUR")

    Returns:
        Normalized currency (uppercase, trimmed)

    Raises:
        ValueError: If currency format is invalid
    """
    if not value:
        raise ValueError("Currency cannot be empty")

    normalized = value.strip().upper()

    if not CURRENCY_PATTERN.match(normalized):
        raise ValueError(
            f"Invalid currency format: '{normalized}'. "
            "Currency must be a 3-letter ISO code (e.g., USD, EUR)"
        )

    return normalized


def normalize_currency(value: str) -> str:
    """
    Normalize currency without strict validation.

    Args:
        value: Raw currency input

    Returns:
        Normalized currency (uppercase, trimmed)
    """
    return value.strip().upper() if value else ""
