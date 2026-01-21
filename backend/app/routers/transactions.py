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
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AfterValidator
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload, contains_eager

from app.database import get_db
from app.models import Transaction, Portfolio, Asset, TransactionType
from app.schemas.pagination import PaginationMeta
from app.schemas.transactions import (
    TransactionCreate,
    TransactionUpdate,
    TransactionResponse,
    TransactionListResponse,
)
from app.schemas.validators import validate_currency_query, validate_ticker_query
from app.services.asset_resolution import AssetResolutionService
from app.services.analytics.service import AnalyticsService
from app.services.constants import MAX_BATCH_SIZE
from app.dependencies import (
    get_asset_resolution_service,
    get_analytics_service,
)

# Validated query parameter types
CurrencyQuery = Annotated[str | None, AfterValidator(validate_currency_query)]
TickerQuery = Annotated[str | None, AfterValidator(validate_ticker_query)]

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
    Fetch a transaction by ID with eager-loaded asset, or raise 404.
    """
    # FIX: Use select with joinedload instead of db.get()
    query = (
        select(Transaction)
        .options(joinedload(Transaction.asset))
        .where(Transaction.id == transaction_id)
    )
    transaction = db.scalar(query)

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
        db: Session = Depends(get_db),
        asset_service: AssetResolutionService = Depends(get_asset_resolution_service),
        analytics_service: AnalyticsService = Depends(get_analytics_service),
) -> Transaction:
    """
    Record a new buy or sell transaction.

    **Asset Resolution:** You provide ticker + exchange, and the backend
    automatically resolves this to an asset:
    - If the asset exists in the database → uses existing asset
    - If not → fetches details from Yahoo Finance and creates it

    - **portfolio_id**: Which portfolio this transaction belongs to
    - **ticker**: Trading symbol (e.g., AAPL, NVDA)
    - **exchange**: Stock exchange (e.g., NASDAQ, XETRA)
    - **transaction_type**: BUY or SELL
    - **date**: When the trade was executed
    - **quantity**: Number of shares/units
    - **price_per_share**: Price per unit at time of trade

    **Errors:**
    - 404: Portfolio not found, or asset not found on Yahoo Finance
    - 400: Asset is deactivated
    - 502: Yahoo Finance API error

    The portfolio must exist.
    """
    # Validate portfolio exists
    validate_portfolio_exists(db, transaction.portfolio_id)

    # Resolve asset (lookup in DB or create from Yahoo Finance)
    # Domain exceptions propagate to global handlers in main.py
    asset = asset_service.resolve_asset(
        db=db,
        ticker=transaction.ticker,
        exchange=transaction.exchange,
    )

    # Determine fee_currency (default to transaction currency)
    fee_currency = transaction.fee_currency if transaction.fee_currency is not None else transaction.currency

    # Create transaction with resolved asset_id
    db_transaction = Transaction(
        portfolio_id=transaction.portfolio_id,
        asset_id=asset.id,
        transaction_type=transaction.transaction_type,
        date=transaction.date,
        quantity=transaction.quantity,
        price_per_share=transaction.price_per_share,
        currency=transaction.currency,
        fee=transaction.fee,
        fee_currency=fee_currency,
        exchange_rate=transaction.exchange_rate,
    )

    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)

    # Invalidate analytics cache for this portfolio
    analytics_service.invalidate_cache(transaction.portfolio_id)

    # Return with eager-loaded asset for response
    return get_transaction_or_404(db, db_transaction.id)


@router.get(
    "/",
    response_model=TransactionListResponse,
    summary="List transactions",
    response_description="List of transactions matching the filters"
)
def list_transactions(
        db: Session = Depends(get_db),
        # Filters
        portfolio_id: int | None = Query(
            default=None,
            description="Filter by portfolio ID (recommended)"
        ),
        asset_id: int | None = Query(
            default=None,
            description="Filter by asset ID"
        ),
        ticker: TickerQuery = Query(
            default=None,
            description="Filter by ticker symbol"
        ),
        transaction_type: TransactionType | None = Query(
            default=None,
            description="Filter by transaction type (BUY/SELL)"
        ),
        currency: CurrencyQuery = Query(
            default=None,
            description="Filter by trade currency (ISO 4217, e.g., EUR, USD)"
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
    - **ticker**: Filter by ticker symbol
    - **transaction_type**: BUY or SELL
    - **currency**: Trade currency (EUR, USD, etc.)
    - **date_from / date_to**: Date range

    Supports pagination with **skip** and **limit**.

    Results are ordered by date (newest first).
    """
    # Build base query
    query = select(Transaction)

    if ticker is not None:
        # Use explicit join + contains_eager when filtering
        query = (
            query
            .join(Transaction.asset)
            .options(contains_eager(Transaction.asset))
            .where(Asset.ticker == ticker)  # Already normalized by validator
        )
    else:
        # Use joinedload when not filtering by asset
        query = query.options(joinedload(Transaction.asset))

    # Apply filters
    if portfolio_id is not None:
        query = query.where(Transaction.portfolio_id == portfolio_id)

    if asset_id is not None:
        query = query.where(Transaction.asset_id == asset_id)

    if transaction_type is not None:
        query = query.where(Transaction.transaction_type == transaction_type)

    if currency is not None:
        query = query.where(Transaction.currency == currency)  # Already normalized by validator

    if date_from is not None:
        query = query.where(Transaction.date >= date_from)

    if date_to is not None:
        query = query.where(Transaction.date <= date_to)

    # Order by date (newest first), then by id for consistency
    query = query.order_by(Transaction.date.desc(), Transaction.id.desc())

    # Get total count before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query)

    # Apply pagination and use .unique() to handle joinedload properly
    transactions = db.scalars(query.offset(skip).limit(limit)).unique().all()

    return TransactionListResponse(
        items=list(transactions),
        pagination=PaginationMeta.create(total=total, skip=skip, limit=limit),
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
        db: Session = Depends(get_db),
        analytics_service: AnalyticsService = Depends(get_analytics_service),
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

    # Invalidate analytics cache for this portfolio
    analytics_service.invalidate_cache(db_transaction.portfolio_id)

    # FIX: Return with eager-loaded asset
    return get_transaction_or_404(db, transaction_id)


@router.delete(
    "/{transaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a transaction",
)
def delete_transaction(
        transaction_id: int,
        db: Session = Depends(get_db),
        analytics_service: AnalyticsService = Depends(get_analytics_service),
) -> None:
    """
    Delete a transaction permanently.

    **Warning:** This action cannot be undone.
    This will affect portfolio valuations and performance calculations.

    Raises **404** if the transaction does not exist.
    """
    db_transaction = get_transaction_or_404(db, transaction_id)

    # Capture portfolio_id before deletion
    portfolio_id = db_transaction.portfolio_id

    db.delete(db_transaction)
    db.commit()

    # Invalidate analytics cache for this portfolio
    analytics_service.invalidate_cache(portfolio_id)

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
        ticker: TickerQuery = Query(default=None, description="Filter by ticker"),
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

    # Build base query - filter by portfolio_id
    query = select(Transaction).where(Transaction.portfolio_id == portfolio_id)

    if ticker is not None:
        # Use explicit join + contains_eager when filtering
        query = (
            query
            .join(Transaction.asset)
            .options(contains_eager(Transaction.asset))
            .where(Asset.ticker == ticker)  # Already normalized by validator
        )
    else:
        # Use joinedload when not filtering by asset
        query = query.options(joinedload(Transaction.asset))

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

    # Use .unique() to handle joinedload properly
    transactions = db.scalars(query.offset(skip).limit(limit)).unique().all()

    return TransactionListResponse(
        items=list(transactions),
        pagination=PaginationMeta.create(total=total, skip=skip, limit=limit),
    )


@router.post(
    "/batch",
    response_model=list[TransactionResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Batch create transactions",
    response_description="The created transactions"
)
def create_transactions_batch(
        transactions: list[TransactionCreate],
        db: Session = Depends(get_db),
        asset_service: AssetResolutionService = Depends(get_asset_resolution_service),
        analytics_service: AnalyticsService = Depends(get_analytics_service),
) -> list[Transaction]:
    """
    Create multiple transactions in a single request.

    This is much more efficient than calling POST /transactions/ multiple times.
    It uses batch asset resolution to minimize database and API calls.

    **Limit:** Maximum {MAX_BATCH_SIZE} transactions per request.
    """
    if not transactions:
        return []

    # Validate batch size
    if len(transactions) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch size {len(transactions)} exceeds maximum of {MAX_BATCH_SIZE} transactions"
        )

    # 1. Validate Portfolios (Optimization: Check unique IDs once)
    portfolio_ids = {t.portfolio_id for t in transactions}
    existing_portfolios = db.scalars(
        select(Portfolio.id).where(Portfolio.id.in_(portfolio_ids))
    ).all()

    if len(existing_portfolios) != len(portfolio_ids):
        missing = sorted(portfolio_ids - set(existing_portfolios))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolios not found: {', '.join(str(p) for p in missing)}"
        )

    # 2. Batch Resolve Assets
    # Extract all (ticker, exchange) tuples to resolve in one go
    asset_requests = [(t.ticker, t.exchange) for t in transactions]

    # This magic method resolves everything (DB lookup + Yahoo Fetch + Create) in bulk
    resolution_result = asset_service.resolve_assets_batch(db, asset_requests)

    # 3. Handle Resolution Failures
    if not resolution_result.all_resolved:
        errors = []
        for key in resolution_result.deactivated:
            errors.append(f"{key[0]} on {key[1]}: deactivated")
        for key in resolution_result.not_found:
            errors.append(f"{key[0]} on {key[1]}: not found")
        for key, exc in resolution_result.errors.items():
            errors.append(f"{key[0]} on {key[1]}: {exc}")
        error_list = "; ".join(errors)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Asset resolution failed: {error_list}"
        )

    # 4. Create Transaction Objects
    resolved_assets_map = resolution_result.resolved
    new_transactions = []

    for i, txn_data in enumerate(transactions):
        key = (txn_data.ticker.strip().upper(), txn_data.exchange.strip().upper() if txn_data.exchange else "")
        asset = resolved_assets_map[key]

        # Default fee logic
        fee_currency = txn_data.fee_currency or txn_data.currency

        new_txn = Transaction(
            portfolio_id=txn_data.portfolio_id,
            asset_id=asset.id,
            transaction_type=txn_data.transaction_type,
            date=txn_data.date,
            quantity=txn_data.quantity,
            price_per_share=txn_data.price_per_share,
            currency=txn_data.currency,
            fee=txn_data.fee,
            fee_currency=fee_currency,
            exchange_rate=txn_data.exchange_rate,
        )
        new_transactions.append(new_txn)

    # 5. Atomic Commit (All or Nothing)
    from sqlalchemy.exc import IntegrityError, DataError, OperationalError
    try:
        db.add_all(new_transactions)
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Data integrity error: {str(e)}"
        )
    except DataError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid data: {str(e)}"
        )
    except OperationalError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database unavailable: {str(e)}"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}"
        )

    # 6. Invalidate analytics cache for all affected portfolios
    for portfolio_id in portfolio_ids:
        analytics_service.invalidate_cache(portfolio_id)

    # 7. Reload with eager-loaded assets for response
    result_ids = [txn.id for txn in new_transactions]
    query = (
        select(Transaction)
        .options(joinedload(Transaction.asset))
        .where(Transaction.id.in_(result_ids))
        .order_by(Transaction.id)  # Preserve insertion order
    )
    return list(db.scalars(query).unique().all())
