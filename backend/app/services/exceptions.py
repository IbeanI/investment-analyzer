# backend/app/services/exceptions.py
"""
Service layer exceptions.

These exceptions represent domain-specific errors and contain NO HTTP knowledge.
The router layer is responsible for mapping these to appropriate HTTP responses.

Exception Hierarchy:
    ServiceError (base)
    ├── ValidationError
    │   └── InvalidIntervalError
    ├── NotFoundError
    │   └── PortfolioNotFoundError
    ├── AssetResolutionError
    │   ├── AssetNotFoundError
    │   └── AssetDeactivatedError
    ├── MarketDataError
    │   ├── ProviderUnavailableError
    │   ├── TickerNotFoundError
    │   └── RateLimitError
    ├── FXRateError
    │   ├── FXRateNotFoundError
    │   ├── FXProviderError
    │   └── FXConversionError
    └── AnalyticsError
        └── BenchmarkNotSyncedError

    CircuitBreakerOpen (from circuit_breaker module)
        - Raised when circuit breaker is open and blocking requests
"""

from datetime import date


class ServiceError(Exception):
    """
    Base exception for all service layer errors.

    Attributes:
        message: Human-readable error description
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


# =============================================================================
# VALIDATION ERRORS
# =============================================================================


class ValidationError(ServiceError):
    """
    Raised when input validation fails.

    This is for programmatic validation errors (invalid parameters, missing
    required fields, etc.), NOT for user input validation which is handled
    by Pydantic.

    Attributes:
        field: The field that failed validation (optional)
    """

    def __init__(self, message: str, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)


class InvalidIntervalError(ValidationError):
    """
    Raised when an invalid interval is specified for time series.

    Valid intervals are: daily, weekly, monthly
    """

    def __init__(self, interval: str) -> None:
        self.interval = interval
        super().__init__(
            f"Invalid interval: '{interval}'. Valid options: daily, weekly, monthly",
            field="interval"
        )


# =============================================================================
# NOT FOUND ERRORS
# =============================================================================


class NotFoundError(ServiceError):
    """
    Base exception for resource not found errors.

    Attributes:
        resource_type: Type of resource (e.g., "Portfolio", "Asset")
        resource_id: Identifier of the resource
    """

    def __init__(
            self,
            message: str,
            resource_type: str | None = None,
            resource_id: int | str | None = None,
    ) -> None:
        self.resource_type = resource_type
        self.resource_id = resource_id
        super().__init__(message)


class PortfolioNotFoundError(NotFoundError):
    """
    Raised when a portfolio cannot be found.

    Attributes:
        portfolio_id: ID of the portfolio that was not found
    """

    def __init__(self, portfolio_id: int) -> None:
        self.portfolio_id = portfolio_id
        super().__init__(
            f"Portfolio {portfolio_id} not found",
            resource_type="Portfolio",
            resource_id=portfolio_id,
        )


# =============================================================================
# ASSET RESOLUTION ERRORS
# =============================================================================


class AssetResolutionError(ServiceError):
    """
    Base exception for asset resolution failures.

    Attributes:
        ticker: The ticker symbol that caused the error
        exchange: The exchange code that caused the error
    """

    def __init__(
            self,
            message: str,
            ticker: str | None = None,
            exchange: str | None = None,
    ) -> None:
        self.ticker = ticker
        self.exchange = exchange
        super().__init__(message)


class AssetNotFoundError(AssetResolutionError):
    """
    Raised when an asset cannot be found in the database or via any provider.

    This indicates the ticker+exchange combination is not recognized.
    """

    def __init__(self, ticker: str, exchange: str) -> None:
        message = f"Asset '{ticker}' on exchange '{exchange}' not found"
        super().__init__(message, ticker=ticker, exchange=exchange)


class AssetDeactivatedError(AssetResolutionError):
    """
    Raised when an asset exists but has been deactivated (is_active=False).

    Deactivated assets cannot be used in new transactions to maintain
    data integrity, but historical transactions referencing them remain valid.
    """

    def __init__(self, ticker: str, exchange: str) -> None:
        message = f"Asset '{ticker}' on exchange '{exchange}' is deactivated"
        super().__init__(message, ticker=ticker, exchange=exchange)


# =============================================================================
# MARKET DATA PROVIDER ERRORS
# =============================================================================


class MarketDataError(ServiceError):
    """
    Base exception for market data provider failures.

    Attributes:
        provider: Name of the provider that failed
    """

    def __init__(self, message: str, provider: str | None = None) -> None:
        self.provider = provider
        super().__init__(message)


class ProviderUnavailableError(MarketDataError):
    """
    Raised when a market data provider is temporarily unavailable.

    Examples:
    - Network timeout
    - Server errors (500, 502, 503)
    - API maintenance

    This is a retryable error.
    """

    def __init__(self, provider: str, reason: str) -> None:
        message = f"Provider '{provider}' is unavailable: {reason}"
        super().__init__(message, provider=provider)
        self.reason = reason


class TickerNotFoundError(MarketDataError):
    """
    Raised when a ticker symbol is not found by the provider.

    This indicates:
    - The ticker symbol is invalid
    - The ticker is not available on the specified exchange
    - The provider doesn't recognize the symbol

    This is NOT a retryable error.
    """

    def __init__(self, ticker: str, exchange: str, provider: str) -> None:
        message = f"Ticker '{ticker}' on exchange '{exchange}' not found by {provider}"
        super().__init__(message, provider=provider)
        self.ticker = ticker
        self.exchange = exchange


class RateLimitError(MarketDataError):
    """
    Raised when the provider's rate limit has been exceeded.

    This is a retryable error (with backoff).

    Attributes:
        retry_after: Seconds to wait before retrying (if provided by API)
    """

    def __init__(self, provider: str, retry_after: int | None = None) -> None:
        message = f"Rate limit exceeded for provider '{provider}'"
        if retry_after:
            message += f" (retry after {retry_after}s)"
        super().__init__(message, provider=provider)
        self.retry_after = retry_after


# =============================================================================
# FX RATE ERRORS (Phase 3)
# =============================================================================


class FXRateError(ServiceError):
    """
    Base exception for FX rate errors.

    Attributes:
        base_currency: The base currency code
        quote_currency: The quote currency code
    """

    def __init__(
            self,
            message: str,
            base_currency: str | None = None,
            quote_currency: str | None = None,
    ) -> None:
        self.base_currency = base_currency
        self.quote_currency = quote_currency
        super().__init__(message)


class FXRateNotFoundError(FXRateError):
    """
    Raised when no FX rate is available for the requested date/pair.

    This can happen when:
    - The date is before available historical data
    - The currency pair is not supported
    - Data hasn't been synced for the date range

    Attributes:
        date: The date for which rate was requested
    """

    def __init__(
            self,
            base_currency: str,
            quote_currency: str,
            rate_date: date,
            message: str | None = None
    ) -> None:
        self.date = rate_date
        msg = message or f"No FX rate found for {base_currency}/{quote_currency} on {rate_date}"
        super().__init__(msg, base_currency=base_currency, quote_currency=quote_currency)


class FXProviderError(FXRateError):
    """
    Raised when the FX data provider fails.

    This is typically a retryable error caused by:
    - Network issues
    - Provider API errors
    - Rate limiting

    Attributes:
        provider: Name of the FX data provider
        reason: Specific reason for failure
    """

    def __init__(self, provider: str, reason: str) -> None:
        self.provider = provider
        self.reason = reason
        super().__init__(f"FX provider '{provider}' error: {reason}")


class FXConversionError(FXRateError):
    """
    Raised when FX rate conversion fails due to invalid parameters.

    Examples:
    - Attempting to invert a zero rate
    - Invalid rate value (negative, None)

    Attributes:
        reason: Specific reason for conversion failure
    """

    def __init__(
            self,
            reason: str,
            base_currency: str | None = None,
            quote_currency: str | None = None,
    ) -> None:
        self.reason = reason
        super().__init__(
            f"FX conversion error: {reason}",
            base_currency=base_currency,
            quote_currency=quote_currency,
        )


# =============================================================================
# ANALYTICS ERRORS
# =============================================================================


class AnalyticsError(ServiceError):
    """
    Base exception for analytics calculation errors.
    """
    pass


class BenchmarkNotSyncedError(AnalyticsError):
    """
    Raised when benchmark data is required but not available.

    This typically means:
    - Benchmark asset not in database
    - Benchmark has no price data for requested period
    - User needs to sync benchmark data first

    Attributes:
        symbol: The benchmark symbol that's not synced
    """

    def __init__(self, symbol: str, message: str | None = None) -> None:
        self.symbol = symbol
        msg = message or f"Benchmark '{symbol}' is not synced. Please sync benchmark data first."
        super().__init__(msg)


# =============================================================================
# CIRCUIT BREAKER (re-exported for convenience)
# =============================================================================

# Re-export CircuitBreakerOpen for easier importing alongside other exceptions
from app.services.circuit_breaker import CircuitBreakerOpen

__all__ = [
    # Base
    "ServiceError",
    # Validation
    "ValidationError",
    "InvalidIntervalError",
    # Not Found
    "NotFoundError",
    "PortfolioNotFoundError",
    # Asset Resolution
    "AssetResolutionError",
    "AssetNotFoundError",
    "AssetDeactivatedError",
    # Market Data
    "MarketDataError",
    "ProviderUnavailableError",
    "TickerNotFoundError",
    "RateLimitError",
    # FX Rate
    "FXRateError",
    "FXRateNotFoundError",
    "FXProviderError",
    "FXConversionError",
    # Analytics
    "AnalyticsError",
    "BenchmarkNotSyncedError",
    # Circuit Breaker
    "CircuitBreakerOpen",
]
