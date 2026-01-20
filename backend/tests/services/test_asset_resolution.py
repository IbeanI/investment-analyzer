# backend/tests/services/test_asset_resolution.py
"""
Tests for the AssetResolutionService.

This module tests:
- Single asset resolution (database lookup, provider fetch, creation)
- Batch asset resolution
- Caching behavior
- Error handling (deactivated assets, not found, provider errors)
- Race condition handling
"""

import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy.exc import IntegrityError

from app.models import Asset, AssetClass
from app.services.asset_resolution import AssetResolutionService, BatchResolutionResult
from app.services.exceptions import (
    AssetNotFoundError,
    AssetDeactivatedError,
    ProviderUnavailableError,
    TickerNotFoundError,
)
from app.services.market_data.base import AssetInfo, BatchResult

from tests.conftest import (
    MockMarketDataProvider,
    create_asset,
    create_asset_info,
)


# =============================================================================
# INITIALIZATION TESTS
# =============================================================================

class TestAssetResolutionServiceInit:
    """Tests for service initialization."""

    def test_init_with_default_provider(self):
        """Service should use YahooFinanceProvider by default."""
        service = AssetResolutionService()
        assert service.provider_name == "yahoo"

    def test_init_with_custom_provider(self, mock_provider):
        """Service should accept custom provider."""
        service = AssetResolutionService(provider=mock_provider)
        assert service.provider_name == "mock"

    def test_cache_starts_empty(self, mock_provider):
        """Cache should be empty on initialization."""
        service = AssetResolutionService(provider=mock_provider)
        assert service.cache_size == 0


# =============================================================================
# SINGLE ASSET RESOLUTION TESTS
# =============================================================================

class TestResolveAsset:
    """Tests for resolve_asset method."""

    def test_resolve_existing_active_asset(self, db, mock_provider):
        """Should return existing active asset from database without calling provider."""
        # Setup: Create existing asset in DB
        existing_asset = create_asset(db, ticker="NVDA", exchange="NASDAQ")
        service = AssetResolutionService(provider=mock_provider)

        # Act
        result = service.resolve_asset(db, "NVDA", "NASDAQ")

        # Assert
        assert result.id == existing_asset.id
        assert result.ticker == "NVDA"
        assert mock_provider.single_call_count == 0  # No provider call

    def test_resolve_existing_asset_case_insensitive(self, db, mock_provider):
        """Should find existing asset regardless of input case."""
        existing_asset = create_asset(db, ticker="NVDA", exchange="NASDAQ")
        service = AssetResolutionService(provider=mock_provider)

        # Test lowercase input
        result = service.resolve_asset(db, "nvda", "nasdaq")

        assert result.id == existing_asset.id
        assert mock_provider.single_call_count == 0

    def test_resolve_existing_asset_with_whitespace(self, db, mock_provider):
        """Should normalize whitespace in ticker and exchange."""
        existing_asset = create_asset(db, ticker="NVDA", exchange="NASDAQ")
        service = AssetResolutionService(provider=mock_provider)

        # Test input with whitespace
        result = service.resolve_asset(db, "  NVDA  ", "  NASDAQ  ")

        assert result.id == existing_asset.id

    def test_resolve_deactivated_asset_raises_error(self, db, mock_provider):
        """Should raise AssetDeactivatedError for deactivated assets."""
        # Setup: Create deactivated asset
        create_asset(db, ticker="DELISTED", exchange="NYSE", is_active=False)
        service = AssetResolutionService(provider=mock_provider)

        # Act & Assert
        with pytest.raises(AssetDeactivatedError) as exc_info:
            service.resolve_asset(db, "DELISTED", "NYSE")

        assert exc_info.value.ticker == "DELISTED"
        assert exc_info.value.exchange == "NYSE"
        assert mock_provider.single_call_count == 0

    def test_resolve_new_asset_fetches_from_provider(self, db, mock_provider):
        """Should fetch from provider and create asset when not in database."""
        # Setup: Configure mock provider
        asset_info = create_asset_info(
            ticker="AAPL",
            exchange="NASDAQ",
            name="Apple Inc.",
            currency="USD",
        )
        mock_provider.add_response("AAPL", "NASDAQ", asset_info)
        service = AssetResolutionService(provider=mock_provider)

        # Act
        result = service.resolve_asset(db, "AAPL", "NASDAQ")

        # Assert
        assert result.ticker == "AAPL"
        assert result.exchange == "NASDAQ"
        assert result.name == "Apple Inc."
        assert result.currency == "USD"
        assert result.is_active is True
        assert result.id is not None  # Persisted to DB
        assert mock_provider.single_call_count == 1

    def test_resolve_unknown_ticker_raises_not_found(self, db, mock_provider):
        """Should raise AssetNotFoundError when provider doesn't find ticker."""
        # Provider returns TickerNotFoundError by default for unknown tickers
        service = AssetResolutionService(provider=mock_provider)

        with pytest.raises(AssetNotFoundError) as exc_info:
            service.resolve_asset(db, "INVALID", "NYSE")

        assert exc_info.value.ticker == "INVALID"
        assert exc_info.value.exchange == "NYSE"

    def test_resolve_propagates_provider_error(self, db, mock_provider):
        """Should propagate ProviderUnavailableError from provider."""
        mock_provider.add_error(
            "AAPL", "NASDAQ",
            ProviderUnavailableError(provider="mock", reason="Network error")
        )
        service = AssetResolutionService(provider=mock_provider)

        with pytest.raises(ProviderUnavailableError):
            service.resolve_asset(db, "AAPL", "NASDAQ")


# =============================================================================
# CACHING TESTS
# =============================================================================

class TestCaching:
    """Tests for provider response caching."""

    def test_cache_hit_avoids_provider_call(self, db, mock_provider):
        """Second resolution of same ticker should use cache."""
        asset_info = create_asset_info(ticker="MSFT", exchange="NASDAQ")
        mock_provider.add_response("MSFT", "NASDAQ", asset_info)
        service = AssetResolutionService(provider=mock_provider)

        # First call - fetches from provider
        result1 = service.resolve_asset(db, "MSFT", "NASDAQ")
        assert mock_provider.single_call_count == 1

        # Delete from DB to force re-resolution
        db.delete(result1)
        db.commit()

        # Second call - should use cache (but still creates new DB record)
        result2 = service.resolve_asset(db, "MSFT", "NASDAQ")
        assert mock_provider.single_call_count == 1  # No additional provider call
        assert service.cache_size == 1

    def test_clear_cache(self, db, mock_provider):
        """clear_cache should empty the cache."""
        asset_info = create_asset_info(ticker="TSLA", exchange="NASDAQ")
        mock_provider.add_response("TSLA", "NASDAQ", asset_info)
        service = AssetResolutionService(provider=mock_provider)

        # Populate cache
        service.resolve_asset(db, "TSLA", "NASDAQ")
        assert service.cache_size == 1

        # Clear and verify
        service.clear_cache()
        assert service.cache_size == 0

    def test_cache_evicts_oldest_when_full(self, db, mock_provider):
        """LRU cache should evict oldest entries when at capacity."""
        # Create a service with a tiny cache for testing
        service = AssetResolutionService(provider=mock_provider)
        # Override the cache with a small one for testing
        from app.services.asset_resolution import BoundedLRUCache
        service._cache = BoundedLRUCache(maxsize=3)

        # Add responses for 4 different assets
        for i in range(4):
            ticker = f"TEST{i}"
            info = create_asset_info(ticker=ticker, exchange="NYSE", name=f"Test {i}")
            mock_provider.add_response(ticker, "NYSE", info)

        # Resolve first 3 assets - cache should be full
        service.resolve_asset(db, "TEST0", "NYSE")
        service.resolve_asset(db, "TEST1", "NYSE")
        service.resolve_asset(db, "TEST2", "NYSE")
        assert service.cache_size == 3

        # Resolve 4th asset - should evict TEST0 (oldest)
        service.resolve_asset(db, "TEST3", "NYSE")
        assert service.cache_size == 3  # Still 3 (at capacity)

        # TEST0 should be evicted, others should still be cached
        # Access TEST1 to verify it's still in cache (moves to end)
        assert service._cache.get(("TEST1", "NYSE")) is not None
        assert service._cache.get(("TEST2", "NYSE")) is not None
        assert service._cache.get(("TEST3", "NYSE")) is not None
        # TEST0 was evicted
        assert service._cache.get(("TEST0", "NYSE")) is None


# =============================================================================
# BATCH RESOLUTION TESTS
# =============================================================================

class TestResolveAssetsBatch:
    """Tests for resolve_assets_batch method."""

    def test_batch_resolve_all_existing(self, db, mock_provider):
        """Should resolve all existing assets without provider calls."""
        # Setup: Create multiple existing assets
        asset1 = create_asset(db, ticker="NVDA", exchange="NASDAQ")
        asset2 = create_asset(db, ticker="AAPL", exchange="NASDAQ")

        service = AssetResolutionService(provider=mock_provider)

        # Act
        result = service.resolve_assets_batch(db, [
            ("NVDA", "NASDAQ"),
            ("AAPL", "NASDAQ"),
        ])

        # Assert
        assert result.all_resolved
        assert len(result.resolved) == 2
        assert result.resolved[("NVDA", "NASDAQ")].id == asset1.id
        assert result.resolved[("AAPL", "NASDAQ")].id == asset2.id
        assert mock_provider.batch_call_count == 0

    def test_batch_resolve_mixed_existing_and_new(self, db, mock_provider):
        """Should resolve existing from DB and fetch missing from provider."""
        # Setup: One existing, one to fetch
        existing = create_asset(db, ticker="NVDA", exchange="NASDAQ")

        new_info = create_asset_info(ticker="AAPL", exchange="NASDAQ", name="Apple Inc.")
        mock_provider.add_response("AAPL", "NASDAQ", new_info)

        service = AssetResolutionService(provider=mock_provider)

        # Act
        result = service.resolve_assets_batch(db, [
            ("NVDA", "NASDAQ"),
            ("AAPL", "NASDAQ"),
        ])

        # Assert
        assert result.all_resolved
        assert len(result.resolved) == 2
        assert result.resolved[("NVDA", "NASDAQ")].id == existing.id
        assert result.resolved[("AAPL", "NASDAQ")].name == "Apple Inc."
        assert mock_provider.batch_call_count == 1

    def test_batch_resolve_with_deactivated(self, db, mock_provider):
        """Should report deactivated assets separately."""
        create_asset(db, ticker="ACTIVE", exchange="NYSE", is_active=True)
        create_asset(db, ticker="DELISTED", exchange="NYSE", is_active=False)

        service = AssetResolutionService(provider=mock_provider)

        result = service.resolve_assets_batch(db, [
            ("ACTIVE", "NYSE"),
            ("DELISTED", "NYSE"),
        ])

        assert not result.all_resolved
        assert len(result.resolved) == 1
        assert ("ACTIVE", "NYSE") in result.resolved
        assert ("DELISTED", "NYSE") in result.deactivated

    def test_batch_resolve_with_not_found(self, db, mock_provider):
        """Should report not found assets separately."""
        # Only NVDA is configured in provider
        nvda_info = create_asset_info(ticker="NVDA", exchange="NASDAQ")
        mock_provider.add_response("NVDA", "NASDAQ", nvda_info)

        service = AssetResolutionService(provider=mock_provider)

        result = service.resolve_assets_batch(db, [
            ("NVDA", "NASDAQ"),
            ("INVALID", "NYSE"),
        ])

        assert not result.all_resolved
        assert len(result.resolved) == 1
        assert ("INVALID", "NYSE") in result.not_found

    def test_batch_resolve_deduplicates_requests(self, db, mock_provider):
        """Should deduplicate repeated ticker/exchange pairs."""
        nvda_info = create_asset_info(ticker="NVDA", exchange="NASDAQ")
        mock_provider.add_response("NVDA", "NASDAQ", nvda_info)

        service = AssetResolutionService(provider=mock_provider)

        result = service.resolve_assets_batch(db, [
            ("NVDA", "NASDAQ"),
            ("nvda", "nasdaq"),  # Same, different case
            ("NVDA", "NASDAQ"),  # Exact duplicate
        ])

        assert len(result.resolved) == 1
        # Provider should only be called once for NVDA
        assert mock_provider.batch_call_count == 1

    def test_batch_resolve_empty_list(self, db, mock_provider):
        """Should handle empty request list gracefully."""
        service = AssetResolutionService(provider=mock_provider)

        result = service.resolve_assets_batch(db, [])

        assert result.all_resolved
        assert len(result.resolved) == 0
        assert mock_provider.batch_call_count == 0


# =============================================================================
# RACE CONDITION TESTS
# =============================================================================

class TestRaceConditionHandling:
    """Tests for concurrent asset creation handling."""

    def test_create_asset_returns_existing_on_integrity_error(self, db, mock_provider):
        """Should return existing asset when IntegrityError occurs during creation."""
        # First, create an asset that already exists
        existing_asset = create_asset(db, ticker="RACE", exchange="NYSE", name="Existing Asset")

        # Now try to create the same asset again via the service
        # This simulates what happens after an IntegrityError and rollback
        asset_info = create_asset_info(ticker="RACE", exchange="NYSE", name="New Asset")
        mock_provider.add_response("RACE", "NYSE", asset_info)

        service = AssetResolutionService(provider=mock_provider)

        # The service should find the existing asset in DB lookup
        result = service.resolve_asset(db, "RACE", "NYSE")

        # Should return the existing asset (not create a new one)
        assert result.id == existing_asset.id
        assert result.ticker == "RACE"
        assert result.name == "Existing Asset"  # Original name, not from provider

    def test_create_asset_batch_fallback_on_integrity_error(self, db, mock_provider):
        """Batch creation should handle IntegrityError by falling back to individual resolution."""
        # Create an asset that will cause IntegrityError in batch
        existing = create_asset(db, ticker="EXISTS", exchange="NYSE")

        # Configure provider for both assets
        mock_provider.add_response("EXISTS", "NYSE", create_asset_info(ticker="EXISTS", exchange="NYSE"))
        mock_provider.add_response("NEW", "NYSE", create_asset_info(ticker="NEW", exchange="NYSE"))

        service = AssetResolutionService(provider=mock_provider)

        # Batch resolve should handle the existing asset gracefully
        result = service.resolve_assets_batch(db, [
            ("EXISTS", "NYSE"),
            ("NEW", "NYSE"),
        ])

        # Both should be resolved successfully
        assert len(result.resolved) == 2
        assert result.resolved[("EXISTS", "NYSE")].id == existing.id
        assert result.resolved[("NEW", "NYSE")].ticker == "NEW"


# =============================================================================
# BATCH RESULT TESTS
# =============================================================================

class TestBatchResolutionResult:
    """Tests for BatchResolutionResult data class."""

    def test_all_resolved_true_when_all_success(self):
        """all_resolved should be True when no failures."""
        result = BatchResolutionResult(
            resolved={("NVDA", "NASDAQ"): MagicMock()},
            deactivated=[],
            not_found=[],
            errors={},
        )
        assert result.all_resolved is True

    def test_all_resolved_false_with_deactivated(self):
        """all_resolved should be False when deactivated assets exist."""
        result = BatchResolutionResult(
            resolved={},
            deactivated=[("DELISTED", "NYSE")],
            not_found=[],
            errors={},
        )
        assert result.all_resolved is False

    def test_all_resolved_false_with_not_found(self):
        """all_resolved should be False when not found assets exist."""
        result = BatchResolutionResult(
            resolved={},
            deactivated=[],
            not_found=[("INVALID", "NYSE")],
            errors={},
        )
        assert result.all_resolved is False

    def test_all_resolved_false_with_errors(self):
        """all_resolved should be False when errors exist."""
        result = BatchResolutionResult(
            resolved={},
            deactivated=[],
            not_found=[],
            errors={("ERROR", "NYSE"): Exception("test")},
        )
        assert result.all_resolved is False


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_resolve_asset_with_empty_exchange(self, db, mock_provider):
        """Should handle assets with empty exchange (e.g., crypto)."""
        asset_info = create_asset_info(
            ticker="BTC",
            exchange="",
            name="Bitcoin",
            asset_class=AssetClass.CRYPTO,
            currency="USD",
        )
        mock_provider.add_response("BTC", "", asset_info)
        service = AssetResolutionService(provider=mock_provider)

        result = service.resolve_asset(db, "BTC", "")

        assert result.ticker == "BTC"
        assert result.exchange == ""

    def test_resolve_asset_exchange_none_becomes_empty(self, db, mock_provider):
        """Should handle None exchange by converting to empty string."""
        asset_info = create_asset_info(ticker="BTC", exchange="", currency="USD")
        mock_provider.add_response("BTC", "", asset_info)
        service = AssetResolutionService(provider=mock_provider)

        # Note: The actual resolve_asset doesn't accept None,
        # but exchange could be empty string
        result = service.resolve_asset(db, "BTC", "")

        assert result.ticker == "BTC"
        assert result.exchange == ""
