# backend/app/dependencies.py
"""
Dependency injection module for FastAPI services.

This module provides singleton service instances that are shared across
all requests. This is more efficient than creating new instances per request
and ensures shared state (like caches) works correctly.

Services are lazily initialized on first use to avoid import-time side effects.

Usage in routers:
    from app.dependencies import (
        get_asset_resolution_service,
        get_analytics_service,
        get_sync_service,
        get_current_user,
        get_portfolio_with_owner_check,
    )

    @router.post("/")
    def create_transaction(
        service: AssetResolutionService = Depends(get_asset_resolution_service),
        current_user: User = Depends(get_current_user),
    ):
        ...
"""

import logging
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Portfolio
from app.services.asset_resolution import AssetResolutionService
from app.services.analytics.service import AnalyticsService
from app.services.market_data.sync_service import MarketDataSyncService
from app.services.market_data.yahoo import YahooFinanceProvider
from app.services.valuation.service import ValuationService
from app.services.fx_rate_service import FXRateService
from app.services.auth import AuthService, EmailService
from app.services.auth.jwt_handler import JWTHandler
from app.services.exceptions import (
    TokenExpiredError,
    InvalidCredentialsError,
    PermissionDeniedError,
)

logger = logging.getLogger(__name__)

# HTTP Bearer scheme for JWT authentication
_bearer_scheme = HTTPBearer(auto_error=False)


# =============================================================================
# SINGLETON SERVICE INSTANCES
# =============================================================================
# Using @lru_cache ensures the function returns the same instance on every call
# This is a clean pattern for lazy singleton initialization in Python
#
# Order matters: define dependencies before dependents
# 1. get_market_data_provider (no deps)
# 2. get_fx_rate_service (depends on provider)
# 3. get_asset_resolution_service (depends on provider)
# 4. get_valuation_service (depends on fx_service)
# 5. get_analytics_service (depends on valuation_service)
# 6. get_sync_service (depends on provider, fx_service)


@lru_cache(maxsize=1)
def get_market_data_provider() -> YahooFinanceProvider:
    """
    Get the singleton market data provider instance.

    Shares the provider (and its circuit breaker) across all services,
    ensuring rate limits are respected globally.
    """
    logger.debug("Initializing singleton YahooFinanceProvider")
    return YahooFinanceProvider()


@lru_cache(maxsize=1)
def get_fx_rate_service() -> FXRateService:
    """
    Get the singleton FXRateService instance.

    Shares the FX rate provider and cache across all requests.
    """
    logger.debug("Initializing singleton FXRateService")
    return FXRateService(provider=get_market_data_provider())


@lru_cache(maxsize=1)
def get_asset_resolution_service() -> AssetResolutionService:
    """
    Get the singleton AssetResolutionService instance.

    Shares the LRU cache for resolved assets across all requests,
    reducing database lookups and external API calls.
    Uses the shared provider to ensure circuit breaker state is consistent.
    """
    logger.debug("Initializing singleton AssetResolutionService")
    return AssetResolutionService(provider=get_market_data_provider())


@lru_cache(maxsize=1)
def get_valuation_service() -> ValuationService:
    """
    Get the singleton ValuationService instance.

    Used by routers and other services for portfolio valuation.
    Uses the shared FX service to ensure circuit breaker state is consistent.
    """
    logger.debug("Initializing singleton ValuationService")
    return ValuationService(fx_service=get_fx_rate_service())


@lru_cache(maxsize=1)
def get_analytics_service() -> AnalyticsService:
    """
    Get the singleton AnalyticsService instance.

    Shares a single cache across all requests, ensuring cache invalidation
    works correctly and avoiding redundant computations.
    """
    logger.debug("Initializing singleton AnalyticsService")
    return AnalyticsService(valuation_service=get_valuation_service())


@lru_cache(maxsize=1)
def get_sync_service() -> MarketDataSyncService:
    """
    Get the singleton MarketDataSyncService instance.

    Shares the market data provider (and its circuit breaker) across all
    requests, preventing excessive API calls and ensuring rate limits
    are respected globally.
    """
    logger.debug("Initializing singleton MarketDataSyncService")
    return MarketDataSyncService(
        provider=get_market_data_provider(),
        fx_service=get_fx_rate_service(),
    )


# =============================================================================
# AUTHENTICATION SERVICES
# =============================================================================


@lru_cache(maxsize=1)
def get_email_service() -> EmailService:
    """
    Get the singleton EmailService instance.

    Used for sending verification and password reset emails.
    """
    logger.debug("Initializing singleton EmailService")
    return EmailService()


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    """
    Get the singleton AuthService instance.

    Handles user registration, authentication, and token management.
    """
    logger.debug("Initializing singleton AuthService")
    return AuthService(email_service=get_email_service())


# =============================================================================
# AUTHENTICATION DEPENDENCIES
# =============================================================================


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """
    Dependency that extracts and validates the current user from JWT.

    Usage:
        @router.get("/protected")
        def protected_endpoint(current_user: User = Depends(get_current_user)):
            return {"user_id": current_user.id}

    Raises:
        HTTPException 401: If no token provided or token is invalid/expired
        HTTPException 401: If user not found or inactive
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = JWTHandler.validate_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidCredentialsError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_optional_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User | None:
    """
    Optional version of get_current_user.

    Returns None if no token provided, but still validates token if present.
    Useful for endpoints that work differently for authenticated vs anonymous users.
    """
    if credentials is None:
        return None

    try:
        return get_current_user(credentials, db)
    except HTTPException:
        return None


def get_portfolio_with_owner_check(
    portfolio_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Portfolio:
    """
    Dependency that fetches a portfolio and verifies ownership.

    Usage:
        @router.get("/{portfolio_id}")
        def get_portfolio(
            portfolio: Portfolio = Depends(get_portfolio_with_owner_check),
        ):
            return portfolio

    Raises:
        HTTPException 404: If portfolio not found
        HTTPException 403: If user doesn't own the portfolio
    """
    portfolio = db.get(Portfolio, portfolio_id)

    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio {portfolio_id} not found",
        )

    if portfolio.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this portfolio",
        )

    return portfolio


# =============================================================================
# CACHE MANAGEMENT
# =============================================================================

def clear_service_caches() -> None:
    """
    Clear all service caches.

    Useful for testing or when you need to reset state.
    """
    # Clear the LRU caches (this will cause new instances to be created on next call)
    get_market_data_provider.cache_clear()
    get_fx_rate_service.cache_clear()
    get_asset_resolution_service.cache_clear()
    get_valuation_service.cache_clear()
    get_analytics_service.cache_clear()
    get_sync_service.cache_clear()
    get_email_service.cache_clear()
    get_auth_service.cache_clear()
    logger.info("Cleared all service singleton caches")
