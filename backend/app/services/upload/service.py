# backend/app/services/upload/service.py
"""
Upload service for processing transaction files.

This service orchestrates the complete upload flow:
1. Parse file using appropriate parser (CSV, JSON, Excel)
2. Validate rows using Pydantic schemas
3. Resolve assets via AssetResolutionService
4. Create transactions atomically

Design Principles:
- Format agnostic: delegates parsing to specialized parsers
- Atomic commits: all transactions saved or none
- Detailed error reporting: every failure is explained
- No HTTP knowledge: raises domain exceptions

Usage:
    from app.services.upload import UploadService, DateFormat

    service = UploadService()
    result = service.process_file(
        db=session,
        file=uploaded_file,
        filename="transactions.csv",
        portfolio_id=1,
        date_format=DateFormat.US,  # For M/D/YYYY dates
    )

    if result.success:
        print(f"Created {result.created_count} transactions")
    else:
        for error in result.errors:
            print(f"Row {error.row_number}: {error.message}")
"""

import dataclasses
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import BinaryIO, Any

from sqlalchemy.orm import Session

from app.models import Transaction, Portfolio, TransactionType
from app.services.asset_resolution import AssetResolutionService, BatchResolutionResult
from app.services.upload.parsers import (
    get_parser,
    ParsedTransactionRow,
    UnsupportedFileTypeError,
    DateFormat,
)

logger = logging.getLogger(__name__)


# =============================================================================
# RESULT DATA CLASSES
# =============================================================================

@dataclass
class UploadError:
    """
    Represents an error during upload processing.

    Attributes:
        row_number: 1-based row number (0 for file-level errors)
        stage: Processing stage where error occurred
        error_type: Category of error
        message: Human-readable error description
        field: Specific field that caused the error (if applicable)
        raw_data: Original row data for context
    """

    row_number: int
    stage: str  # "parsing", "validation", "asset_resolution", "persistence"
    error_type: str
    message: str
    field: str | None = None
    raw_data: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclass
class UploadResult:
    """
    Result of processing an uploaded file.

    Attributes:
        success: True if all rows were processed successfully
        filename: Original filename
        total_rows: Total rows in file
        created_count: Number of transactions created
        skipped_count: Number of rows skipped (duplicates, etc.)
        error_count: Number of rows with errors
        errors: Detailed error information
        created_transaction_ids: IDs of created transactions
    """

    success: bool = False
    filename: str = ""
    total_rows: int = 0
    created_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    errors: list[UploadError] = field(default_factory=list)
    warnings: list[UploadError] = field(default_factory=list)
    created_transaction_ids: list[int] = field(default_factory=list)

    def add_error(
            self,
            row_number: int,
            stage: str,
            error_type: str,
            message: str,
            field: str | None = None,
            raw_data: dict[str, Any] | None = None,
    ) -> None:
        """Add an error to the result."""
        self.errors.append(UploadError(
            row_number=row_number,
            stage=stage,
            error_type=error_type,
            message=message,
            field=field,
            raw_data=raw_data or {},
        ))
        self.error_count += 1

    def add_warning(self, row_number: int, stage: str, error_type: str, message: str, field: str | None = None, raw_data: dict[str, Any] | None = None) -> None:
        self.warnings.append(UploadError(row_number, stage, error_type, message, field, raw_data or {}))


# =============================================================================
# UPLOAD SERVICE
# =============================================================================

class UploadService:
    """
    Service for processing uploaded transaction files.

    This service is FILE FORMAT AGNOSTIC. It:
    1. Delegates parsing to the appropriate parser
    2. Validates rows using Pydantic schemas
    3. Resolves assets via AssetResolutionService
    4. Creates transactions atomically

    The service guarantees atomic behavior:
    - If ANY row fails validation -> NO transactions are created
    - If asset resolution fails -> NO transactions are created
    - If database commit fails -> rollback, NO transactions are created

    Example:
        service = UploadService()

        with open("transactions.csv", "rb") as f:
            result = service.process_file(
                db=session,
                file=f,
                filename="transactions.csv",
                portfolio_id=1,
                date_format=DateFormat.US,
            )

        if result.success:
            print(f"Imported {result.created_count} transactions")
        else:
            for error in result.errors:
                print(f"Error: {error.message}")
    """

    def __init__(
            self,
            asset_service: AssetResolutionService | None = None,
    ) -> None:
        """
        Initialize the upload service.

        Args:
            asset_service: Asset resolution service instance.
                          Defaults to new AssetResolutionService.
        """
        self._asset_service = asset_service or AssetResolutionService()

    def process_file(
            self,
            db: Session,
            file: BinaryIO,
            filename: str,
            portfolio_id: int,
            content_type: str | None = None,
            date_format: DateFormat = DateFormat.ISO,
    ) -> UploadResult:
        """
        Process an uploaded transaction file.

        This is the main entry point. It handles the complete flow:
        1. Validate portfolio exists
        2. Parse file (using specified date format)
        3. Validate all rows
        4. Resolve all assets (batch)
        5. Create all transactions (atomic)

        Args:
            db: Database session
            file: File object to process
            filename: Original filename
            portfolio_id: Target portfolio ID
            content_type: Optional MIME type
            date_format: Date format used in the file (ISO, US, or EU)

        Returns:
            UploadResult with success status and details
        """
        result = UploadResult(filename=filename)
        logger.info(f"Processing upload: {filename} for portfolio {portfolio_id}")

        # 1. Validate Portfolio
        portfolio = db.get(Portfolio, portfolio_id)
        if not portfolio:
            result.add_error(0, "validation", "portfolio_not_found", f"Portfolio {portfolio_id} not found")
            return result

        # 2. Parse File
        try:
            parser = get_parser(filename, content_type)
            parse_result = parser.parse(file, filename, date_format)
        except UnsupportedFileTypeError as e:
            result.add_error(0, "parsing", "unsupported_file_type", str(e))
            return result
        except Exception as e:
            logger.error(f"Parsing error: {e}", exc_info=True)
            result.add_error(0, "parsing", "parse_error", str(e))
            return result

        result.total_rows = parse_result.total_rows
        for error in parse_result.errors:
            result.add_error(error.row_number, "parsing", error.error_type, error.message, error.field, error.raw_data)

        if not parse_result.has_data:
            if not result.errors:
                result.add_error(0, "parsing", "empty_file", "No valid rows found")
            return result

        # 3. Validate Rows
        validated_rows, validation_errors = self._validate_rows(parse_result.rows, portfolio_id)
        for error in validation_errors:
            result.add_error(**error)

        if result.errors:
            return result

        # 4. Resolve Assets (Batch)
        # Note: Asset resolution may create new assets in the database.
        # These assets are global shared entities that persist regardless of
        # whether transaction creation succeeds. This is acceptable because:
        # - Assets are idempotent (ON CONFLICT DO NOTHING)
        # - Orphan assets cause no harm and may be used by future uploads
        # - The critical atomicity requirement is that ALL transactions are
        #   created or NONE, which is handled in step 7
        asset_requests = [(row["ticker"], row["exchange"]) for row in validated_rows]

        try:
            resolution_result = self._asset_service.resolve_assets_batch(db, asset_requests)
        except Exception as e:
            logger.error(f"Resolution failed: {e}", exc_info=True)
            result.add_error(0, "asset_resolution", "resolution_error", str(e))
            return result

        # 5. Build Smart Maps (Exact + Fallback)
        exact_asset_map = {}
        ticker_fallback_map = {}

        # Populate maps from successfully resolved assets
        for key, asset in resolution_result.resolved.items():
            # Map 1: Exact Match (Ticker + Exchange)
            exact_asset_map[key] = asset

            # Map 2: Fallback (Ticker only) - Handle duplicates safely
            if asset.ticker not in ticker_fallback_map:
                ticker_fallback_map[asset.ticker] = []

            # Avoid adding same asset twice
            if asset not in ticker_fallback_map[asset.ticker]:
                ticker_fallback_map[asset.ticker].append(asset)

        # 6. Map Rows to Assets (with Warning Logic)
        transactions_db: list[Transaction] = []

        for row in validated_rows:
            key = (row["ticker"], row["exchange"])
            asset = None

            # A. Try Exact Match
            if key in exact_asset_map:
                asset = exact_asset_map[key]

            # B. Try Smart Fallback
            else:
                candidates = ticker_fallback_map.get(row["ticker"], [])
                if len(candidates) == 1:
                    asset = candidates[0]
                    # 👇 RECORD WARNING (This fixes your issue!)
                    msg = (f"Exchange mismatch: Requested '{row['exchange']}', "
                           f"using '{asset.exchange}' for {row['ticker']}")
                    logger.warning(msg)
                    result.add_warning(
                        row_number=row["row_number"],
                        stage="asset_resolution",
                        error_type="exchange_mismatch",
                        message=msg,
                        field="exchange",
                        raw_data={"requested": row["exchange"], "used": asset.exchange}
                    )
                elif len(candidates) > 1:
                    result.add_error(
                        row["row_number"], "asset_resolution", "ambiguous_asset",
                        f"Ambiguous ticker '{row['ticker']}': Found multiple matches {[a.exchange for a in candidates]}",
                        field="ticker"
                    )
                    continue
                else:
                    # Not found in fallback either -> Check specific resolution errors
                    if key in resolution_result.deactivated:
                        result.add_error(row["row_number"], "asset_resolution", "asset_deactivated",
                                         f"Asset '{row['ticker']}' is deactivated", field="ticker")
                    elif key in resolution_result.not_found:
                        result.add_error(row["row_number"], "asset_resolution", "asset_not_found",
                                         f"Asset '{row['ticker']}' on '{row['exchange']}' not found", field="ticker")
                    elif key in resolution_result.errors:
                        result.add_error(row["row_number"], "asset_resolution", "resolution_error",
                                         str(resolution_result.errors[key]), field="ticker")
                    else:
                        result.add_error(row["row_number"], "asset_resolution", "asset_not_found",
                                         "Asset not resolved", field="ticker")
                    continue

            # Create Transaction Object
            txn = Transaction(
                portfolio_id=portfolio_id,
                asset_id=asset.id,
                transaction_type=row["transaction_type"],
                date=row["date"],
                quantity=row["quantity"],
                price_per_share=row["price_per_share"],
                currency=row["currency"],
                fee=row["fee"],
                fee_currency=row["fee_currency"],
                exchange_rate=row["exchange_rate"],
            )
            transactions_db.append(txn)

        # 7. Atomic Commit (Only if no blocking errors)
        if result.error_count == 0:
            try:
                db.add_all(transactions_db)
                db.commit()
                for txn in transactions_db:
                    db.refresh(txn)

                result.success = True
                result.created_count = len(transactions_db)
                result.created_transaction_ids = [t.id for t in transactions_db]
                logger.info(f"Upload complete. Created: {result.created_count}, Warnings: {len(result.warnings)}")
            except Exception as e:
                db.rollback()
                logger.error(f"Save failed: {e}", exc_info=True)
                result.add_error(0, "persistence", "database_error", str(e))

        return result

    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================

    def _validate_rows(
            self,
            parsed_rows: list[ParsedTransactionRow],
            portfolio_id: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Validate parsed rows and convert to transaction data.

        Args:
            parsed_rows: Rows from parser
            portfolio_id: Target portfolio ID

        Returns:
            Tuple of (validated_rows, errors)
        """
        validated: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for row in parsed_rows:
            try:
                # Convert string values to proper types
                validated_row = {
                    "row_number": row.row_number,
                    "portfolio_id": portfolio_id,
                    "ticker": row.ticker,
                    "exchange": row.exchange,
                    "transaction_type": TransactionType(row.transaction_type),
                    "date": datetime.fromisoformat(
                        row.date.replace("Z", "+00:00")
                    ),
                    "quantity": Decimal(row.quantity),
                    "price_per_share": Decimal(row.price_per_share),
                    "currency": row.currency,
                    "fee": Decimal(row.fee) if row.fee else Decimal("0"),
                    "fee_currency": row.fee_currency or row.currency,
                    "exchange_rate": (
                        Decimal(row.exchange_rate)
                        if row.exchange_rate
                        else Decimal("1")
                    ),
                }

                # Validate date not in future
                if validated_row["date"] > datetime.now(timezone.utc):
                    errors.append({
                        "row_number": row.row_number,
                        "stage": "validation",
                        "error_type": "invalid_date",
                        "message": "Transaction date cannot be in the future",
                        "field": "date",
                        "raw_data": row.raw_data,
                    })
                    continue

                # Validate positive amounts
                if validated_row["quantity"] <= 0:
                    errors.append({
                        "row_number": row.row_number,
                        "stage": "validation",
                        "error_type": "invalid_quantity",
                        "message": "Quantity must be positive",
                        "field": "quantity",
                        "raw_data": row.raw_data,
                    })
                    continue

                if validated_row["price_per_share"] <= 0:
                    errors.append({
                        "row_number": row.row_number,
                        "stage": "validation",
                        "error_type": "invalid_price",
                        "message": "Price must be positive",
                        "field": "price_per_share",
                        "raw_data": row.raw_data,
                    })
                    continue

                if validated_row["fee"] < 0:
                    errors.append({
                        "row_number": row.row_number,
                        "stage": "validation",
                        "error_type": "invalid_fee",
                        "message": "Fee cannot be negative",
                        "field": "fee",
                        "raw_data": row.raw_data,
                    })
                    continue

                validated.append(validated_row)

            except InvalidOperation as e:
                errors.append({
                    "row_number": row.row_number,
                    "stage": "validation",
                    "error_type": "invalid_number",
                    "message": f"Invalid numeric value: {e}",
                    "raw_data": row.raw_data,
                })

            except ValueError as e:
                errors.append({
                    "row_number": row.row_number,
                    "stage": "validation",
                    "error_type": "invalid_value",
                    "message": str(e),
                    "raw_data": row.raw_data,
                })

        return validated, errors

    def _add_resolution_errors(
            self,
            result: UploadResult,
            resolution: BatchResolutionResult,
            validated_rows: list[dict[str, Any]],
    ) -> None:
        """Add asset resolution errors to upload result."""

        # Build index for row lookup
        row_index: dict[tuple[str, str], int] = {}
        for row in validated_rows:
            key = (row["ticker"], row["exchange"])
            if key not in row_index:
                row_index[key] = row["row_number"]

        # Add deactivated errors
        for ticker, exchange in resolution.deactivated:
            row_num = row_index.get((ticker, exchange), 0)
            result.add_error(
                row_number=row_num,
                stage="asset_resolution",
                error_type="asset_deactivated",
                message=f"Asset '{ticker}' on '{exchange}' is deactivated",
                field="ticker",
            )

        # Add not found errors
        for ticker, exchange in resolution.not_found:
            row_num = row_index.get((ticker, exchange), 0)
            result.add_error(
                row_number=row_num,
                stage="asset_resolution",
                error_type="asset_not_found",
                message=(
                    f"Asset '{ticker}' on '{exchange}' not found. "
                    f"Please verify the ticker and exchange are correct."
                ),
                field="ticker",
            )

        # Add other errors
        for (ticker, exchange), exc in resolution.errors.items():
            row_num = row_index.get((ticker, exchange), 0)
            result.add_error(
                row_number=row_num,
                stage="asset_resolution",
                error_type="resolution_error",
                message=f"Error resolving '{ticker}' on '{exchange}': {exc}",
                field="ticker",
            )

    def _create_transactions(
            self,
            db: Session,
            validated_rows: list[dict[str, Any]],
            resolved_assets: dict[tuple[str, str], Any],
            portfolio_id: int,
    ) -> list[int]:
        """
        Create transactions in the database.

        Args:
            db: Database session
            validated_rows: Validated transaction data
            resolved_assets: Map of (ticker, exchange) -> Asset
            portfolio_id: Target portfolio ID

        Returns:
            List of created transaction IDs
        """
        transactions: list[Transaction] = []

        for row in validated_rows:
            key = (row["ticker"], row["exchange"])
            asset = resolved_assets[key]

            txn = Transaction(
                portfolio_id=portfolio_id,
                asset_id=asset.id,
                transaction_type=row["transaction_type"],
                date=row["date"],
                quantity=row["quantity"],
                price_per_share=row["price_per_share"],
                currency=row["currency"],
                fee=row["fee"],
                fee_currency=row["fee_currency"],
                exchange_rate=row["exchange_rate"],
            )
            transactions.append(txn)

        # Atomic commit
        db.add_all(transactions)
        db.commit()

        # Refresh to get IDs
        for txn in transactions:
            db.refresh(txn)

        return [txn.id for txn in transactions]
