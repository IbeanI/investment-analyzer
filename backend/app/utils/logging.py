# backend/app/utils/logging.py
"""
Logging configuration for the Investment Portfolio Analyzer.

This module provides centralized logging setup with:
- Environment-based log levels (DEBUG in dev, INFO in prod)
- Structured logging with correlation ID support
- JSON format option for production environments
- Suppression of noisy third-party library logs

Usage:
    from app.utils import setup_logging

    # In main.py, before creating the FastAPI app
    setup_logging()

Log Levels:
    DEBUG   - Detailed flow, cache hits/misses, raw data
    INFO    - Key business events (asset created, transaction recorded)
    WARNING - Recoverable issues (retry attempts, rate limits)
    ERROR   - Failures requiring attention (API down, unexpected exceptions)

Environment Configuration:
    LOG_LEVEL=DEBUG       # Development - see everything
    LOG_LEVEL=INFO        # Production - business events + errors
    LOG_LEVEL=WARNING     # Testing - only problems
    LOG_FORMAT=json       # Production - machine-readable logs
    LOG_FORMAT=text       # Development - human-readable logs (default)

Correlation ID:
    All log messages automatically include the correlation ID when available,
    enabling request tracing across log entries.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.utils.context import get_correlation_id

# =============================================================================
# CONSTANTS
# =============================================================================

# Default text format: timestamp | level | correlation_id | logger_name | message
DEFAULT_TEXT_FORMAT = "%(asctime)s | %(levelname)-8s | %(correlation_id)s | %(name)s | %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Placeholder when no correlation ID is available
NO_CORRELATION_ID = "no-correlation-id"

# Third-party loggers to suppress (set to WARNING to reduce noise)
NOISY_LOGGERS = [
    "yfinance",
    "urllib3",
    "urllib3.connectionpool",
    "requests",
    "httpx",
    "httpcore",
    "peewee",
    "asyncio",
]


# =============================================================================
# CORRELATION ID FILTER
# =============================================================================

class CorrelationIdFilter(logging.Filter):
    """
    Logging filter that adds correlation ID to log records.

    This filter retrieves the correlation ID from the request context
    and adds it to every log record as 'correlation_id'.

    Usage:
        # Automatically applied by setup_logging()
        # Access in format string: %(correlation_id)s
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Add correlation ID to the log record.

        Args:
            record: Log record to modify

        Returns:
            True (always allows the record through)
        """
        correlation_id = get_correlation_id()
        record.correlation_id = correlation_id or NO_CORRELATION_ID
        return True


# =============================================================================
# JSON FORMATTER
# =============================================================================

class JsonFormatter(logging.Formatter):
    """
    JSON formatter for structured logging in production.

    Produces machine-readable JSON logs ideal for log aggregation
    systems like ELK, Datadog, or CloudWatch.

    Output format:
    {
        "timestamp": "2024-01-15T10:30:00.123Z",
        "level": "INFO",
        "logger": "app.services.sync",
        "correlation_id": "abc-123-def",
        "message": "Sync completed for portfolio 1",
        "extra": { ... }  // Any extra fields passed to logger
    }
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON string representation of the log record
        """
        # Get correlation ID (added by filter)
        correlation_id = getattr(record, "correlation_id", NO_CORRELATION_ID)

        # Build base log entry
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "correlation_id": correlation_id,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Add any extra fields from the record
        # Standard LogRecord attributes to exclude
        standard_attrs = {
            "name", "msg", "args", "created", "filename", "funcName",
            "levelname", "levelno", "lineno", "module", "msecs",
            "pathname", "process", "processName", "relativeCreated",
            "stack_info", "exc_info", "exc_text", "thread", "threadName",
            "correlation_id", "message", "taskName",
        }

        extra = {}
        for key, value in record.__dict__.items():
            if key not in standard_attrs:
                try:
                    # Ensure value is JSON serializable
                    json.dumps(value)
                    extra[key] = value
                except (TypeError, ValueError):
                    extra[key] = str(value)

        if extra:
            log_entry["extra"] = extra

        return json.dumps(log_entry)


# =============================================================================
# SETUP FUNCTION
# =============================================================================

def setup_logging(
        level: str | None = None,
        log_format: str | None = None,
        suppress_noisy_loggers: bool = True,
) -> None:
    """
    Configure application-wide logging with correlation ID support.

    This function should be called once at application startup,
    before creating the FastAPI application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
               Defaults to settings.log_level from environment.
        log_format: Output format ('text' or 'json').
                    Defaults to settings.log_format or 'text'.
                    Use 'json' for production/log aggregation.
        suppress_noisy_loggers: If True, set third-party loggers to WARNING
                                to reduce noise. Defaults to True.

    Example:
        # Basic usage (uses settings from environment)
        setup_logging()

        # Development with debug output
        setup_logging(level="DEBUG", log_format="text")

        # Production with JSON logs
        setup_logging(level="INFO", log_format="json")
    """
    # Determine log level
    log_level_str = level or settings.log_level
    log_level = _get_log_level(log_level_str)

    # Determine format (default to text, check settings if available)
    format_type = log_format or getattr(settings, "log_format", "text")

    # Create formatter based on format type
    if format_type.lower() == "json":
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            fmt=DEFAULT_TEXT_FORMAT,
            datefmt=DEFAULT_DATE_FORMAT,
        )

    # Create handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(CorrelationIdFilter())

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers and add our configured handler
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Suppress noisy third-party loggers
    if suppress_noisy_loggers:
        _suppress_noisy_loggers()

    # Log the configuration (using a logger from this module)
    logger = logging.getLogger(__name__)
    logger.info(
        f"Logging configured: level={log_level_str}, format={format_type}",
        extra={"config": {"level": log_level_str, "format": format_type}},
    )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _get_log_level(level_str: str) -> int:
    """
    Convert string log level to logging constant.

    Args:
        level_str: Log level as string (case-insensitive)

    Returns:
        logging level constant (e.g., logging.INFO)

    Raises:
        ValueError: If level_str is not a valid log level
    """
    level_str = level_str.upper().strip()

    level_mapping = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    if level_str not in level_mapping:
        valid_levels = ", ".join(level_mapping.keys())
        raise ValueError(
            f"Invalid log level: '{level_str}'. "
            f"Valid levels are: {valid_levels}"
        )

    return level_mapping[level_str]


def _suppress_noisy_loggers() -> None:
    """
    Set third-party library loggers to WARNING level.

    Many libraries (especially HTTP clients) log at DEBUG/INFO level
    with messages that clutter our logs. This function quiets them
    while still allowing warnings and errors through.
    """
    for logger_name in NOISY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the given name.

    This is a convenience function that returns a standard Python logger.
    The correlation ID is automatically added to all log messages via
    the filter configured in setup_logging().

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance

    Example:
        from app.utils.logging import get_logger

        logger = get_logger(__name__)
        logger.info("Processing transaction", extra={"portfolio_id": 1})
    """
    return logging.getLogger(name)
