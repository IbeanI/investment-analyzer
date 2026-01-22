# backend/app/schemas/upload.py
"""
Pydantic schemas for file upload operations.

These schemas define the API response format for upload endpoints.
"""

from pydantic import BaseModel, Field


# =============================================================================
# ERROR SCHEMAS
# =============================================================================

class UploadErrorResponse(BaseModel):
    """
    Details about a single error during upload processing.
    
    Provides context for debugging and user feedback.
    """

    row_number: int = Field(
        ...,
        description="Row number where error occurred (0 for file-level errors)"
    )
    stage: str = Field(
        ...,
        description="Processing stage: parsing, validation, asset_resolution, persistence"
    )
    error_type: str = Field(
        ...,
        description="Error category for programmatic handling"
    )
    message: str = Field(
        ...,
        description="Human-readable error description"
    )
    field: str | None = Field(
        default=None,
        description="Specific field that caused the error"
    )


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================

class UploadResponse(BaseModel):
    """
    Response schema for file upload operations.
    
    Provides detailed feedback on the upload result.
    """

    success: bool = Field(
        ...,
        description="True if all rows were processed successfully"
    )
    filename: str = Field(
        ...,
        description="Original filename"
    )
    total_rows: int = Field(
        ...,
        description="Total number of data rows in file"
    )
    created_count: int = Field(
        ...,
        description="Number of transactions created"
    )
    error_count: int = Field(
        ...,
        description="Number of rows with errors"
    )
    errors: list[UploadErrorResponse] = Field(
        default_factory=list,
        description="Detailed error information"
    )

    warnings: list[UploadErrorResponse] = Field(
        default_factory=list,
        description="Non-blocking warnings (e.g. asset exchange mismatches)"
    )

    created_transaction_ids: list[int] = Field(
        default_factory=list,
        description="IDs of created transactions"
    )


class SupportedFormatsResponse(BaseModel):
    """
    Response schema listing supported file formats.
    """

    extensions: list[str] = Field(
        ...,
        description="Supported file extensions (e.g., ['.csv', '.json'])"
    )
    content_types: list[str] = Field(
        ...,
        description="Supported MIME types"
    )


# =============================================================================
# DATE DETECTION SCHEMAS
# =============================================================================

class DateSampleResponse(BaseModel):
    """
    Shows how a date value would be interpreted under different formats.
    """
    raw_value: str = Field(
        ...,
        description="Original date string from the file"
    )
    row_number: int = Field(
        ...,
        description="Row number where this date appears"
    )
    us_interpretation: str | None = Field(
        default=None,
        description="Date as YYYY-MM-DD if valid under US format (M/D/Y)"
    )
    eu_interpretation: str | None = Field(
        default=None,
        description="Date as YYYY-MM-DD if valid under EU format (D/M/Y)"
    )
    iso_interpretation: str | None = Field(
        default=None,
        description="Date as YYYY-MM-DD if valid under ISO format (Y-M-D)"
    )
    is_disambiguator: bool = Field(
        default=False,
        description="True if this date proves a specific format"
    )


class DateDetectionResponse(BaseModel):
    """
    Result of automatic date format detection.

    Returned with 422 status when date format is ambiguous.
    """
    status: str = Field(
        ...,
        description="Detection status: 'unambiguous', 'ambiguous', or 'error'"
    )
    detected_format: str | None = Field(
        default=None,
        description="Detected format if unambiguous: 'ISO', 'US', or 'EU'"
    )
    samples: list[DateSampleResponse] = Field(
        default_factory=list,
        description="Sample dates showing how they would be interpreted"
    )
    reason: str = Field(
        default="",
        description="Human-readable explanation of the result"
    )


class AmbiguousDateFormatError(BaseModel):
    """
    Error response when date format cannot be auto-detected.

    Client should display the samples to the user and let them choose.
    """
    error: str = Field(
        default="ambiguous_date_format",
        description="Error code for client handling"
    )
    message: str = Field(
        default="Could not automatically determine date format",
        description="Human-readable error message"
    )
    detection: DateDetectionResponse = Field(
        ...,
        description="Detection result with sample interpretations"
    )
