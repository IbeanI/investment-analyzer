# backend/app/middleware/correlation.py
"""
Correlation ID middleware for request tracing.

This middleware:
1. Extracts or generates a correlation ID for each request
2. Stores it in context for use throughout the request lifecycle
3. Adds it to response headers for client-side tracing

Correlation ID Sources (in order of precedence):
1. X-Correlation-ID header (from client or upstream service)
2. X-Request-ID header (alternative header name)
3. Generated UUID if neither header is present

Usage:
    from fastapi import FastAPI
    from app.middleware import CorrelationIdMiddleware

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

Client Usage:
    # Pass correlation ID for tracing
    curl -H "X-Correlation-ID: my-trace-123" http://localhost:8000/health

    # Response will include the correlation ID
    # X-Correlation-ID: my-trace-123
"""

import logging
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.utils.context import set_correlation_id, clear_correlation_id

logger = logging.getLogger(__name__)

# Header names for correlation ID
CORRELATION_ID_HEADER = "X-Correlation-ID"
REQUEST_ID_HEADER = "X-Request-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware that manages correlation IDs for request tracing.

    For each request:
    1. Extracts correlation ID from headers (X-Correlation-ID or X-Request-ID)
    2. Generates a new UUID if no header is present
    3. Stores the ID in context (accessible via get_correlation_id())
    4. Adds the ID to response headers

    This enables:
    - End-to-end request tracing in distributed systems
    - Log correlation across services
    - Debugging by filtering logs for a specific request ID
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Response],
    ) -> Response:
        """
        Process request and add correlation ID handling.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            Response with correlation ID header
        """
        # Extract or generate correlation ID
        correlation_id = self._get_correlation_id(request)

        # Store in context for use throughout request lifecycle
        set_correlation_id(correlation_id)

        try:
            # Process the request
            response = await call_next(request)

            # Add correlation ID to response headers
            response.headers[CORRELATION_ID_HEADER] = correlation_id

            return response

        finally:
            # Clean up context after request completes
            clear_correlation_id()

    def _get_correlation_id(self, request: Request) -> str:
        """
        Extract correlation ID from request headers or generate new one.

        Checks headers in order:
        1. X-Correlation-ID
        2. X-Request-ID
        3. Generate new UUID

        Args:
            request: Incoming HTTP request

        Returns:
            Correlation ID string
        """
        # Check for existing correlation ID in headers
        correlation_id = request.headers.get(CORRELATION_ID_HEADER)
        if correlation_id:
            return correlation_id

        # Check alternative header
        correlation_id = request.headers.get(REQUEST_ID_HEADER)
        if correlation_id:
            return correlation_id

        # Generate new correlation ID
        return str(uuid.uuid4())
