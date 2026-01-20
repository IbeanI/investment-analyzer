# backend/app/routers/portfolios.py
"""
Portfolio management endpoints.

Provides CRUD operations for user portfolios.
Each portfolio belongs to a single user and contains transactions.

Note: Currently there's no authentication, so user_id must be provided.
When auth is implemented (Phase 5), endpoints will automatically use
the authenticated user's ID from the JWT token.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
# HELPER FUNCTIONS
# =============================================================================

def get_portfolio_or_404(db: Session, portfolio_id: int) -> Portfolio:
    """
    Fetch a portfolio by ID or raise 404 if not found.
    """
    portfolio = db.get(Portfolio, portfolio_id)

    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio with id {portfolio_id} not found"
        )

    return portfolio


def get_user_or_404(db: Session, user_id: int) -> User:
    """
    Fetch a user by ID or raise 404 if not found.

    Used to validate that user exists before creating a portfolio.
    """
    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {user_id} not found"
        )

    return user


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
        db: Session = Depends(get_db)
) -> Portfolio:
    """
    Create a new portfolio for a user.

    - **name**: Display name for the portfolio
    - **currency**: Base currency for valuations (EUR, USD, etc.)
    - **user_id**: Owner of the portfolio (will be automatic after auth)

    A user can have multiple portfolios (e.g., "Retirement", "Trading").
    """
    # Verify the user exists
    get_user_or_404(db, portfolio.user_id)

    # Create the portfolio
    db_portfolio = Portfolio(**portfolio.model_dump())

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
        db: Session = Depends(get_db),
        # Filters
        user_id: int | None = Query(
            default=None,
            description="Filter by user ID (required until auth is implemented)"
        ),
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
    Retrieve a list of portfolios with optional filtering.

    **Important:** Until authentication is implemented, you should filter
    by user_id to get a specific user's portfolios.

    Supports filtering by:
    - **user_id**: Get portfolios for a specific user
    - **currency**: Filter by base currency
    - **search**: Partial match on portfolio name

    Supports pagination with **skip** and **limit**.
    """
    query = select(Portfolio)

    # Apply filters
    if user_id is not None:
        query = query.where(Portfolio.user_id == user_id)

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
        portfolio_id: int,
        db: Session = Depends(get_db)
) -> Portfolio:
    """
    Retrieve a single portfolio by its ID.

    Raises **404** if the portfolio does not exist.
    """
    return get_portfolio_or_404(db, portfolio_id)


@router.patch(
    "/{portfolio_id}",
    response_model=PortfolioResponse,
    summary="Update a portfolio",
    response_description="The updated portfolio"
)
def update_portfolio(
        portfolio_id: int,
        portfolio_update: PortfolioUpdate,
        db: Session = Depends(get_db)
) -> Portfolio:
    """
    Update an existing portfolio (partial update).

    Only the provided fields will be updated.
    Omitted fields remain unchanged.

    **Note:** You cannot change the owner (user_id) of a portfolio.

    **Warning:** Changing the base currency affects how the portfolio
    value is calculated. Historical transactions are not converted.

    Raises **404** if the portfolio does not exist.
    """
    db_portfolio = get_portfolio_or_404(db, portfolio_id)

    update_data = portfolio_update.model_dump(exclude_unset=True)

    # Apply updates
    for field, value in update_data.items():
        setattr(db_portfolio, field, value)

    db.commit()
    db.refresh(db_portfolio)

    return db_portfolio


@router.delete(
    "/{portfolio_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a portfolio",
)
def delete_portfolio(
        portfolio_id: int,
        db: Session = Depends(get_db)
) -> None:
    """
    Delete a portfolio.

    **Warning:** This will also delete all transactions in the portfolio.
    This action cannot be undone.

    Raises **404** if the portfolio does not exist.
    """
    db_portfolio = get_portfolio_or_404(db, portfolio_id)

    # Hard delete — portfolio and its transactions are removed
    # Note: Transactions will be cascade deleted if FK is set up correctly
    # If not, you may need to delete transactions first
    db.delete(db_portfolio)
    db.commit()

    return None
