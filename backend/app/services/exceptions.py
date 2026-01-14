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
    └── MarketDataError
        ├── ProviderUnavailableError
        ├── TickerNotFoundError
        └── RateLimitError
"""


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
        provider: Name of the provider that caused the error (e.g., "yahoo")
        ticker: The ticker symbol being requested (if applicable)
        exchange: The exchange code being requested (if applicable)
    """

    def __init__(
            self,
            message: str,
            provider: str | None = None,
            ticker: str | None = None,
            exchange: str | None = None,
    ) -> None:
        self.provider = provider
        self.ticker = ticker
        self.exchange = exchange
        super().__init__(message)


class ProviderUnavailableError(MarketDataError):
    """
    Raised when a market data provider is unavailable.

    This can occur due to:
    - Network connectivity issues
    - API timeout
    - Provider service outage
    - Authentication failures
    """

    def __init__(self, provider: str, reason: str) -> None:
        message = f"Provider '{provider}' is unavailable: {reason}"
        super().__init__(message, provider=provider)


class TickerNotFoundError(MarketDataError):
    """
    Raised when a provider cannot find the requested ticker.

    This indicates the ticker symbol is not recognized by the provider,
    which may be due to:
    - Invalid ticker symbol
    - Ticker not listed on the specified exchange
    - Delisted security
    """

    def __init__(self, ticker: str, exchange: str, provider: str) -> None:
        message = f"Ticker '{ticker}' on exchange '{exchange}' not found on {provider}"
        super().__init__(message, provider=provider, ticker=ticker, exchange=exchange)


class RateLimitError(MarketDataError):
    """
    Raised when a provider's rate limit has been exceeded.

    The caller should implement appropriate backoff strategies
    or queue requests for later processing.
    """

    def __init__(self, provider: str, retry_after: int | None = None) -> None:
        message = f"Rate limit exceeded for provider '{provider}'"
        if retry_after is not None:
            message += f". Retry after {retry_after} seconds"
        self.retry_after = retry_after
        super().__init__(message, provider=provider)
