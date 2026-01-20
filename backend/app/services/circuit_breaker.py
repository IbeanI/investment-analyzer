# backend/app/services/circuit_breaker.py
"""
Circuit breaker pattern implementation for resilient service calls.

The circuit breaker prevents cascading failures by stopping requests to a
failing service after a threshold of failures is reached, allowing the
service time to recover.

States:
    CLOSED  - Normal operation, requests pass through
    OPEN    - Too many failures, requests rejected immediately
    HALF_OPEN - Testing recovery, limited requests allowed

State Transitions:
    CLOSED -> OPEN: When failure count reaches threshold within window
    OPEN -> HALF_OPEN: After recovery timeout expires
    HALF_OPEN -> CLOSED: When a test request succeeds
    HALF_OPEN -> OPEN: When a test request fails

Usage:
    from app.services.circuit_breaker import CircuitBreaker, CircuitBreakerOpen

    # Create circuit breaker
    breaker = CircuitBreaker(
        name="yahoo-finance",
        failure_threshold=5,
        recovery_timeout=60,
        half_open_max_calls=3,
    )

    # Use as context manager
    try:
        with breaker:
            result = call_external_service()
    except CircuitBreakerOpen:
        # Circuit is open, return cached data or error
        return fallback_response()

    # Or use as decorator
    @breaker
    def fetch_data():
        return call_external_service()
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Callable, TypeVar, Any

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Blocking requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreakerOpen(Exception):
    """
    Exception raised when circuit breaker is open.

    This exception indicates that the protected service is unavailable
    and requests are being blocked to prevent cascading failures.

    Attributes:
        breaker_name: Name of the circuit breaker
        time_remaining: Seconds until recovery timeout expires
    """

    def __init__(self, breaker_name: str, time_remaining: float) -> None:
        self.breaker_name = breaker_name
        self.time_remaining = time_remaining
        super().__init__(
            f"Circuit breaker '{breaker_name}' is open. "
            f"Retry in {time_remaining:.1f} seconds."
        )


@dataclass
class CircuitBreakerStats:
    """
    Statistics for monitoring circuit breaker behavior.

    Attributes:
        total_calls: Total number of calls attempted
        successful_calls: Number of successful calls
        failed_calls: Number of failed calls
        rejected_calls: Number of calls rejected (circuit open)
        state_changes: Number of state transitions
        last_failure_time: Timestamp of last failure
        last_success_time: Timestamp of last success
    """
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    state_changes: int = 0
    last_failure_time: float | None = None
    last_success_time: float | None = None


@dataclass
class CircuitBreaker:
    """
    Thread-safe circuit breaker implementation.

    The circuit breaker monitors calls to an external service and opens
    (blocks requests) when too many failures occur, allowing the service
    time to recover.

    Attributes:
        name: Identifier for this circuit breaker (used in logs/errors)
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Seconds to wait before testing recovery
        half_open_max_calls: Max calls allowed in half-open state
        failure_window: Time window (seconds) for counting failures (0 = no window)
        excluded_exceptions: Exception types that don't count as failures

    Example:
        breaker = CircuitBreaker(
            name="payment-gateway",
            failure_threshold=5,
            recovery_timeout=30,
        )

        @breaker
        def process_payment(amount):
            return gateway.charge(amount)
    """

    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    half_open_max_calls: int = 3
    failure_window: float = 0.0  # 0 = count all failures, >0 = sliding window
    excluded_exceptions: tuple[type[Exception], ...] = field(default_factory=tuple)

    # Internal state (not part of constructor)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _failure_timestamps: list[float] = field(default_factory=list, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _half_open_calls: int = field(default=0, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _stats: CircuitBreakerStats = field(default_factory=CircuitBreakerStats, init=False)

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if self.recovery_timeout < 0:
            raise ValueError("recovery_timeout cannot be negative")
        if self.half_open_max_calls < 1:
            raise ValueError("half_open_max_calls must be at least 1")

        logger.info(
            f"CircuitBreaker '{self.name}' initialized: "
            f"threshold={self.failure_threshold}, "
            f"recovery_timeout={self.recovery_timeout}s"
        )

    @property
    def state(self) -> CircuitState:
        """Current state of the circuit breaker."""
        with self._lock:
            self._check_state_transition()
            return self._state

    @property
    def stats(self) -> CircuitBreakerStats:
        """Get a copy of current statistics."""
        with self._lock:
            return CircuitBreakerStats(
                total_calls=self._stats.total_calls,
                successful_calls=self._stats.successful_calls,
                failed_calls=self._stats.failed_calls,
                rejected_calls=self._stats.rejected_calls,
                state_changes=self._stats.state_changes,
                last_failure_time=self._stats.last_failure_time,
                last_success_time=self._stats.last_success_time,
            )

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self.state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        return self.state == CircuitState.OPEN

    def _check_state_transition(self) -> None:
        """
        Check if state should transition based on current conditions.

        Called internally before each operation to ensure state is current.
        Must be called while holding the lock.
        """
        if self._state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            time_since_failure = time.time() - self._last_failure_time
            if time_since_failure >= self.recovery_timeout:
                self._transition_to(CircuitState.HALF_OPEN)

    def _transition_to(self, new_state: CircuitState) -> None:
        """
        Transition to a new state.

        Must be called while holding the lock.
        """
        old_state = self._state
        self._state = new_state
        self._stats.state_changes += 1

        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0

        if new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._failure_timestamps.clear()

        logger.info(
            f"CircuitBreaker '{self.name}' state change: "
            f"{old_state.value} -> {new_state.value}"
        )

    def _record_success(self) -> None:
        """Record a successful call. Must be called while holding the lock."""
        self._stats.successful_calls += 1
        self._stats.last_success_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            # Successful call in half-open state closes the circuit
            self._transition_to(CircuitState.CLOSED)

    def _record_failure(self) -> None:
        """Record a failed call. Must be called while holding the lock."""
        current_time = time.time()
        self._stats.failed_calls += 1
        self._stats.last_failure_time = current_time
        self._last_failure_time = current_time

        if self._state == CircuitState.HALF_OPEN:
            # Failure in half-open state opens the circuit again
            self._transition_to(CircuitState.OPEN)
            return

        if self._state == CircuitState.CLOSED:
            # Track failure in sliding window if configured
            if self.failure_window > 0:
                self._failure_timestamps.append(current_time)
                # Remove old failures outside the window
                cutoff = current_time - self.failure_window
                self._failure_timestamps = [
                    t for t in self._failure_timestamps if t > cutoff
                ]
                self._failure_count = len(self._failure_timestamps)
            else:
                self._failure_count += 1

            # Check if threshold exceeded
            if self._failure_count >= self.failure_threshold:
                self._transition_to(CircuitState.OPEN)

    def _can_execute(self) -> bool:
        """
        Check if a call can be executed in the current state.

        Must be called while holding the lock.
        Returns True if call is allowed, False if circuit is open.
        """
        self._check_state_transition()

        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.HALF_OPEN:
            if self._half_open_calls < self.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False

        # OPEN state
        return False

    def _time_until_recovery(self) -> float:
        """Calculate time remaining until recovery timeout expires."""
        elapsed = time.time() - self._last_failure_time
        remaining = self.recovery_timeout - elapsed
        return max(0.0, remaining)

    def __enter__(self) -> "CircuitBreaker":
        """
        Context manager entry - check if call is allowed.

        Raises:
            CircuitBreakerOpen: If circuit is open
        """
        with self._lock:
            self._stats.total_calls += 1

            if not self._can_execute():
                self._stats.rejected_calls += 1
                raise CircuitBreakerOpen(
                    self.name,
                    self._time_until_recovery()
                )

        return self

    def __exit__(self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any) -> bool:
        """
        Context manager exit - record success or failure.

        Returns False to propagate any exception.
        """
        with self._lock:
            if exc_val is None:
                # No exception - success
                self._record_success()
            elif self.excluded_exceptions and isinstance(exc_val, self.excluded_exceptions):
                # Excluded exception - treat as success (don't count as failure)
                self._record_success()
            else:
                # Exception occurred - failure
                self._record_failure()

        return False  # Don't suppress exceptions

    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        """
        Use circuit breaker as a decorator.

        Example:
            @circuit_breaker
            def fetch_data():
                return external_api.get_data()
        """
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            with self:
                return func(*args, **kwargs)
        return wrapper

    def reset(self) -> None:
        """
        Manually reset the circuit breaker to closed state.

        Use this for administrative purposes or after manual intervention.
        """
        with self._lock:
            self._transition_to(CircuitState.CLOSED)
            logger.info(f"CircuitBreaker '{self.name}' manually reset")

    def force_open(self) -> None:
        """
        Manually open the circuit breaker.

        Use this for maintenance or when service is known to be down.
        """
        with self._lock:
            self._last_failure_time = time.time()
            self._transition_to(CircuitState.OPEN)
            logger.warning(f"CircuitBreaker '{self.name}' manually opened")
