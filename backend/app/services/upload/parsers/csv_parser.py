# backend/app/services/upload/parsers/csv_parser.py
"""
CSV transaction file parser.

Parses CSV files containing transaction data into a standardized format.
Supports flexible column mapping and explicit date format specification.

Expected CSV Format (DEGIRO-style):
    date,action,ticker,product_description,reference_exchange,quantity,price,price_currency,exchange_rate,fee,fee_currency,note
    1/22/2021,Buy,VWRL,VANGUARD FTSE AW,AEB,1.0000,90.1400,EUR,1.0000,0.0000,EUR,DEGIRO

Column Mapping:
    CSV Column          -> Internal Field
    ----------------------------------------
    date                -> date
    action              -> transaction_type
    ticker              -> ticker
    reference_exchange  -> exchange
    quantity            -> quantity
    price               -> price_per_share
    price_currency      -> currency
    exchange_rate       -> exchange_rate
    fee                 -> fee
    fee_currency        -> fee_currency
    product_description -> (ignored, fetched from provider)
    note                -> (ignored for now)

Date Format Handling:
    User must specify which format their CSV uses to avoid ambiguity:
    - ISO: YYYY-MM-DD (default, unambiguous)
    - US: M/D/YYYY (American style)
    - EU: D/M/YYYY (European style)
    
    All dates are converted to ISO format internally.
"""

import csv
import io
import logging
from datetime import datetime
from typing import BinaryIO

from app.services.upload.parsers.base import (
    TransactionFileParser,
    ParsedTransactionRow,
    ParseError,
    ParseResult,
    DateFormat,
    DateDetectionStatus,
    DateInterpretation,
    DateDetectionResult,
)

logger = logging.getLogger(__name__)


class CSVTransactionParser(TransactionFileParser):
    """
    Parser for CSV transaction files.
    
    Features:
    - Flexible column mapping (handles different CSV layouts)
    - Explicit date format specification (no ambiguity)
    - Graceful error handling per row
    - Encoding detection (UTF-8, Latin-1)
    
    Example:
        parser = CSVTransactionParser()
        
        with open("transactions.csv", "rb") as f:
            # For US-style dates (M/D/YYYY)
            result = parser.parse(f, "transactions.csv", DateFormat.US)
        
        print(f"Parsed {result.success_count} transactions")
        print(f"Errors: {result.error_count}")
    """

    # =========================================================================
    # CONFIGURATION
    # =========================================================================

    # Column name mapping: CSV header -> internal field name
    # Supports multiple possible names for each field
    COLUMN_MAPPING: dict[str, list[str]] = {
        "date": ["date", "trade_date", "transaction_date", "datum"],
        "transaction_type": ["action", "type", "transaction_type", "side"],
        "ticker": ["ticker", "symbol", "isin", "product"],
        "exchange": ["reference_exchange", "exchange", "market", "venue"],
        "quantity": ["quantity", "qty", "shares", "units", "amount"],
        "price_per_share": ["price", "price_per_share", "unit_price", "share_price"],
        "currency": ["price_currency", "currency", "ccy"],
        "fee": ["fee", "commission", "fees", "cost"],
        "fee_currency": ["fee_currency"],
        "exchange_rate": ["exchange_rate", "fx_rate", "rate"],
    }

    # Transaction type normalization
    TYPE_MAPPING: dict[str, str] = {
        "buy": "BUY",
        "b": "BUY",
        "purchase": "BUY",
        "kauf": "BUY",  # German
        "sell": "SELL",
        "s": "SELL",
        "sale": "SELL",
        "verkauf": "SELL",  # German
    }

    # Date format patterns by user selection
    # Each format only allows unambiguous patterns for that locale
    DATE_FORMAT_PATTERNS: dict[DateFormat, list[str]] = {
        DateFormat.ISO: [
            "%Y-%m-%d",  # 2021-01-22
            "%Y/%m/%d",  # 2021/01/22
        ],
        DateFormat.US: [
            "%m/%d/%Y",  # 1/22/2021 or 01/22/2021
            "%m-%d-%Y",  # 01-22-2021
            "%m/%d/%y",  # 1/22/21 (2-digit year)
        ],
        DateFormat.EU: [
            "%d/%m/%Y",  # 22/01/2021
            "%d-%m-%Y",  # 22-01-2021
            "%d.%m.%Y",  # 22.01.2021 (German)
            "%d/%m/%y",  # 22/01/21 (2-digit year)
        ],
    }

    # Required fields (must be present and non-empty)
    REQUIRED_FIELDS: set[str] = {
        "date",
        "transaction_type",
        "ticker",
        "exchange",
        "quantity",
        "price_per_share",
        "currency",
    }

    # =========================================================================
    # INTERFACE IMPLEMENTATION
    # =========================================================================

    @property
    def name(self) -> str:
        return "CSV"

    @property
    def supported_extensions(self) -> set[str]:
        return {".csv"}

    @property
    def supported_content_types(self) -> set[str]:
        return {"text/csv", "application/csv", "text/plain"}

    def parse(
            self,
            file: BinaryIO,
            filename: str,
            date_format: DateFormat = DateFormat.ISO,
    ) -> ParseResult:
        """
        Parse CSV file into transaction rows.
        
        Args:
            file: Binary file object containing CSV data
            filename: Original filename for error messages
            date_format: User-specified date format (ISO, US, or EU)
            
        Returns:
            ParseResult with parsed rows and errors
        """
        logger.info(f"Parsing CSV file: {filename} (date_format={date_format.value})")

        result = ParseResult()

        # Read and decode file content
        try:
            content = self._read_file_content(file)
        except Exception as e:
            logger.error(f"Failed to read file {filename}: {e}", exc_info=True)
            result.errors.append(ParseError(
                row_number=0,
                error_type="file_read_error",
                message=f"Could not read file: {e}",
            ))
            return result

        # Parse CSV
        try:
            reader = csv.DictReader(io.StringIO(content))

            # Validate headers
            if not reader.fieldnames:
                result.errors.append(ParseError(
                    row_number=0,
                    error_type="missing_headers",
                    message="CSV file has no headers",
                ))
                return result

            # Build column mapping for this file
            column_map = self._build_column_map(reader.fieldnames)

            # Check for missing required columns
            missing_columns = self._get_missing_columns(column_map)
            if missing_columns:
                result.errors.append(ParseError(
                    row_number=0,
                    error_type="missing_columns",
                    message=f"Missing required columns: {', '.join(missing_columns)}",
                ))
                return result

            # Parse each row
            for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
                result.total_rows += 1

                parsed_row, error = self._parse_row(
                    row_num, row, column_map, date_format
                )

                if error:
                    result.errors.append(error)
                elif parsed_row:
                    result.rows.append(parsed_row)

        except csv.Error as e:
            logger.error(f"CSV parsing error in {filename}: {e}")
            result.errors.append(ParseError(
                row_number=0,
                error_type="csv_format_error",
                message=f"Invalid CSV format: {e}",
            ))

        logger.info(
            f"Parsed {filename}: {result.success_count} rows OK, "
            f"{result.error_count} errors"
        )

        return result

    def detect_date_format(
            self,
            file: BinaryIO,
            filename: str,
            max_samples: int = 5,
    ) -> DateDetectionResult:
        """
        Detect the date format used in a CSV file.

        Analyzes all dates in the file and determines:
        - If dates are unambiguous (only one format works)
        - If dates are ambiguous (multiple formats could work)
        - If dates are invalid in all formats

        A date like "1/22/2021" is a "disambiguator" because day=22 > 12,
        meaning it can only be US format (M/D/Y), not EU format (D/M/Y).

        Args:
            file: Binary file object containing CSV data
            filename: Original filename for error messages
            max_samples: Maximum number of sample dates to return

        Returns:
            DateDetectionResult with status, detected format, and samples
        """
        logger.info(f"Detecting date format for: {filename}")

        # Read and decode file content
        try:
            content = self._read_file_content(file)
        except Exception as e:
            logger.error(f"Failed to read file {filename}: {e}", exc_info=True)
            return DateDetectionResult(
                status=DateDetectionStatus.ERROR,
                reason=f"Could not read file: {e}",
            )

        # Parse CSV to extract dates
        try:
            reader = csv.DictReader(io.StringIO(content))

            if not reader.fieldnames:
                return DateDetectionResult(
                    status=DateDetectionStatus.ERROR,
                    reason="CSV file has no headers",
                )

            # Build column mapping
            column_map = self._build_column_map(reader.fieldnames)

            if "date" not in column_map:
                return DateDetectionResult(
                    status=DateDetectionStatus.ERROR,
                    reason="CSV file has no date column",
                )

            date_column = column_map["date"]

            # Collect all date values with their row numbers
            date_values: list[tuple[int, str]] = []
            for row_num, row in enumerate(reader, start=2):
                raw_date = row.get(date_column, "").strip()
                if raw_date:
                    date_values.append((row_num, raw_date))

            if not date_values:
                return DateDetectionResult(
                    status=DateDetectionStatus.ERROR,
                    reason="No dates found in file",
                )

            # Analyze dates and determine viable formats
            return self._analyze_dates(date_values, max_samples)

        except csv.Error as e:
            logger.error(f"CSV parsing error in {filename}: {e}")
            return DateDetectionResult(
                status=DateDetectionStatus.ERROR,
                reason=f"Invalid CSV format: {e}",
            )

    def _analyze_dates(
            self,
            date_values: list[tuple[int, str]],
            max_samples: int,
    ) -> DateDetectionResult:
        """
        Analyze date values to determine the format.

        For each date, tries parsing with ISO, US, and EU formats.
        Tracks which formats remain viable across all dates.

        Args:
            date_values: List of (row_number, raw_date) tuples
            max_samples: Maximum samples to include in result

        Returns:
            DateDetectionResult with detection status and samples
        """
        # Track viable formats
        iso_viable = True
        us_viable = True
        eu_viable = True

        # Build interpretations for all dates
        interpretations: list[DateInterpretation] = []
        disambiguators: list[DateInterpretation] = []

        for row_num, raw_date in date_values:
            interpretation = self._interpret_date(row_num, raw_date)
            interpretations.append(interpretation)

            # Update viability based on this date
            if interpretation.iso_interpretation is None:
                iso_viable = False
            if interpretation.us_interpretation is None:
                us_viable = False
            if interpretation.eu_interpretation is None:
                eu_viable = False

            # Track disambiguators
            if interpretation.is_disambiguator:
                disambiguators.append(interpretation)

        # Determine result based on viable formats
        viable_formats = []
        if iso_viable:
            viable_formats.append(DateFormat.ISO)
        if us_viable:
            viable_formats.append(DateFormat.US)
        if eu_viable:
            viable_formats.append(DateFormat.EU)

        # Select samples: prefer disambiguators, then first few dates
        samples = []
        seen_rows = set()

        # Add disambiguators first
        for interp in disambiguators[:max_samples]:
            if interp.row_number not in seen_rows:
                samples.append(interp)
                seen_rows.add(interp.row_number)

        # Fill with other dates if needed
        for interp in interpretations:
            if len(samples) >= max_samples:
                break
            if interp.row_number not in seen_rows:
                samples.append(interp)
                seen_rows.add(interp.row_number)

        # Sort samples by row number
        samples.sort(key=lambda x: x.row_number)

        # Build result
        if len(viable_formats) == 0:
            return DateDetectionResult(
                status=DateDetectionStatus.ERROR,
                samples=samples,
                reason="No valid date format found. Dates could not be parsed "
                       "as ISO (YYYY-MM-DD), US (M/D/YYYY), or EU (D/M/YYYY).",
            )
        elif len(viable_formats) == 1:
            detected = viable_formats[0]
            format_names = {
                DateFormat.ISO: "ISO (YYYY-MM-DD)",
                DateFormat.US: "US (M/D/YYYY)",
                DateFormat.EU: "EU (D/M/YYYY)",
            }
            return DateDetectionResult(
                status=DateDetectionStatus.UNAMBIGUOUS,
                detected_format=detected,
                samples=samples,
                reason=f"Detected {format_names[detected]} format.",
            )
        else:
            format_names = []
            if DateFormat.ISO in viable_formats:
                format_names.append("ISO")
            if DateFormat.US in viable_formats:
                format_names.append("US")
            if DateFormat.EU in viable_formats:
                format_names.append("EU")
            return DateDetectionResult(
                status=DateDetectionStatus.AMBIGUOUS,
                samples=samples,
                reason=f"Dates are ambiguous between {' and '.join(format_names)} formats. "
                       "All date values have day and month <= 12.",
            )

    def _interpret_date(
            self,
            row_number: int,
            raw_date: str,
    ) -> DateInterpretation:
        """
        Try to interpret a date value under all formats.

        Args:
            row_number: Row where date appears
            raw_date: Raw date string

        Returns:
            DateInterpretation showing how date parses under each format
        """
        interpretation = DateInterpretation(
            raw_value=raw_date,
            row_number=row_number,
        )

        # Try ISO format
        iso_result = self._try_parse_date(raw_date, DateFormat.ISO)
        if iso_result:
            interpretation.iso_interpretation = iso_result

        # Try US format
        us_result = self._try_parse_date(raw_date, DateFormat.US)
        if us_result:
            interpretation.us_interpretation = us_result

        # Try EU format
        eu_result = self._try_parse_date(raw_date, DateFormat.EU)
        if eu_result:
            interpretation.eu_interpretation = eu_result

        # Determine if this date is a disambiguator
        # A date disambiguates if it eliminates at least one format
        valid_count = sum([
            bool(iso_result),
            bool(us_result),
            bool(eu_result),
        ])

        # If exactly one format works, or if US and EU differ (one is None),
        # this date helps disambiguate
        if valid_count == 1:
            interpretation.is_disambiguator = True
        elif us_result and eu_result and us_result != eu_result:
            # Both parse but give different dates - check if one has day > 12
            # which would make it invalid for the other format
            interpretation.is_disambiguator = self._has_day_over_12(raw_date)
        elif (us_result and not eu_result) or (eu_result and not us_result):
            interpretation.is_disambiguator = True

        return interpretation

    def _try_parse_date(self, value: str, date_format: DateFormat) -> str | None:
        """
        Try to parse a date with the specified format.

        Args:
            value: Raw date string
            date_format: Format to try

        Returns:
            ISO format date string if successful, None otherwise
        """
        value = value.strip()
        patterns = self.DATE_FORMAT_PATTERNS.get(date_format, [])

        for fmt in patterns:
            try:
                dt = datetime.strptime(value, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        # Also try ISO format with time component (always accepted)
        if date_format == DateFormat.ISO:
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                pass

        return None

    def _has_day_over_12(self, raw_date: str) -> bool:
        """
        Check if a date string contains a component > 12.

        This indicates that the date cannot be both US and EU format,
        as one of month/day must be > 12.

        Args:
            raw_date: Raw date string

        Returns:
            True if any numeric component > 12
        """
        import re
        # Extract numeric components
        components = re.findall(r'\d+', raw_date)
        for comp in components:
            val = int(comp)
            if 12 < val <= 31:
                return True
        return False

    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================

    def _read_file_content(self, file: BinaryIO) -> str:
        """
        Read and decode file content, handling different encodings.
        
        Tries UTF-8 first, falls back to Latin-1.
        """
        raw_content = file.read()

        # Try UTF-8 first
        try:
            return raw_content.decode("utf-8")
        except UnicodeDecodeError:
            pass

        # Try UTF-8 with BOM
        try:
            return raw_content.decode("utf-8-sig")
        except UnicodeDecodeError:
            pass

        # Fall back to Latin-1 (never fails, but may produce garbage)
        logger.warning("File is not UTF-8, falling back to Latin-1 encoding")
        return raw_content.decode("latin-1")

    def _build_column_map(
            self,
            headers: list[str]
    ) -> dict[str, str]:
        """
        Build mapping from internal field names to actual CSV column names.
        
        Args:
            headers: List of column headers from CSV file
            
        Returns:
            Dict mapping internal field -> CSV column name
        """
        column_map: dict[str, str] = {}
        normalized_headers = {h.lower().strip(): h for h in headers}

        for internal_field, possible_names in self.COLUMN_MAPPING.items():
            for name in possible_names:
                if name.lower() in normalized_headers:
                    column_map[internal_field] = normalized_headers[name.lower()]
                    break

        return column_map

    def _get_missing_columns(
            self,
            column_map: dict[str, str]
    ) -> list[str]:
        """
        Check which required fields are missing from the column map.
        
        Args:
            column_map: Current column mapping
            
        Returns:
            List of missing required field names
        """
        missing = []
        for field in self.REQUIRED_FIELDS:
            if field not in column_map:
                missing.append(field)
        return missing

    def _parse_row(
            self,
            row_number: int,
            row: dict[str, str],
            column_map: dict[str, str],
            date_format: DateFormat,
    ) -> tuple[ParsedTransactionRow | None, ParseError | None]:
        """
        Parse a single CSV row into a ParsedTransactionRow.
        
        Args:
            row_number: 1-based row number
            row: CSV row as dictionary
            column_map: Mapping from internal fields to CSV columns
            date_format: User-specified date format
            
        Returns:
            Tuple of (parsed_row, error) - one will be None
        """
        raw_data = dict(row)

        try:
            # Extract values using column map
            values: dict[str, str] = {}
            for internal_field, csv_column in column_map.items():
                value = row.get(csv_column, "").strip()
                values[internal_field] = value

            # Validate required fields are not empty
            for field in self.REQUIRED_FIELDS:
                if not values.get(field):
                    return None, ParseError(
                        row_number=row_number,
                        error_type="missing_value",
                        message=f"Missing required value for '{field}'",
                        field=field,
                        raw_data=raw_data,
                    )

            # Normalize transaction type
            transaction_type = self._normalize_transaction_type(
                values["transaction_type"]
            )
            if not transaction_type:
                return None, ParseError(
                    row_number=row_number,
                    error_type="invalid_transaction_type",
                    message=f"Invalid transaction type: '{values['transaction_type']}'. "
                            f"Expected: BUY or SELL",
                    field="transaction_type",
                    raw_data=raw_data,
                )

            # Parse and convert date to ISO format
            parsed_date = self._parse_date(values["date"], date_format)
            if not parsed_date:
                format_examples = {
                    DateFormat.ISO: "YYYY-MM-DD (e.g., 2021-01-22)",
                    DateFormat.US: "M/D/YYYY (e.g., 1/22/2021)",
                    DateFormat.EU: "D/M/YYYY (e.g., 22/01/2021)",
                }
                return None, ParseError(
                    row_number=row_number,
                    error_type="invalid_date",
                    message=f"Invalid date: '{values['date']}'. "
                            f"Expected format: {format_examples[date_format]}",
                    field="date",
                    raw_data=raw_data,
                )

            # Build parsed row
            parsed_row = ParsedTransactionRow(
                row_number=row_number,
                date=parsed_date,
                transaction_type=transaction_type,
                ticker=values["ticker"].upper(),
                exchange=values["exchange"].upper(),
                quantity=values["quantity"],
                price_per_share=values["price_per_share"],
                currency=values["currency"].upper(),
                fee=values.get("fee", "0") or "0",
                fee_currency=values.get("fee_currency", "").upper() or None,
                exchange_rate=values.get("exchange_rate") or None,
                raw_data=raw_data,
            )

            return parsed_row, None

        except Exception as e:
            logger.warning(f"Unexpected error parsing row {row_number}: {e}", exc_info=True)
            return None, ParseError(
                row_number=row_number,
                error_type="parse_error",
                message=f"Failed to parse row: {e}",
                raw_data=raw_data,
            )

    def _normalize_transaction_type(self, value: str) -> str | None:
        """
        Normalize transaction type to BUY or SELL.
        
        Args:
            value: Raw transaction type from CSV
            
        Returns:
            "BUY", "SELL", or None if invalid
        """
        normalized = value.lower().strip()
        return self.TYPE_MAPPING.get(normalized)

    def _parse_date(self, value: str, date_format: DateFormat) -> str | None:
        """
        Parse date string using the specified format and return ISO format.
        
        Only tries patterns matching the user's declared format.
        This eliminates ambiguity between formats like M/D/YYYY and D/M/YYYY.
        
        Args:
            value: Raw date string from CSV
            date_format: User-specified date format
            
        Returns:
            ISO format date string (YYYY-MM-DDTHH:MM:SSZ) or None if invalid
        """
        value = value.strip()

        # Get patterns for the specified format
        patterns = self.DATE_FORMAT_PATTERNS.get(date_format, [])

        for fmt in patterns:
            try:
                dt = datetime.strptime(value, fmt)
                # Return ISO format with UTC timezone
                return dt.strftime("%Y-%m-%dT00:00:00Z")
            except ValueError:
                continue

        # Also try ISO format with time component (always accepted as fallback)
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass

        return None
