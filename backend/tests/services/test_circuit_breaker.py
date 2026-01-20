# tests/services/test_circuit_breaker.py
"""
Tests for the circuit breaker implementation.
"""

import pytest
import time
from unittest.mock import Mock

from app.services.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpen,
    CircuitState,
)


class TestCircuitBreakerInit:
    """Tests for circuit breaker initialization."""

    def test_default_values(self):
        """Should initialize with default values."""
        breaker = CircuitBreaker(name="test")

        assert breaker.name == "test"
        assert breaker.failure_threshold == 5
        assert breaker.recovery_timeout == 60.0
        assert breaker.half_open_max_calls == 3
        assert breaker.state == CircuitState.CLOSED

    def test_custom_values(self):
        """Should accept custom configuration."""
        breaker = CircuitBreaker(
            name="custom",
            failure_threshold=3,
            recovery_timeout=30.0,
            half_open_max_calls=2,
            failure_window=60.0,
        )

        assert breaker.failure_threshold == 3
        assert breaker.recovery_timeout == 30.0
        assert breaker.half_open_max_calls == 2
        assert breaker.failure_window == 60.0

    def test_invalid_failure_threshold(self):
        """Should reject invalid failure threshold."""
        with pytest.raises(ValueError, match="failure_threshold must be at least 1"):
            CircuitBreaker(name="test", failure_threshold=0)

    def test_invalid_recovery_timeout(self):
        """Should reject negative recovery timeout."""
        with pytest.raises(ValueError, match="recovery_timeout cannot be negative"):
            CircuitBreaker(name="test", recovery_timeout=-1)

    def test_invalid_half_open_max_calls(self):
        """Should reject invalid half_open_max_calls."""
        with pytest.raises(ValueError, match="half_open_max_calls must be at least 1"):
            CircuitBreaker(name="test", half_open_max_calls=0)


class TestCircuitBreakerClosedState:
    """Tests for circuit breaker in closed state."""

    def test_allows_calls_when_closed(self):
        """Should allow calls when circuit is closed."""
        breaker = CircuitBreaker(name="test", failure_threshold=3)
        call_count = 0

        for _ in range(10):
            with breaker:
                call_count += 1

        assert call_count == 10
        assert breaker.state == CircuitState.CLOSED

    def test_records_successful_calls(self):
        """Should record successful calls in stats."""
        breaker = CircuitBreaker(name="test")

        for _ in range(5):
            with breaker:
                pass

        stats = breaker.stats
        assert stats.total_calls == 5
        assert stats.successful_calls == 5
        assert stats.failed_calls == 0

    def test_opens_after_threshold_failures(self):
        """Should open after failure threshold is reached."""
        breaker = CircuitBreaker(name="test", failure_threshold=3)

        for i in range(3):
            with pytest.raises(ValueError):
                with breaker:
                    raise ValueError(f"Failure {i}")

        assert breaker.state == CircuitState.OPEN

    def test_records_failed_calls(self):
        """Should record failed calls in stats."""
        breaker = CircuitBreaker(name="test", failure_threshold=5)

        for i in range(3):
            with pytest.raises(ValueError):
                with breaker:
                    raise ValueError(f"Failure {i}")

        stats = breaker.stats
        assert stats.failed_calls == 3
        assert stats.state_changes == 0  # Not yet opened

    def test_excluded_exceptions_dont_trip_circuit(self):
        """Excluded exceptions should not count as failures."""
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=2,
            excluded_exceptions=(KeyError,),
        )

        # These should not count as failures
        for _ in range(5):
            with pytest.raises(KeyError):
                with breaker:
                    raise KeyError("excluded")

        assert breaker.state == CircuitState.CLOSED
        stats = breaker.stats
        assert stats.successful_calls == 5  # Excluded = success
        assert stats.failed_calls == 0


class TestCircuitBreakerOpenState:
    """Tests for circuit breaker in open state."""

    def test_rejects_calls_when_open(self):
        """Should reject calls when circuit is open."""
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=2,
            recovery_timeout=60.0,
        )

        # Trip the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                with breaker:
                    raise ValueError("failure")

        assert breaker.state == CircuitState.OPEN

        # Subsequent calls should be rejected
        with pytest.raises(CircuitBreakerOpen) as exc_info:
            with breaker:
                pass

        assert exc_info.value.breaker_name == "test"
        assert exc_info.value.time_remaining > 0

    def test_records_rejected_calls(self):
        """Should record rejected calls in stats."""
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=60.0,
        )

        # Trip the circuit
        with pytest.raises(ValueError):
            with breaker:
                raise ValueError("failure")

        # Try to call while open
        for _ in range(3):
            with pytest.raises(CircuitBreakerOpen):
                with breaker:
                    pass

        stats = breaker.stats
        assert stats.rejected_calls == 3

    def test_transitions_to_half_open_after_timeout(self):
        """Should transition to half-open after recovery timeout."""
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.1,  # 100ms
        )

        # Trip the circuit
        with pytest.raises(ValueError):
            with breaker:
                raise ValueError("failure")

        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        time.sleep(0.15)

        assert breaker.state == CircuitState.HALF_OPEN


class TestCircuitBreakerHalfOpenState:
    """Tests for circuit breaker in half-open state."""

    def test_allows_limited_calls_in_half_open(self):
        """Should allow limited calls in half-open state."""
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.1,
            half_open_max_calls=2,
        )

        # Trip the circuit
        with pytest.raises(ValueError):
            with breaker:
                raise ValueError("failure")

        # Wait for half-open
        time.sleep(0.15)
        assert breaker.state == CircuitState.HALF_OPEN

        # First call allowed
        with breaker:
            pass

        # Circuit should close on success
        assert breaker.state == CircuitState.CLOSED

    def test_reopens_on_failure_in_half_open(self):
        """Should reopen if call fails in half-open state."""
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.1,
            half_open_max_calls=3,
        )

        # Trip the circuit
        with pytest.raises(ValueError):
            with breaker:
                raise ValueError("failure")

        # Wait for half-open
        time.sleep(0.15)
        assert breaker.state == CircuitState.HALF_OPEN

        # Fail in half-open
        with pytest.raises(ValueError):
            with breaker:
                raise ValueError("failure in half-open")

        # Should be open again
        assert breaker.state == CircuitState.OPEN

    def test_closes_on_success_in_half_open(self):
        """Should close on successful call in half-open state."""
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.1,
        )

        # Trip the circuit
        with pytest.raises(ValueError):
            with breaker:
                raise ValueError("failure")

        # Wait for half-open
        time.sleep(0.15)

        # Successful call should close circuit
        with breaker:
            pass

        assert breaker.state == CircuitState.CLOSED
        assert breaker.stats.state_changes == 3  # CLOSED->OPEN->HALF_OPEN->CLOSED


class TestCircuitBreakerFailureWindow:
    """Tests for failure window behavior."""

    def test_failures_outside_window_dont_count(self):
        """Failures outside the window should not count."""
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=3,
            failure_window=0.1,  # 100ms window
        )

        # First failure
        with pytest.raises(ValueError):
            with breaker:
                raise ValueError("failure 1")

        # Wait for failure to expire
        time.sleep(0.15)

        # Two more failures (only these should count)
        for i in range(2):
            with pytest.raises(ValueError):
                with breaker:
                    raise ValueError(f"failure {i+2}")

        # Should still be closed (only 2 failures in window)
        assert breaker.state == CircuitState.CLOSED


class TestCircuitBreakerDecorator:
    """Tests for circuit breaker as decorator."""

    def test_decorator_allows_calls(self):
        """Decorator should allow calls when closed."""
        breaker = CircuitBreaker(name="test", failure_threshold=3)

        @breaker
        def my_function(x):
            return x * 2

        assert my_function(5) == 10
        assert breaker.stats.successful_calls == 1

    def test_decorator_records_failures(self):
        """Decorator should record failures."""
        breaker = CircuitBreaker(name="test", failure_threshold=3)

        @breaker
        def failing_function():
            raise ValueError("error")

        for _ in range(2):
            with pytest.raises(ValueError):
                failing_function()

        assert breaker.stats.failed_calls == 2

    def test_decorator_opens_circuit(self):
        """Decorator should open circuit after threshold."""
        breaker = CircuitBreaker(name="test", failure_threshold=2)

        @breaker
        def failing_function():
            raise ValueError("error")

        for _ in range(2):
            with pytest.raises(ValueError):
                failing_function()

        assert breaker.state == CircuitState.OPEN

        # Next call should be rejected
        with pytest.raises(CircuitBreakerOpen):
            failing_function()


class TestCircuitBreakerManualControl:
    """Tests for manual control methods."""

    def test_manual_reset(self):
        """Should be able to manually reset circuit."""
        breaker = CircuitBreaker(name="test", failure_threshold=1)

        # Trip the circuit
        with pytest.raises(ValueError):
            with breaker:
                raise ValueError("failure")

        assert breaker.state == CircuitState.OPEN

        # Manually reset
        breaker.reset()
        assert breaker.state == CircuitState.CLOSED

    def test_force_open(self):
        """Should be able to force circuit open."""
        breaker = CircuitBreaker(name="test")
        assert breaker.state == CircuitState.CLOSED

        breaker.force_open()
        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerStats:
    """Tests for circuit breaker statistics."""

    def test_stats_isolation(self):
        """Stats should be a copy, not the internal state."""
        breaker = CircuitBreaker(name="test")

        with breaker:
            pass

        stats = breaker.stats
        stats.total_calls = 999  # Modify the copy

        # Internal stats should be unchanged
        assert breaker.stats.total_calls == 1

    def test_state_changes_tracked(self):
        """Should track state changes."""
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.1,
        )

        # Trip the circuit
        with pytest.raises(ValueError):
            with breaker:
                raise ValueError("failure")

        # Wait for half-open
        time.sleep(0.15)
        _ = breaker.state  # Trigger state check

        # Close with success
        with breaker:
            pass

        assert breaker.stats.state_changes == 3  # CLOSED->OPEN->HALF_OPEN->CLOSED


class TestCircuitBreakerThreadSafety:
    """Tests for thread safety (basic verification)."""

    def test_concurrent_access(self):
        """Should handle concurrent access safely."""
        import threading

        breaker = CircuitBreaker(name="test", failure_threshold=100)
        call_count = 0
        lock = threading.Lock()

        def worker():
            nonlocal call_count
            for _ in range(100):
                try:
                    with breaker:
                        with lock:
                            call_count += 1
                except CircuitBreakerOpen:
                    pass

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All calls should have succeeded
        assert call_count == 1000
        assert breaker.stats.successful_calls == 1000
