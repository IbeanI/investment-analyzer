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
