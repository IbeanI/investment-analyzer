# backend/app/utils/__init__.py
"""
Utility modules for the Investment Portfolio Analyzer.

This package contains cross-cutting utilities used throughout the application:
- logging: Logging configuration and setup
- (future) validation: Common validation helpers
- (future) formatting: Data formatting utilities

Usage:
    from app.utils import setup_logging
"""

from app.utils.logging import setup_logging

__all__ = [
    "setup_logging",
]
