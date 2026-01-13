# backend/app/schema/portfolios.py
"""
Pydantic schemas for Portfolio validation.

These schemas define:
- What data clients must send (Create)
- What data clients can update (Update)
- What data the API returns (Response)

Note: Currently user_id is provided in the request body.
When authentication is implemented (Phase 5), user_id will be
extracted from the JWT token instead.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PortfolioBase(BaseModel):
    """
    Base schema with fields common to Create and Response.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        examples=["My Retirement Fund", "Tech Stocks", "ETF Portfolio"],
        description="Name of the portfolio"
    )

    currency: str = Field(
        default="EUR",
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        examples=["EUR", "USD", "GBP"],
        description="Base currency for portfolio valuation (ISO 4217)"
    )


class PortfolioCreate(PortfolioBase):
    """
    Schema for creating a new portfolio.

    Note: user_id is required now but will be removed when
    authentication is implemented — it will come from the JWT token.
    """

    # TODO: Remove when auth is implemented (Phase 5)
    # user_id will come from the authenticated user's token
    user_id: int = Field(
        ...,
        gt=0,
        description="ID of the user who owns this portfolio"
    )


class PortfolioUpdate(BaseModel):
    """
    Schema for updating an existing portfolio.

    All fields are optional — client only sends fields to update.
    Note: user_id cannot be changed (you can't transfer portfolio ownership).
    """

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="New name for the portfolio"
    )

    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="New base currency (changing this affects all valuations)"
    )


class PortfolioResponse(PortfolioBase):
    """
    Schema for API responses.

    Includes all database-generated fields.
    """

    id: int = Field(..., description="Unique identifier")
    user_id: int = Field(..., description="ID of the portfolio owner")
    created_at: datetime = Field(..., description="When the portfolio was created")
    updated_at: datetime = Field(..., description="When the portfolio was last modified")

    model_config = ConfigDict(from_attributes=True)


class PortfolioListResponse(BaseModel):
    """
    Response schema for paginated portfolio list.
    """

    items: list[PortfolioResponse]
    total: int = Field(..., description="Total number of portfolios matching the filters")
    skip: int = Field(..., description="Number of records skipped")
    limit: int = Field(..., description="Maximum number of records returned")
