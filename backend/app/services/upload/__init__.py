# backend/app/services/upload/__init__.py
"""
Upload service package.

This package provides file upload and processing capabilities:
- Multi-format support (CSV, JSON, Excel - extensible)
- Explicit date format specification (no ambiguity)
- Batch asset resolution
- Atomic transaction creation
- Detailed error reporting

Usage:
    from app.services.upload import UploadService, UploadResult, DateFormat
    
    service = UploadService()
    result = service.process_file(
        db=session,
        file=uploaded_file,
        filename="transactions.csv",
        portfolio_id=1,
        date_format=DateFormat.US,  # For M/D/YYYY dates
    )

Date Format Handling:
    Users must specify their date format to avoid ambiguity:
    - DateFormat.ISO: YYYY-MM-DD (default, unambiguous)
    - DateFormat.US: M/D/YYYY (American style)
    - DateFormat.EU: D/M/YYYY (European style)
    
    All dates are converted to ISO format internally.

Architecture:
    upload/
    ├── __init__.py          # This file - main exports
    ├── service.py           # UploadService (orchestration)
    └── parsers/             # File format parsers
        ├── base.py          # Abstract interface + DateFormat enum
        ├── csv_parser.py    # CSV implementation
        ├── json_parser.py   # JSON implementation (future)
        └── excel_parser.py  # Excel implementation (future)
"""

from app.services.upload.parsers import (
    DateFormat,
    get_parser,
    get_supported_extensions,
    get_supported_content_types,
    TransactionFileParser,
    ParsedTransactionRow,
    ParseError,
    ParseResult,
    UnsupportedFileTypeError,
)
from app.services.upload.service import (
    UploadService,
    UploadResult,
    UploadError,
)

__all__ = [
    # Service
    "UploadService",
    "UploadResult",
    "UploadError",
    # Enums
    "DateFormat",
    # Parser factory
    "get_parser",
    "get_supported_extensions",
    "get_supported_content_types",
    # Parser base
    "TransactionFileParser",
    "ParsedTransactionRow",
    "ParseError",
    "ParseResult",
    # Exceptions
    "UnsupportedFileTypeError",
]
