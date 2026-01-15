# backend/app/services/upload/parsers/__init__.py
"""
Transaction file parsers package.

This package contains parsers for different file formats:
- CSV (implemented)
- JSON (future)
- Excel (future)

Usage:
    from app.services.upload.parsers import get_parser, DateFormat, ParseResult
    
    # Get appropriate parser for file
    parser = get_parser("transactions.csv", "text/csv")
    
    # Parse file with explicit date format
    with open("transactions.csv", "rb") as f:
        result = parser.parse(f, "transactions.csv", DateFormat.US)

The factory function `get_parser()` automatically selects the correct
parser based on file extension or content type.

Date Format Handling:
    Users must specify their date format to avoid ambiguity:
    - DateFormat.ISO: YYYY-MM-DD (default, unambiguous)
    - DateFormat.US: M/D/YYYY (American style)
    - DateFormat.EU: D/M/YYYY (European style)
"""

import logging
from pathlib import Path

from app.services.upload.parsers.base import (
    DateFormat,
    TransactionFileParser,
    ParsedTransactionRow,
    ParseError,
    ParseResult,
)
from app.services.upload.parsers.csv_parser import CSVTransactionParser

logger = logging.getLogger(__name__)

# =============================================================================
# PARSER REGISTRY
# =============================================================================

# All available parsers - add new parsers here
_PARSERS: list[TransactionFileParser] = [
    CSVTransactionParser(),
    # JSONTransactionParser(),   # Future
    # ExcelTransactionParser(),  # Future
]


# =============================================================================
# EXCEPTIONS
# =============================================================================

class UnsupportedFileTypeError(Exception):
    """
    Raised when no parser is available for a file type.
    
    Attributes:
        filename: Name of the unsupported file
        extension: File extension
        supported: List of supported extensions
    """

    def __init__(
            self,
            filename: str,
            extension: str,
            supported: list[str],
    ) -> None:
        self.filename = filename
        self.extension = extension
        self.supported = supported

        message = (
            f"Unsupported file type: '{extension}'. "
            f"Supported formats: {', '.join(supported)}"
        )
        super().__init__(message)


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def get_parser(
        filename: str,
        content_type: str | None = None
) -> TransactionFileParser:
    """
    Get the appropriate parser for a file.
    
    Selects parser based on file extension first, then content type.
    
    Args:
        filename: Name of the file to parse
        content_type: Optional MIME type from upload
        
    Returns:
        Parser instance that can handle this file type
        
    Raises:
        UnsupportedFileTypeError: If no parser supports this file type
        
    Example:
        parser = get_parser("transactions.csv")
        parser = get_parser("data.txt", content_type="text/csv")
    """
    extension = Path(filename).suffix.lower()

    logger.debug(
        f"Finding parser for: {filename} "
        f"(extension={extension}, content_type={content_type})"
    )

    # Try to find matching parser
    for parser in _PARSERS:
        if parser.supports_file(filename, content_type):
            logger.debug(f"Selected parser: {parser.name}")
            return parser

    # No parser found - raise with helpful message
    supported = []
    for parser in _PARSERS:
        supported.extend(parser.supported_extensions)

    raise UnsupportedFileTypeError(
        filename=filename,
        extension=extension,
        supported=sorted(set(supported)),
    )


def get_supported_extensions() -> list[str]:
    """
    Get list of all supported file extensions.
    
    Returns:
        Sorted list of supported extensions (e.g., [".csv", ".json"])
    """
    extensions = set()
    for parser in _PARSERS:
        extensions.update(parser.supported_extensions)
    return sorted(extensions)


def get_supported_content_types() -> list[str]:
    """
    Get list of all supported MIME types.
    
    Returns:
        Sorted list of supported content types
    """
    content_types = set()
    for parser in _PARSERS:
        content_types.update(parser.supported_content_types)
    return sorted(content_types)


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "DateFormat",
    # Factory
    "get_parser",
    "get_supported_extensions",
    "get_supported_content_types",
    # Base classes
    "TransactionFileParser",
    "ParsedTransactionRow",
    "ParseError",
    "ParseResult",
    # Concrete parsers
    "CSVTransactionParser",
    # Exceptions
    "UnsupportedFileTypeError",
]
