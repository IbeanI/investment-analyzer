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

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.upload import (
    UploadResponse,
    UploadErrorResponse,
    SupportedFormatsResponse,
)
from app.services.upload import (
    UploadService,
    DateFormat,
    get_supported_extensions,
    get_supported_content_types,
)
from app.schemas.upload import UploadResponse, UploadErrorResponse

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
# ENDPOINTS
# =============================================================================

@router.get(
    "/formats",
    response_model=SupportedFormatsResponse,
    summary="List supported file formats",
    response_description="Supported file formats for upload"
)
def get_supported_formats() -> SupportedFormatsResponse:
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
        404: {
            "description": "Portfolio not found",
        },
    },
)
def upload_transactions(
        file: UploadFile = File(
            ...,
            description="Transaction file to upload (CSV, JSON, or Excel)"
        ),
        portfolio_id: int = Query(
            ...,
            gt=0,
            description="ID of the target portfolio"
        ),
        date_format: DateFormat = Query(
            default=DateFormat.ISO,
            description=(
                    "Date format used in the file. "
                    "ISO: YYYY-MM-DD (default), "
                    "US: M/D/YYYY (American), "
                    "EU: D/M/YYYY (European)"
            )
        ),
        db: Session = Depends(get_db),
        upload_service: UploadService = Depends(get_upload_service),
) -> UploadResponse | JSONResponse:
    """
    Upload transactions from a file.
    
    **Supported formats:** CSV (more coming soon)
    
    **Date Format Parameter:**
    
    You MUST specify the date format used in your file to avoid ambiguity:
    
    | Format | Pattern | Example |
    |--------|---------|---------|
    | `ISO` (default) | YYYY-MM-DD | 2021-01-22 |
    | `US` | M/D/YYYY | 1/22/2021 |
    | `EU` | D/M/YYYY | 22/01/2021 |
    
    **Why is this required?**
    
    The date "1/2/2021" is ambiguous:
    - US format: January 2, 2021
    - EU format: February 1, 2021
    
    For financial data, we cannot guess - you must be explicit.
    
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
    """
    logger.info(
        f"Upload request: {file.filename} -> portfolio {portfolio_id} "
        f"(date_format={date_format.value})"
    )

    # Process the file
    result = upload_service.process_file(
        db=db,
        file=file.file,
        filename=file.filename or "unknown",
        portfolio_id=portfolio_id,
        content_type=file.content_type,
        date_format=date_format,
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
    else:
        logger.warning(
            f"Upload failed: {result.error_count} errors"
        )

    # Return appropriate status code
    # Note: We return 200 even on validation failures because the request
    # itself was valid - the response body indicates success/failure
    return response
