# backend/app/routers/transactions.py
"""
Transaction management endpoints.

Provides CRUD operations for buy/sell transactions within portfolios.
Transactions record the purchase or sale of assets.

Key concepts:
- Each transaction belongs to ONE portfolio
- Each transaction references ONE asset
- Transactions cannot be moved between portfolios
- Transaction type (BUY/SELL) cannot be changed after creation
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Transaction, Portfolio, Asset, TransactionType
from app.schemas.transactions import (
    TransactionCreate,
    TransactionUpdate,
    TransactionResponse,
    TransactionListResponse,
)

# =============================================================================
# ROUTER SETUP
# =============================================================================

router = APIRouter(
    prefix="/transactions",
    tags=["Transactions"],
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_transaction_or_404(db: Session, transaction_id: int) -> Transaction:
    """
    Fetch a transaction by ID or raise 404 if not found.
    """
    transaction = db.get(Transaction, transaction_id)

    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction with id {transaction_id} not found"
        )

    return transaction


def validate_portfolio_exists(db: Session, portfolio_id: int) -> Portfolio:
    """
    Verify that a portfolio exists, raise 404 if not.
    """
    portfolio = db.get(Portfolio, portfolio_id)

    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio with id {portfolio_id} not found"
        )

    return portfolio


def validate_asset_exists(db: Session, asset_id: int) -> Asset:
    """
    Verify that an asset exists and is active, raise error if not.
    """
    asset = db.get(Asset, asset_id)

    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset with id {asset_id} not found"
        )

    if not asset.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Asset with id {asset_id} is inactive and cannot be traded"
        )

    return asset


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post(
    "/",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new transaction",
    response_description="The created transaction"
)
def create_transaction(
        transaction: TransactionCreate,
        db: Session = Depends(get_db)
) -> Transaction:
    """
    Record a new buy or sell transaction.

    - **portfolio_id**: Which portfolio this transaction belongs to
    - **asset_id**: Which asset is being traded
    - **transaction_type**: BUY or SELL
    - **date**: When the trade was executed
    - **quantity**: Number of shares/units
    - **price_per_share**: Price per unit at time of trade
    - **fee**: Optional transaction fee (default: 0)

    The portfolio and asset must exist. The asset must be active.
    """
    # Validate foreign keys
    validate_portfolio_exists(db, transaction.portfolio_id)
    validate_asset_exists(db, transaction.asset_id)

    # Create the transaction
    txn_data = transaction.model_dump()
    if txn_data.get("fee_currency") is None:
        txn_data["fee_currency"] = txn_data["currency"]

    db_transaction = Transaction(**txn_data)

    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)

    return db_transaction


@router.get(
    "/",
    response_model=TransactionListResponse,
    summary="List transactions",
    response_description="List of transactions matching the filters"
)
def list_transactions(
        db: Session = Depends(get_db),
        # Required filter (for now, until auth)
        portfolio_id: int | None = Query(
            default=None,
            description="Filter by portfolio ID (recommended)"
        ),
        # Optional filters
        asset_id: int | None = Query(
            default=None,
            description="Filter by asset ID"
        ),
        transaction_type: TransactionType | None = Query(
            default=None,
            description="Filter by transaction type (BUY/SELL)"
        ),
        currency: str | None = Query(
            default=None,
            description="Filter by trade currency"
        ),
        # Date range filters
        date_from: datetime | None = Query(
            default=None,
            description="Filter transactions on or after this date",
            examples=["2025-01-01T00:00:00Z"]
        ),
        date_to: datetime | None = Query(
            default=None,
            description="Filter transactions on or before this date",
            examples=["2025-12-31T23:59:59Z"]
        ),
        # Pagination
        skip: int = Query(default=0, ge=0, description="Number of records to skip"),
        limit: int = Query(default=100, ge=1, le=1000, description="Maximum records to return"),
) -> TransactionListResponse:
    """
    Retrieve a list of transactions with optional filtering.

    **Tip:** Always filter by portfolio_id for better performance.

    Supports filtering by:
    - **portfolio_id**: Get transactions for a specific portfolio
    - **asset_id**: Get transactions for a specific asset
    - **transaction_type**: BUY or SELL
    - **currency**: Trade currency (EUR, USD, etc.)
    - **date_from / date_to**: Date range

    Supports pagination with **skip** and **limit**.

    Results are ordered by date (newest first).
    """
    query = select(Transaction)

    # Apply filters
    if portfolio_id is not None:
        query = query.where(Transaction.portfolio_id == portfolio_id)

    if asset_id is not None:
        query = query.where(Transaction.asset_id == asset_id)

    if transaction_type is not None:
        query = query.where(Transaction.transaction_type == transaction_type)

    if currency is not None:
        query = query.where(Transaction.currency == currency.upper())

    if date_from is not None:
        query = query.where(Transaction.date >= date_from)

    if date_to is not None:
        query = query.where(Transaction.date <= date_to)

    # Order by date (newest first), then by id for consistency
    query = query.order_by(Transaction.date.desc(), Transaction.id.desc())

    # Get total count before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query)

    # Apply pagination
    transactions = db.scalars(query.offset(skip).limit(limit)).all()

    return TransactionListResponse(
        items=list(transactions),
        total=total,
        skip=skip,
        limit=limit
    )


@router.get(
    "/{transaction_id}",
    response_model=TransactionResponse,
    summary="Get a transaction by ID",
    response_description="The requested transaction"
)
def get_transaction(
        transaction_id: int,
        db: Session = Depends(get_db)
) -> Transaction:
    """
    Retrieve a single transaction by its ID.

    Raises **404** if the transaction does not exist.
    """
    return get_transaction_or_404(db, transaction_id)


@router.patch(
    "/{transaction_id}",
    response_model=TransactionResponse,
    summary="Update a transaction",
    response_description="The updated transaction"
)
def update_transaction(
        transaction_id: int,
        transaction_update: TransactionUpdate,
        db: Session = Depends(get_db)
) -> Transaction:
    """
    Update an existing transaction (partial update).

    Only the provided fields will be updated.
    Omitted fields remain unchanged.

    **Cannot be changed:**
    - portfolio_id (can't move transaction to different portfolio)
    - asset_id (can't change which asset was traded)
    - transaction_type (can't change BUY to SELL or vice versa)

    To change these, delete the transaction and create a new one.

    Raises **404** if the transaction does not exist.
    """
    db_transaction = get_transaction_or_404(db, transaction_id)

    update_data = transaction_update.model_dump(exclude_unset=True)

    # Apply updates
    for field, value in update_data.items():
        setattr(db_transaction, field, value)

    db.commit()
    db.refresh(db_transaction)

    return db_transaction


@router.delete(
    "/{transaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a transaction",
)
def delete_transaction(
        transaction_id: int,
        db: Session = Depends(get_db)
) -> None:
    """
    Delete a transaction permanently.

    **Warning:** This action cannot be undone.
    This will affect portfolio valuations and performance calculations.

    Raises **404** if the transaction does not exist.
    """
    db_transaction = get_transaction_or_404(db, transaction_id)

    db.delete(db_transaction)
    db.commit()

    return None


# =============================================================================
# ADDITIONAL ENDPOINTS (Portfolio-scoped)
# =============================================================================

@router.get(
    "/portfolio/{portfolio_id}",
    response_model=TransactionListResponse,
    summary="Get all transactions for a portfolio",
    response_description="All transactions in the specified portfolio"
)
def get_portfolio_transactions(
        portfolio_id: int,
        db: Session = Depends(get_db),
        # Optional filters
        asset_id: int | None = Query(default=None, description="Filter by asset"),
        transaction_type: TransactionType | None = Query(default=None, description="Filter by type"),
        date_from: datetime | None = Query(default=None, description="From date"),
        date_to: datetime | None = Query(default=None, description="To date"),
        # Pagination
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=1000),
) -> TransactionListResponse:
    """
    Retrieve all transactions for a specific portfolio.

    This is a convenience endpoint that ensures you're looking
    at transactions for a valid portfolio.

    Raises **404** if the portfolio does not exist.
    """
    # Verify portfolio exists
    validate_portfolio_exists(db, portfolio_id)

    # Build query
    query = select(Transaction).where(Transaction.portfolio_id == portfolio_id)

    if asset_id is not None:
        query = query.where(Transaction.asset_id == asset_id)

    if transaction_type is not None:
        query = query.where(Transaction.transaction_type == transaction_type)

    if date_from is not None:
        query = query.where(Transaction.date >= date_from)

    if date_to is not None:
        query = query.where(Transaction.date <= date_to)

    query = query.order_by(Transaction.date.desc(), Transaction.id.desc())

    # Count and paginate
    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query)

    transactions = db.scalars(query.offset(skip).limit(limit)).all()

    return TransactionListResponse(
        items=list(transactions),
        total=total,
        skip=skip,
        limit=limit
    )
