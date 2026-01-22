# backend/app/services/upload/parsers/base.py
"""
Abstract interface for transaction file parsers.

This module defines the contract that all file parsers must follow.
Using an abstract base class allows for:
- Easy addition of new formats (CSV, JSON, Excel, etc.)
- Consistent output structure regardless of input format
- Clear separation between parsing and validation

Design Principles:
- Single Responsibility: Parsers only parse, they don't validate business rules
- Interface Segregation: Only essential methods in the base class
- Dependency Inversion: UploadService depends on this abstraction
"""

import dataclasses
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import BinaryIO, Any


# =============================================================================
# ENUMS
# =============================================================================

class DateFormat(str, Enum):
    """
    Supported date formats for file uploads.

    User must specify which format their file uses to avoid ambiguity
    between formats like M/D/YYYY (US) and D/M/YYYY (EU).

    Example:
        "1/2/2021" could mean:
        - January 2, 2021 (US format)
        - February 1, 2021 (EU format)

        By requiring explicit format declaration, we eliminate this ambiguity.

    Usage:
        POST /upload/transactions?portfolio_id=1&date_format=US
    """

    ISO = "ISO"  # YYYY-MM-DD (default, unambiguous)
    US = "US"  # M/D/YYYY (American)
    EU = "EU"  # D/M/YYYY (European)


class DateDetectionStatus(str, Enum):
    """
    Result status of automatic date format detection.

    UNAMBIGUOUS: Only one format is valid for all dates in the file
    AMBIGUOUS: Multiple formats could be valid (e.g., all dates have day <= 12)
    ERROR: No valid format found (dates are invalid in all formats)
    """
    UNAMBIGUOUS = "unambiguous"
    AMBIGUOUS = "ambiguous"
    ERROR = "error"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class DateInterpretation:
    """
    Shows how a single date value would be interpreted under different formats.

    Used to help users understand ambiguous dates and choose the correct format.

    Attributes:
        raw_value: The original date string from the file
        row_number: 1-based row number where this date appears
        us_interpretation: Date as ISO string if valid under US format (M/D/Y)
        eu_interpretation: Date as ISO string if valid under EU format (D/M/Y)
        iso_interpretation: Date as ISO string if valid under ISO format (Y-M-D)
        is_disambiguator: True if this date proves a specific format
                          (e.g., day > 12 proves it's not EU format)
    """
    raw_value: str
    row_number: int
    us_interpretation: str | None = None
    eu_interpretation: str | None = None
    iso_interpretation: str | None = None
    is_disambiguator: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "raw_value": self.raw_value,
            "row_number": self.row_number,
            "us_interpretation": self.us_interpretation,
            "eu_interpretation": self.eu_interpretation,
            "iso_interpretation": self.iso_interpretation,
            "is_disambiguator": self.is_disambiguator,
        }


@dataclass
class DateDetectionResult:
    """
    Result of automatic date format detection.

    Contains the detection status, detected format (if unambiguous),
    and sample dates showing how they would be interpreted.

    Attributes:
        status: Detection outcome (unambiguous, ambiguous, or error)
        detected_format: The detected format if status is UNAMBIGUOUS
        samples: Sample dates showing interpretations (for user preview)
        reason: Human-readable explanation of the result
    """
    status: DateDetectionStatus
    detected_format: DateFormat | None = None
    samples: list[DateInterpretation] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "status": self.status.value,
            "detected_format": self.detected_format.value if self.detected_format else None,
            "samples": [s.to_dict() for s in self.samples],
            "reason": self.reason,
        }


@dataclass
class ParsedTransactionRow:
    """
    Intermediate representation of a transaction row.
    
    This is format-agnostic: every parser outputs this same structure.
    This decouples parsing from validation.
    
    All fields are strings at this stage - type conversion and validation
    happen later via Pydantic schemas.
    
    Attributes:
        row_number: 1-based row number in source file (for error reporting)
        date: Date string in ISO format (converted from user's format)
        transaction_type: "BUY" or "SELL" (normalized)
        ticker: Trading symbol
        exchange: Exchange code
        quantity: Quantity as string
        price_per_share: Price as string
        currency: Currency code
        fee: Fee as string
        fee_currency: Fee currency code (optional)
        exchange_rate: Exchange rate as string (optional)
        raw_data: Original row data for debugging/error reporting
    """

    row_number: int
    date: str  # Always ISO format internally (YYYY-MM-DDTHH:MM:SSZ)
    transaction_type: str
    ticker: str
    exchange: str
    quantity: str
    price_per_share: str
    currency: str
    fee: str
    fee_currency: str | None = None
    exchange_rate: str | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParseError:
    """
    Represents a parsing error for a specific row.
    
    Attributes:
        row_number: 1-based row number where error occurred
        error_type: Category of error (e.g., "missing_field", "invalid_format")
        message: Human-readable error description
        field: Specific field that caused the error (if applicable)
        raw_data: Original row data for context
    """

    row_number: int
    error_type: str
    message: str
    field: str | None = None
    raw_data: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclass
class ParseResult:
    """
    Result of parsing a file.
    
    Contains both successfully parsed rows and any errors encountered.
    This allows partial success reporting.
    
    Attributes:
        rows: Successfully parsed transaction rows
        errors: Parsing errors (malformed rows, missing fields, etc.)
        total_rows: Total number of rows attempted
    """

    rows: list[ParsedTransactionRow] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)
    total_rows: int = 0

    @property
    def success_count(self) -> int:
        """Number of successfully parsed rows."""
        return len(self.rows)

    @property
    def error_count(self) -> int:
        """Number of rows with parsing errors."""
        return len(self.errors)

    @property
    def all_successful(self) -> bool:
        """True if all rows were parsed successfully."""
        return self.error_count == 0 and self.success_count > 0

    @property
    def has_data(self) -> bool:
        """True if at least one row was successfully parsed."""
        return self.success_count > 0


# =============================================================================
# ABSTRACT BASE CLASS
# =============================================================================

class TransactionFileParser(ABC):
    """
    Abstract base class for transaction file parsers.
    
    Each file format (CSV, JSON, Excel) implements this interface.
    The parser is ONLY responsible for:
    - Reading the file format
    - Mapping columns/fields to our standard structure
    - Converting dates to ISO format using the user-specified format
    - Outputting ParsedTransactionRow objects
    - Reporting parsing errors
    
    It does NOT:
    - Validate data types or business rules (Pydantic does this)
    - Resolve assets (UploadService does this)
    - Create database records (UploadService does this)
    
    Example:
        parser = CSVTransactionParser()
        result = parser.parse(file, "transactions.csv", DateFormat.US)
        
        for row in result.rows:
            print(f"Row {row.row_number}: {row.ticker} {row.transaction_type}")
        
        for error in result.errors:
            print(f"Error on row {error.row_number}: {error.message}")
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Human-readable name for this parser.
        
        Used in error messages and logging.
        
        Returns:
            Parser name (e.g., "CSV", "JSON", "Excel")
        """
        pass

    @property
    @abstractmethod
    def supported_extensions(self) -> set[str]:
        """
        File extensions this parser handles.
        
        Extensions should include the leading dot and be lowercase.
        
        Returns:
            Set of extensions (e.g., {".csv"}, {".json"}, {".xlsx", ".xls"})
        """
        pass

    @property
    @abstractmethod
    def supported_content_types(self) -> set[str]:
        """
        MIME types this parser handles.
        
        Used as fallback when extension is ambiguous.
        
        Returns:
            Set of MIME types (e.g., {"text/csv"}, {"application/json"})
        """
        pass

    @abstractmethod
    def parse(
            self,
            file: BinaryIO,
            filename: str,
            date_format: DateFormat = DateFormat.ISO,
    ) -> ParseResult:
        """
        Parse file contents into transaction rows.
        
        Implementations should:
        - Read the file format appropriately
        - Map source columns/fields to ParsedTransactionRow fields
        - Convert dates to ISO format using the specified date_format
        - Normalize transaction types (Buy/buy/BUY -> "BUY")
        - Capture parsing errors without raising exceptions
        - Include raw_data in both rows and errors for debugging
        
        Args:
            file: File-like object (binary mode) to read from
            filename: Original filename (for error messages)
            date_format: User-specified date format for parsing dates
            
        Returns:
            ParseResult containing parsed rows and any errors
            
        Note:
            This method should NOT raise exceptions for individual row errors.
            Instead, capture them in ParseResult.errors and continue processing.
            Only raise exceptions for file-level errors (e.g., unreadable file).
        """
        pass

    def supports_file(self, filename: str, content_type: str | None = None) -> bool:
        """
        Check if this parser can handle the given file.
        
        Args:
            filename: Name of the file to check
            content_type: Optional MIME type
            
        Returns:
            True if this parser can handle the file
        """
        from pathlib import Path

        extension = Path(filename).suffix.lower()

        if extension in self.supported_extensions:
            return True

        if content_type and content_type.lower() in self.supported_content_types:
            return True

        return False
