# backend/app/utils/logging.py
"""
Logging configuration for the Investment Portfolio Analyzer.

This module provides centralized logging setup with:
- Environment-based log levels (DEBUG in dev, INFO in prod)
- Consistent formatting across all modules
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
    LOG_LEVEL=DEBUG   # Development - see everything
    LOG_LEVEL=INFO    # Production - business events + errors
    LOG_LEVEL=WARNING # Testing - only problems
"""

import logging
import sys

from app.config import settings

# =============================================================================
# CONSTANTS
# =============================================================================

# Default format: timestamp | level | logger_name | message
DEFAULT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

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
# SETUP FUNCTION
# =============================================================================

def setup_logging(
        level: str | None = None,
        format_string: str | None = None,
        date_format: str | None = None,
        suppress_noisy_loggers: bool = True,
) -> None:
    """
    Configure application-wide logging.

    This function should be called once at application startup,
    before creating the FastAPI application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
               Defaults to settings.log_level from environment.
        format_string: Log message format.
                       Defaults to "timestamp | level | logger | message".
        date_format: Timestamp format.
                     Defaults to "YYYY-MM-DD HH:MM:SS".
        suppress_noisy_loggers: If True, set third-party loggers to WARNING
                                to reduce noise. Defaults to True.

    Example:
        # Basic usage (uses settings from environment)
        setup_logging()

        # Custom configuration
        setup_logging(
            level="DEBUG",
            suppress_noisy_loggers=False,
        )
    """
    # Determine log level
    log_level_str = level or settings.log_level
    log_level = _get_log_level(log_level_str)

    # Determine format
    log_format = format_string or DEFAULT_FORMAT
    log_date_format = date_format or DEFAULT_DATE_FORMAT

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt=log_date_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
        force=True,  # Override any existing configuration
    )

    # Suppress noisy third-party loggers
    if suppress_noisy_loggers:
        _suppress_noisy_loggers()

    # Log the configuration (using a logger from this module)
    logger = logging.getLogger(__name__)
    logger.info(f"Logging configured: level={log_level_str}")


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
# UTILITY FUNCTIONS
# =============================================================================

def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the specified name.

    This is a convenience function that's equivalent to logging.getLogger()
    but provides a single import point.

    Args:
        name: Logger name, typically __name__ of the calling module

    Returns:
        Configured logger instance

    Example:
        from app.utils.logging import get_logger

        logger = get_logger(__name__)
        logger.info("Something happened")
    """
    return logging.getLogger(name)
