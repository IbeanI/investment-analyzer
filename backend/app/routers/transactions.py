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

All endpoints require authentication. Users can only access transactions
in portfolios they own.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Annotated

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import AfterValidator
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload, contains_eager

from app.database import get_db
from app.models import Transaction, Portfolio, Asset, TransactionType, User
from app.schemas.pagination import PaginationMeta
from app.schemas.transactions import (
    TransactionCreate,
    TransactionUpdate,
    TransactionResponse,
    TransactionListResponse,
    BatchTransactionError,
    BatchTransactionErrorResponse,
)
from app.schemas.validators import validate_currency_query, validate_ticker_query
from app.services.asset_resolution import AssetResolutionService
from app.services.analytics.service import AnalyticsService
from app.services.constants import MAX_BATCH_SIZE
from app.dependencies import (
    get_asset_resolution_service,
    get_analytics_service,
    get_current_user,
    get_portfolio_with_owner_check,
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


def get_transaction_with_owner_check(
    db: Session,
    transaction_id: int,
    current_user: User,
) -> Transaction:
    """
    Fetch a transaction and verify the user owns its portfolio.
    """
    transaction = get_transaction_or_404(db, transaction_id)

    # Get the portfolio and check ownership
    portfolio = db.get(Portfolio, transaction.portfolio_id)
    if portfolio is None or portfolio.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this transaction"
        )

    return transaction


def validate_portfolio_ownership(
    db: Session,
    portfolio_id: int,
    current_user: User,
) -> Portfolio:
    """
    Verify that a portfolio exists and the user owns it.
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
            detail="You don't have permission to access this portfolio"
        )

    return portfolio


def get_current_quantity_held(
    db: Session,
    portfolio_id: int,
    asset_id: int,
    as_of_date: datetime | None = None,
) -> tuple[Decimal, Decimal, Decimal]:
    """
    Calculate the current quantity held for an asset in a portfolio.

    Args:
        db: Database session
        portfolio_id: Portfolio to check
        asset_id: Asset to check
        as_of_date: Optional date to calculate holdings as of (inclusive).
                    If None, calculates current holdings.

    Returns:
        Tuple of (net_quantity, total_bought, total_sold)
    """
    # Build base query for transactions of this asset in this portfolio
    query = (
        select(
            Transaction.transaction_type,
            func.sum(Transaction.quantity).label("total_qty")
        )
        .where(
            Transaction.portfolio_id == portfolio_id,
            Transaction.asset_id == asset_id,
            Transaction.transaction_type.in_([TransactionType.BUY, TransactionType.SELL])
        )
        .group_by(Transaction.transaction_type)
    )

    # If as_of_date is specified, only include transactions up to that date
    if as_of_date is not None:
        query = query.where(Transaction.date <= as_of_date)

    results = db.execute(query).all()

    total_bought = Decimal("0")
    total_sold = Decimal("0")

    for row in results:
        if row.transaction_type == TransactionType.BUY:
            total_bought = Decimal(str(row.total_qty))
        elif row.transaction_type == TransactionType.SELL:
            total_sold = Decimal(str(row.total_qty))

    net_quantity = total_bought - total_sold
    return net_quantity, total_bought, total_sold


def validate_sell_quantity(
    db: Session,
    portfolio_id: int,
    asset_id: int,
    sell_quantity: Decimal,
    transaction_date: datetime,
    asset_ticker: str,
) -> None:
    """
    Validate that a SELL transaction doesn't exceed available quantity.

    Args:
        db: Database session
        portfolio_id: Portfolio containing the asset
        asset_id: Asset being sold
        sell_quantity: Quantity to sell
        transaction_date: Date of the sell transaction
        asset_ticker: Ticker symbol for error messages

    Raises:
        HTTPException: If sell quantity exceeds available quantity
    """
    # Calculate holdings as of the transaction date
    # This ensures we consider the chronological order of transactions
    current_qty, _, _ = get_current_quantity_held(
        db=db,
        portfolio_id=portfolio_id,
        asset_id=asset_id,
        as_of_date=transaction_date,
    )

    if sell_quantity > current_qty:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot sell {sell_quantity} shares of {asset_ticker}. "
                   f"Only {current_qty} shares available as of {transaction_date.date()}."
        )


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
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(get_current_user)],
        asset_service: Annotated[AssetResolutionService, Depends(get_asset_resolution_service)],
        analytics_service: Annotated[AnalyticsService, Depends(get_analytics_service)],
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
    - 403: You don't own the portfolio
    - 400: Asset is deactivated, or SELL quantity exceeds available holdings
    - 502: Yahoo Finance API error

    The portfolio must exist and belong to you.
    For SELL transactions, you cannot sell more shares than you currently hold.
    """
    # Validate portfolio exists and user owns it
    validate_portfolio_ownership(db, transaction.portfolio_id, current_user)

    # Resolve asset (lookup in DB or create from Yahoo Finance)
    # Domain exceptions propagate to global handlers in main.py
    asset = asset_service.resolve_asset(
        db=db,
        ticker=transaction.ticker,
        exchange=transaction.exchange,
    )

    # Validate SELL quantity doesn't exceed holdings
    if transaction.transaction_type == TransactionType.SELL:
        validate_sell_quantity(
            db=db,
            portfolio_id=transaction.portfolio_id,
            asset_id=asset.id,
            sell_quantity=transaction.quantity,
            transaction_date=transaction.date,
            asset_ticker=transaction.ticker,
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
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(get_current_user)],
        # Filters
        portfolio_id: int | None = Query(
            default=None,
            description="Filter by portfolio ID (must be a portfolio you own)"
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

    Only returns transactions from portfolios you own.

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
    # If portfolio_id provided, verify ownership
    if portfolio_id is not None:
        validate_portfolio_ownership(db, portfolio_id, current_user)

    # Get user's portfolio IDs
    user_portfolio_ids = db.scalars(
        select(Portfolio.id).where(Portfolio.user_id == current_user.id)
    ).all()

    # Build base query - only from user's portfolios
    query = select(Transaction).where(Transaction.portfolio_id.in_(user_portfolio_ids))

    if ticker is not None:
        # Use explicit join + contains_eager when filtering
        # Use ILIKE for partial, case-insensitive search
        query = (
            query
            .join(Transaction.asset)
            .options(contains_eager(Transaction.asset))
            .where(Asset.ticker.ilike(f"%{ticker}%"))
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
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(get_current_user)],
) -> Transaction:
    """
    Retrieve a single transaction by its ID.

    Raises **404** if the transaction does not exist.
    Raises **403** if you don't own the portfolio containing this transaction.
    """
    return get_transaction_with_owner_check(db, transaction_id, current_user)


@router.patch(
    "/{transaction_id}",
    response_model=TransactionResponse,
    summary="Update a transaction",
    response_description="The updated transaction"
)
def update_transaction(
        transaction_id: int,
        transaction_update: TransactionUpdate,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(get_current_user)],
        analytics_service: Annotated[AnalyticsService, Depends(get_analytics_service)],
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
    Raises **403** if you don't own the portfolio containing this transaction.
    """
    db_transaction = get_transaction_with_owner_check(db, transaction_id, current_user)

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
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(get_current_user)],
        analytics_service: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> None:
    """
    Delete a transaction permanently.

    **Warning:** This action cannot be undone.
    This will affect portfolio valuations and performance calculations.

    Raises **404** if the transaction does not exist.
    Raises **403** if you don't own the portfolio containing this transaction.
    """
    db_transaction = get_transaction_with_owner_check(db, transaction_id, current_user)

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
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(get_current_user)],
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
    at transactions for a valid portfolio that you own.

    Raises **404** if the portfolio does not exist.
    Raises **403** if you don't own the portfolio.
    """
    # Verify portfolio exists and user owns it
    validate_portfolio_ownership(db, portfolio_id, current_user)

    # Build base query - filter by portfolio_id
    query = select(Transaction).where(Transaction.portfolio_id == portfolio_id)

    if ticker is not None:
        # Use explicit join + contains_eager when filtering
        # Use ILIKE for partial, case-insensitive search
        query = (
            query
            .join(Transaction.asset)
            .options(contains_eager(Transaction.asset))
            .where(Asset.ticker.ilike(f"%{ticker}%"))
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


@router.get(
    "/portfolio/{portfolio_id}/types",
    response_model=list[str],
    summary="Get distinct transaction types in a portfolio",
    response_description="List of transaction types that exist in the portfolio"
)
def get_portfolio_transaction_types(
        portfolio_id: int,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(get_current_user)],
) -> list[str]:
    """
    Get all distinct transaction types that exist in a portfolio.

    Useful for populating filter dropdowns with only relevant options.

    Raises **404** if the portfolio does not exist.
    Raises **403** if you don't own the portfolio.
    """
    # Verify portfolio exists and user owns it
    validate_portfolio_ownership(db, portfolio_id, current_user)

    # Get distinct transaction types
    query = (
        select(Transaction.transaction_type)
        .where(Transaction.portfolio_id == portfolio_id)
        .distinct()
    )
    types = db.scalars(query).all()

    # Return as strings (enum values)
    return [t.value for t in types]


@router.post(
    "/batch",
    response_model=list[TransactionResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Batch create transactions",
    response_description="The created transactions",
    responses={
        400: {
            "description": "Validation failed - returns detailed per-transaction errors",
            "model": BatchTransactionErrorResponse,
        },
        403: {
            "description": "Not authorized to access one or more portfolios",
        },
        404: {
            "description": "One or more portfolios not found",
        },
    },
)
def create_transactions_batch(
        transactions: list[TransactionCreate],
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(get_current_user)],
        asset_service: Annotated[AssetResolutionService, Depends(get_asset_resolution_service)],
        analytics_service: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> list[Transaction] | JSONResponse:
    """
    Create multiple transactions in a single request.

    This is much more efficient than calling POST /transactions/ multiple times.
    It uses batch asset resolution to minimize database and API calls.

    All portfolios referenced must be owned by you.

    **Limit:** Maximum {MAX_BATCH_SIZE} transactions per request.

    **Atomic Behavior:** If ANY transaction fails validation, NONE are created.
    This prevents partial states in financial data.

    **Error Response:** On validation failure, returns a structured response with
    detailed per-transaction error information including the index, ticker,
    error type, and message for each failing transaction.
    """
    if not transactions:
        return []

    # Validate batch size
    if len(transactions) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch size {len(transactions)} exceeds maximum of {MAX_BATCH_SIZE} transactions"
        )

    # 1. Validate Portfolios and Ownership
    portfolio_ids = {t.portfolio_id for t in transactions}

    # Get user's portfolio IDs
    user_portfolio_ids = set(db.scalars(
        select(Portfolio.id).where(Portfolio.user_id == current_user.id)
    ).all())

    # Check all referenced portfolios exist and are owned by user
    for pid in portfolio_ids:
        if pid not in user_portfolio_ids:
            # Check if portfolio exists at all
            portfolio = db.get(Portfolio, pid)
            if portfolio is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Portfolio {pid} not found"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"You don't have permission to add transactions to portfolio {pid}"
                )

    # 2. Batch Resolve Assets
    # Extract all (ticker, exchange) tuples to resolve in one go
    asset_requests = [(t.ticker, t.exchange) for t in transactions]

    # This magic method resolves everything (DB lookup + Yahoo Fetch + Create) in bulk
    resolution_result = asset_service.resolve_assets_batch(db, asset_requests)

    # 3. Handle Resolution Failures
    if not resolution_result.all_resolved:
        # Build a map from (ticker, exchange) to list of indices for error attribution
        key_to_indices: dict[tuple[str, str], list[int]] = {}
        for i, txn_data in enumerate(transactions):
            key = (txn_data.ticker.strip().upper(), txn_data.exchange.strip().upper() if txn_data.exchange else "")
            if key not in key_to_indices:
                key_to_indices[key] = []
            key_to_indices[key].append(i)

        batch_errors: list[BatchTransactionError] = []

        for key in resolution_result.deactivated:
            for idx in key_to_indices.get(key, []):
                batch_errors.append(BatchTransactionError(
                    index=idx,
                    ticker=key[0],
                    stage="asset_resolution",
                    error_type="deactivated",
                    message=f"Asset '{key[0]}' on exchange '{key[1]}' is deactivated",
                    field="ticker",
                ))

        for key in resolution_result.not_found:
            for idx in key_to_indices.get(key, []):
                batch_errors.append(BatchTransactionError(
                    index=idx,
                    ticker=key[0],
                    stage="asset_resolution",
                    error_type="not_found",
                    message=f"Asset '{key[0]}' on exchange '{key[1]}' was not found in database or Yahoo Finance",
                    field="ticker",
                ))

        for key, exc in resolution_result.errors.items():
            for idx in key_to_indices.get(key, []):
                batch_errors.append(BatchTransactionError(
                    index=idx,
                    ticker=key[0],
                    stage="asset_resolution",
                    error_type="resolution_error",
                    message=f"Error resolving '{key[0]}' on '{key[1]}': {exc}",
                    field="ticker",
                ))

        error_response = BatchTransactionErrorResponse(
            total_requested=len(transactions),
            error_count=len(batch_errors),
            errors=batch_errors,
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=error_response.model_dump(),
        )

    # 4. Validate SELL Quantities
    # Group transactions by (portfolio_id, asset_id) and validate in date order
    resolved_assets_map = resolution_result.resolved
    from collections import defaultdict

    # Build map of normalized key to asset for quick lookup
    portfolio_asset_txns: dict[tuple[int, int], list[tuple[int, TransactionCreate]]] = defaultdict(list)
    for i, txn_data in enumerate(transactions):
        key = (txn_data.ticker.strip().upper(), txn_data.exchange.strip().upper() if txn_data.exchange else "")
        asset = resolved_assets_map[key]
        portfolio_asset_txns[(txn_data.portfolio_id, asset.id)].append((i, txn_data))

    # Validate each portfolio-asset group
    sell_errors: list[BatchTransactionError] = []
    for (portfolio_id, asset_id), txn_list in portfolio_asset_txns.items():
        # Sort by date for proper validation
        txn_list.sort(key=lambda x: x[1].date)

        # Get current holding for this asset
        current_qty, _, _ = get_current_quantity_held(db, portfolio_id, asset_id)

        # Track running balance through the batch
        running_balance = current_qty

        for idx, txn_data in txn_list:
            if txn_data.transaction_type == TransactionType.BUY:
                running_balance += txn_data.quantity
            elif txn_data.transaction_type == TransactionType.SELL:
                if txn_data.quantity > running_balance:
                    sell_errors.append(BatchTransactionError(
                        index=idx,
                        ticker=txn_data.ticker,
                        stage="sell_quantity",
                        error_type="insufficient_quantity",
                        message=f"Cannot sell {txn_data.quantity} shares of {txn_data.ticker}. Only {running_balance} shares available as of {txn_data.date.date()}.",
                        field="quantity",
                    ))
                else:
                    running_balance -= txn_data.quantity

    if sell_errors:
        error_response = BatchTransactionErrorResponse(
            total_requested=len(transactions),
            error_count=len(sell_errors),
            errors=sell_errors,
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=error_response.model_dump(),
        )

    # 5. Create Transaction Objects (step 4 was SELL validation above)
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

    # 6. Atomic Commit (All or Nothing)
    from sqlalchemy.exc import IntegrityError, DataError, OperationalError
    try:
        db.add_all(new_transactions)
        db.commit()
    except IntegrityError as e:
        db.rollback()
        # Log full error for debugging, return generic message to client
        logger.error(f"Batch transaction integrity error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Data integrity error: A transaction violates database constraints. This may indicate duplicate or conflicting data."
        )
    except DataError as e:
        db.rollback()
        logger.error(f"Batch transaction data error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid data: One or more values are out of acceptable range or format."
        )
    except OperationalError as e:
        db.rollback()
        logger.error(f"Batch transaction operational error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable. Please try again shortly."
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Batch transaction unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while saving transactions."
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
