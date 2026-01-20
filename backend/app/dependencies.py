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
    )

    @router.post("/")
    def create_transaction(
        service: AssetResolutionService = Depends(get_asset_resolution_service),
    ):
        ...
"""

import logging
from functools import lru_cache

from app.services.asset_resolution import AssetResolutionService
from app.services.analytics.service import AnalyticsService
from app.services.market_data.sync_service import MarketDataSyncService
from app.services.market_data.yahoo import YahooFinanceProvider
from app.services.valuation.service import ValuationService
from app.services.fx_rate_service import FXRateService

logger = logging.getLogger(__name__)


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
    logger.info("Cleared all service singleton caches")
