# backend/app/schemas/errors.py
"""
Pydantic schemas for error responses.

These schemas provide a consistent error format across all API endpoints.
Used by global exception handlers in main.py.
"""

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """
    Standard error response format.

    Provides consistent structure for all API errors, making it easier
    for frontend clients to parse and display error messages.
    """

    error: str = Field(
        ...,
        description="Error type/code (e.g., 'AssetNotFoundError')"
    )
    message: str = Field(
        ...,
        description="Human-readable error message"
    )
    details: dict | None = Field(
        default=None,
        description="Additional error context (optional)"
    )


class ValidationErrorDetail(BaseModel):
    """
    Validation error response format.

    Used for Pydantic validation errors (422 responses).
    """

    error: str = Field(default="ValidationError")
    message: str = Field(default="Request validation failed")
    details: list[dict] = Field(
        ...,
        description="List of validation errors"
    )
