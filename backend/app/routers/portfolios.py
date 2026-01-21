# backend/app/routers/portfolios.py
"""
Portfolio management endpoints.

Provides CRUD operations for user portfolios.
Each portfolio belongs to a single user and contains transactions.

All endpoints require authentication. Users can only access their own portfolios.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import AfterValidator
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Portfolio, User
from app.schemas.pagination import PaginationMeta
from app.schemas.portfolios import (
    PortfolioCreate,
    PortfolioUpdate,
    PortfolioResponse,
    PortfolioListResponse,
)
from app.schemas.validators import validate_currency_query
from app.dependencies import get_current_user, get_portfolio_with_owner_check

# Validated query parameter type
CurrencyQuery = Annotated[str | None, AfterValidator(validate_currency_query)]

# =============================================================================
# ROUTER SETUP
# =============================================================================

router = APIRouter(
    prefix="/portfolios",
    tags=["Portfolios"],
)


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post(
    "/",
    response_model=PortfolioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new portfolio",
    response_description="The created portfolio"
)
def create_portfolio(
        portfolio: PortfolioCreate,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(get_current_user)],
) -> Portfolio:
    """
    Create a new portfolio for the authenticated user.

    - **name**: Display name for the portfolio
    - **currency**: Base currency for valuations (EUR, USD, etc.)

    A user can have multiple portfolios (e.g., "Retirement", "Trading").
    """
    # Create the portfolio with user_id from JWT
    db_portfolio = Portfolio(
        name=portfolio.name,
        currency=portfolio.currency,
        user_id=current_user.id,
    )

    db.add(db_portfolio)
    db.commit()
    db.refresh(db_portfolio)

    return db_portfolio


@router.get(
    "/",
    response_model=PortfolioListResponse,
    summary="List portfolios",
    response_description="List of portfolios matching the filters"
)
def list_portfolios(
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(get_current_user)],
        # Filters
        currency: CurrencyQuery = Query(
            default=None,
            description="Filter by base currency (ISO 4217, e.g., EUR, USD)"
        ),
        search: str | None = Query(
            default=None,
            max_length=100,
            description="Search in portfolio name"
        ),
        # Pagination
        skip: int = Query(default=0, ge=0, description="Number of records to skip"),
        limit: int = Query(default=100, ge=1, le=1000, description="Maximum records to return"),
) -> PortfolioListResponse:
    """
    Retrieve a list of the authenticated user's portfolios.

    Supports filtering by:
    - **currency**: Filter by base currency
    - **search**: Partial match on portfolio name

    Supports pagination with **skip** and **limit**.
    """
    # Only show the current user's portfolios
    query = select(Portfolio).where(Portfolio.user_id == current_user.id)

    # Apply filters
    if currency is not None:
        query = query.where(Portfolio.currency == currency)  # Already normalized by validator

    if search is not None:
        search_pattern = f"%{search}%"
        query = query.where(Portfolio.name.ilike(search_pattern))

    # Order by creation date (newest first)
    query = query.order_by(Portfolio.created_at.desc())

    # Get total count before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query)

    # Apply pagination
    portfolios = db.scalars(query.offset(skip).limit(limit)).all()

    return PortfolioListResponse(
        items=list(portfolios),
        pagination=PaginationMeta.create(total=total, skip=skip, limit=limit),
    )


@router.get(
    "/{portfolio_id}",
    response_model=PortfolioResponse,
    summary="Get a portfolio by ID",
    response_description="The requested portfolio"
)
def get_portfolio(
        portfolio: Annotated[Portfolio, Depends(get_portfolio_with_owner_check)],
) -> Portfolio:
    """
    Retrieve a single portfolio by its ID.

    Raises **404** if the portfolio does not exist.
    Raises **403** if you don't own the portfolio.
    """
    return portfolio


@router.patch(
    "/{portfolio_id}",
    response_model=PortfolioResponse,
    summary="Update a portfolio",
    response_description="The updated portfolio"
)
def update_portfolio(
        portfolio_update: PortfolioUpdate,
        portfolio: Annotated[Portfolio, Depends(get_portfolio_with_owner_check)],
        db: Annotated[Session, Depends(get_db)],
) -> Portfolio:
    """
    Update an existing portfolio (partial update).

    Only the provided fields will be updated.
    Omitted fields remain unchanged.

    **Note:** You cannot change the owner (user_id) of a portfolio.

    **Warning:** Changing the base currency affects how the portfolio
    value is calculated. Historical transactions are not converted.

    Raises **404** if the portfolio does not exist.
    Raises **403** if you don't own the portfolio.
    """
    update_data = portfolio_update.model_dump(exclude_unset=True)

    # Apply updates
    for field, value in update_data.items():
        setattr(portfolio, field, value)

    db.commit()
    db.refresh(portfolio)

    return portfolio


@router.delete(
    "/{portfolio_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a portfolio",
)
def delete_portfolio(
        portfolio: Annotated[Portfolio, Depends(get_portfolio_with_owner_check)],
        db: Annotated[Session, Depends(get_db)],
) -> None:
    """
    Delete a portfolio.

    **Warning:** This will also delete all transactions in the portfolio.
    This action cannot be undone.

    Raises **404** if the portfolio does not exist.
    Raises **403** if you don't own the portfolio.
    """
    # Hard delete — portfolio and its transactions are removed
    db.delete(portfolio)
    db.commit()

    return None
