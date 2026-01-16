# backend/app/services/exceptions.py
"""
Service layer exceptions.

These exceptions represent domain-specific errors and contain NO HTTP knowledge.
The router layer is responsible for mapping these to appropriate HTTP responses.

Exception Hierarchy:
    ServiceError (base)
    ├── AssetResolutionError
    │   ├── AssetNotFoundError
    │   └── AssetDeactivatedError
    ├── MarketDataError
    │   ├── ProviderUnavailableError
    │   ├── TickerNotFoundError
    │   └── RateLimitError
    └── FXRateError (NEW - Phase 3)
        ├── FXRateNotFoundError
        └── FXProviderError
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
