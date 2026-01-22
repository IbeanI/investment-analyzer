# backend/app/routers/upload.py
"""
File upload endpoints.

Provides endpoints for uploading transaction data from files.
Supports multiple file formats (CSV now, JSON/Excel in future).

Key features:
- Multi-format support via parser abstraction
- Explicit date format specification (no ambiguity)
- Batch asset resolution (efficient Yahoo API usage)
- Atomic transaction creation (all or nothing)
- Detailed error reporting per row
"""

import logging

from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Portfolio
from app.schemas.upload import (
    UploadResponse,
    UploadErrorResponse,
    SupportedFormatsResponse,
    DateSampleResponse,
    DateDetectionResponse,
    AmbiguousDateFormatError,
)
from app.dependencies import get_current_user, get_portfolio_with_owner_check
from app.services.upload import (
    UploadService,
    DateFormat,
    get_supported_extensions,
    get_supported_content_types,
)
from app.services.upload.parsers import (
    get_parser,
    DateDetectionStatus,
)
from app.services.analytics.service import AnalyticsService
from app.services.constants import MAX_UPLOAD_FILE_SIZE_BYTES
from app.schemas.upload import UploadResponse, UploadErrorResponse
from app.dependencies import get_analytics_service
from app.middleware.rate_limit import limiter, RATE_LIMIT_UPLOAD, RATE_LIMIT_DEFAULT

logger = logging.getLogger(__name__)

# =============================================================================
# ROUTER SETUP
# =============================================================================

router = APIRouter(
    prefix="/upload",
    tags=["Upload"],
)


# =============================================================================
# DEPENDENCIES
# =============================================================================

def get_upload_service() -> UploadService:
    """Dependency that provides the upload service."""
    return UploadService()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def validate_portfolio_ownership(
    db: Session,
    portfolio_id: int,
    current_user: User
) -> Portfolio:
    """
    Validate that the portfolio exists and belongs to the current user.

    Args:
        db: Database session
        portfolio_id: Portfolio ID to validate
        current_user: Authenticated user

    Returns:
        Portfolio if valid

    Raises:
        HTTPException: 404 if portfolio not found, 403 if user doesn't own it
    """
    portfolio = db.get(Portfolio, portfolio_id)
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio with id {portfolio_id} not found"
        )
    if portfolio.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this portfolio"
        )
    return portfolio


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get(
    "/formats",
    response_model=SupportedFormatsResponse,
    summary="List supported file formats",
    response_description="Supported file formats for upload"
)
@limiter.limit(RATE_LIMIT_DEFAULT)
def get_supported_formats(request: Request) -> SupportedFormatsResponse:
    """
    Get list of supported file formats for upload.
    
    Use this endpoint to check which file types are accepted
    before attempting an upload.
    """
    return SupportedFormatsResponse(
        extensions=get_supported_extensions(),
        content_types=get_supported_content_types(),
    )


@router.post(
    "/transactions",
    response_model=UploadResponse,
    summary="Upload transactions from file",
    response_description="Upload result with details",
    responses={
        200: {
            "description": "Upload processed (check 'success' field for result)",
            "model": UploadResponse,
        },
        400: {
            "description": "Invalid request (missing file or portfolio_id)",
        },
        401: {
            "description": "Not authenticated",
        },
        403: {
            "description": "Not authorized to access this portfolio",
        },
        404: {
            "description": "Portfolio not found",
        },
        422: {
            "description": "Ambiguous date format - user must specify",
            "model": AmbiguousDateFormatError,
        },
    },
)
@limiter.limit(RATE_LIMIT_UPLOAD)
def upload_transactions(
        request: Request,  # Required for rate limiting
        file: UploadFile = File(
            ...,
            description="Transaction file to upload (CSV, JSON, or Excel)"
        ),
        portfolio_id: int = Query(
            ...,
            gt=0,
            description="ID of the target portfolio"
        ),
        date_format: Literal["ISO", "US", "EU", "AUTO"] = Query(
            default="AUTO",
            description=(
                    "Date format used in the file. "
                    "AUTO: Auto-detect (default), "
                    "ISO: YYYY-MM-DD, "
                    "US: M/D/YYYY (American), "
                    "EU: D/M/YYYY (European)"
            )
        ),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
        upload_service: UploadService = Depends(get_upload_service),
        analytics_service: AnalyticsService = Depends(get_analytics_service),
) -> UploadResponse | JSONResponse:
    """
    Upload transactions from a file.

    **Supported formats:** CSV (more coming soon)

    **Date Format Parameter:**

    By default, the date format is auto-detected. You can also specify explicitly:

    | Format | Pattern | Example |
    |--------|---------|---------|
    | `AUTO` (default) | Auto-detect | Analyzes dates to determine format |
    | `ISO` | YYYY-MM-DD | 2021-01-22 |
    | `US` | M/D/YYYY | 1/22/2021 |
    | `EU` | D/M/YYYY | 22/01/2021 |

    **Auto-Detection Behavior:**

    - If dates are **unambiguous** (e.g., `1/22/2021` where day=22 > 12),
      the format is detected automatically and upload proceeds.
    - If dates are **ambiguous** (e.g., all dates have day ≤ 12 like `1/2/2021`),
      returns 422 with sample interpretations for the user to choose.

    **Why auto-detect?**

    The date "1/2/2021" is ambiguous:
    - US format: January 2, 2021
    - EU format: February 1, 2021

    But "1/22/2021" is unambiguous (US format only, since month can't be 22).
    
    **CSV Format:**
    ```
    date,action,ticker,reference_exchange,quantity,price,price_currency,fee,fee_currency
    1/22/2021,Buy,VWRL,AEB,1.0000,90.14,EUR,0.00,EUR
    ```
    
    **Required columns:**
    - `date`: Transaction date (in the format specified by date_format)
    - `action`: BUY or SELL
    - `ticker`: Asset ticker symbol
    - `reference_exchange`: Exchange code (e.g., AEB, XETRA, NASDAQ)
    - `quantity`: Number of shares
    - `price`: Price per share
    - `price_currency`: Currency code (EUR, USD, etc.)
    
    **Optional columns:**
    - `fee`: Transaction fee (default: 0)
    - `fee_currency`: Fee currency (default: same as price_currency)
    - `exchange_rate`: FX rate to portfolio currency (default: 1)
    
    **Behavior:**
    - **Asset Resolution:** Unknown tickers are automatically looked up on 
      Yahoo Finance and added to the database.
    - **Atomic:** If ANY row fails validation, NO transactions are created.
    - **Detailed Errors:** Each failure includes row number, field, and message.
    
    **Example requests:**
    
    ```bash
    # US date format (M/D/YYYY)
    curl -X POST "http://localhost:8000/upload/transactions?portfolio_id=1&date_format=US" \\
      -F "file=@transactions.csv"
    
    # European date format (D/M/YYYY)
    curl -X POST "http://localhost:8000/upload/transactions?portfolio_id=1&date_format=EU" \\
      -F "file=@transactions.csv"
    
    # ISO date format (default)
    curl -X POST "http://localhost:8000/upload/transactions?portfolio_id=1" \\
      -F "file=@transactions.csv"
    ```
    
    **Example response (success):**
    ```json
    {
        "success": true,
        "filename": "transactions.csv",
        "total_rows": 50,
        "created_count": 50,
        "error_count": 0,
        "errors": [],
        "created_transaction_ids": [1, 2, 3, ...]
    }
    ```
    
    **Example response (date format error):**
    ```json
    {
        "success": false,
        "filename": "transactions.csv",
        "total_rows": 50,
        "created_count": 0,
        "error_count": 1,
        "errors": [
            {
                "row_number": 2,
                "stage": "parsing",
                "error_type": "invalid_date",
                "message": "Invalid date: '22/01/2021'. Expected format: M/D/YYYY (e.g., 1/22/2021)",
                "field": "date"
            }
        ],
        "created_transaction_ids": []
    }
    ```

    Raises **401** if not authenticated.
    Raises **403** if you don't own the portfolio.
    """
    # Verify user owns the portfolio
    validate_portfolio_ownership(db, portfolio_id, current_user)

    logger.info(
        f"Upload request: {file.filename} -> portfolio {portfolio_id} "
        f"(date_format={date_format})"
    )

    # Validate file size
    # Read the file content to check size (seek back to start for processing)
    file_content = file.file.read()
    file_size = len(file_content)
    file.file.seek(0)  # Reset for processing

    if file_size > MAX_UPLOAD_FILE_SIZE_BYTES:
        max_mb = MAX_UPLOAD_FILE_SIZE_BYTES / (1024 * 1024)
        actual_mb = file_size / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large: {actual_mb:.1f}MB exceeds maximum of {max_mb:.0f}MB"
        )

    logger.debug(f"File size: {file_size} bytes")

    # Handle AUTO date format detection
    resolved_date_format: DateFormat
    if date_format == "AUTO":
        logger.info("Auto-detecting date format")
        try:
            parser = get_parser(file.filename or "unknown", file.content_type)
            detection = parser.detect_date_format(
                file.file,
                file.filename or "unknown",
            )
            file.file.seek(0)  # Reset for parsing

            if detection.status == DateDetectionStatus.ERROR:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=detection.reason,
                )

            if detection.status == DateDetectionStatus.AMBIGUOUS:
                # Return 422 with detection data for user to choose
                logger.info("Date format is ambiguous, requesting user input")
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    content={
                        "error": "ambiguous_date_format",
                        "message": "Could not automatically determine date format. Please select the correct format.",
                        "detection": {
                            "status": detection.status.value,
                            "detected_format": None,
                            "samples": [
                                {
                                    "raw_value": s.raw_value,
                                    "row_number": s.row_number,
                                    "us_interpretation": s.us_interpretation,
                                    "eu_interpretation": s.eu_interpretation,
                                    "iso_interpretation": s.iso_interpretation,
                                    "is_disambiguator": s.is_disambiguator,
                                }
                                for s in detection.samples
                            ],
                            "reason": detection.reason,
                        },
                    },
                )

            # Unambiguous - use detected format
            resolved_date_format = detection.detected_format
            logger.info(f"Auto-detected date format: {resolved_date_format.value}")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Date format detection failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to detect date format: {e}",
            )
    else:
        resolved_date_format = DateFormat(date_format)

    # Process the file
    result = upload_service.process_file(
        db=db,
        file=file.file,
        filename=file.filename or "unknown",
        portfolio_id=portfolio_id,
        content_type=file.content_type,
        date_format=resolved_date_format,
    )

    # Build response
    response = UploadResponse(
        success=result.success,
        filename=result.filename,
        total_rows=result.total_rows,
        created_count=result.created_count,
        error_count=result.error_count,
        errors=[
            UploadErrorResponse(
                row_number=e.row_number,
                stage=e.stage,
                error_type=e.error_type,
                message=e.message,
                field=e.field,
            )
            for e in result.errors
        ],

        warnings=[
            UploadErrorResponse(
                row_number=w.row_number,
                stage=w.stage,
                error_type=w.error_type,
                message=w.message,
                field=w.field
            ) for w in result.warnings
        ],

        created_transaction_ids=result.created_transaction_ids,
    )

    # Log result
    if result.success:
        logger.info(
            f"Upload successful: {result.created_count} transactions created"
        )
        # Invalidate analytics cache after successful upload
        analytics_service.invalidate_cache(portfolio_id)
    else:
        logger.warning(
            f"Upload failed: {result.error_count} errors"
        )

    # Return appropriate status code
    # Note: We return 200 even on validation failures because the request
    # itself was valid - the response body indicates success/failure
    return response
