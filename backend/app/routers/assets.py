# backend/app/routers/assets.py
"""
Asset management endpoints.

Provides CRUD operations for the global asset registry.
Assets are shared across all users (e.g., AAPL is the same for everyone).

Note: An asset is uniquely identified by the combination of ticker + exchange.
The same ticker can exist on different exchanges (e.g., VUAA on XETRA vs LSE).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Asset, AssetClass
from app.schema.assets import AssetCreate, AssetUpdate, AssetResponse, AssetListResponse

# =============================================================================
# ROUTER SETUP
# =============================================================================

router = APIRouter(
    prefix="/assets",
    tags=["Assets"],
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_asset_or_404(db: Session, asset_id: int) -> Asset:
    """
    Fetch an asset by ID or raise 404 if not found.
    """
    asset = db.get(Asset, asset_id)

    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset with id {asset_id} not found"
        )

    return asset


def check_ticker_exchange_exists(
        db: Session,
        ticker: str,
        exchange: str,
        exclude_id: int | None = None
) -> bool:
    """
    Check if an asset with the given ticker+exchange combination already exists.
    
    Args:
        db: Database session
        ticker: Asset ticker symbol
        exchange: Exchange code
        exclude_id: Asset ID to exclude from check (for updates)
    
    Returns:
        True if the combination already exists, False otherwise
    """
    query = select(Asset).where(
        and_(
            Asset.ticker == ticker,
            Asset.exchange == exchange
        )
    )

    # When updating, exclude the asset being updated
    if exclude_id is not None:
        query = query.where(Asset.id != exclude_id)

    existing = db.execute(query).scalar_one_or_none()
    return existing is not None


def check_isin_exists(
        db: Session,
        isin: str,
        exclude_id: int | None = None
) -> bool:
    """
    Check if an asset with the given ISIN already exists.
    
    ISIN is globally unique by design.
    """
    query = select(Asset).where(Asset.isin == isin)

    if exclude_id is not None:
        query = query.where(Asset.id != exclude_id)

    existing = db.execute(query).scalar_one_or_none()
    return existing is not None


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post(
    "/",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new asset",
    response_description="The created asset"
)
def create_asset(
        asset: AssetCreate,
        db: Session = Depends(get_db)
) -> Asset:
    """
    Create a new asset in the global registry.
    
    An asset is uniquely identified by the combination of **ticker + exchange**.
    The same ticker can exist on different exchanges (e.g., VUAA on XETRA vs LSE).
    
    - **ticker**: Trading symbol (e.g., AAPL, VUAA)
    - **exchange**: Stock exchange (e.g., NASDAQ, XETRA, LSE)
    - **asset_class**: Type of asset (STOCK, ETF, BOND, etc.)
    - **isin**: Optional but globally unique identifier
    """
    # Check if ticker+exchange combination already exists
    if check_ticker_exchange_exists(db, asset.ticker, asset.exchange):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Asset with ticker '{asset.ticker}' on exchange '{asset.exchange}' already exists"
        )

    # Check if ISIN already exists (if provided)
    if asset.isin and check_isin_exists(db, asset.isin):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Asset with ISIN '{asset.isin}' already exists"
        )

    # Create the database object
    db_asset = Asset(**asset.model_dump())

    db.add(db_asset)
    db.commit()
    db.refresh(db_asset)

    return db_asset


@router.get(
    "/",
    response_model=AssetListResponse,
    summary="List all assets",
    response_description="List of assets matching the filters"
)
def list_assets(
        db: Session = Depends(get_db),
        # Query parameters for filtering
        asset_class: AssetClass | None = Query(
            default=None,
            description="Filter by asset class"
        ),
        exchange: str | None = Query(
            default=None,
            description="Filter by exchange (e.g., XETRA, NYSE)"
        ),
        currency: str | None = Query(
            default=None,
            description="Filter by currency (e.g., EUR, USD)"
        ),
        is_active: bool | None = Query(
            default=None,
            description="Filter by active status"
        ),
        search: str | None = Query(
            default=None,
            description="Search in ticker and name"
        ),
        # Pagination
        skip: int = Query(default=0, ge=0, description="Number of records to skip"),
        limit: int = Query(default=100, ge=1, le=1000, description="Maximum records to return"),
) -> AssetListResponse:
    """
    Retrieve a list of assets with optional filtering.
    
    Supports filtering by:
    - **asset_class**: STOCK, ETF, BOND, OPTION, CRYPTO, CASH
    - **exchange**: XETRA, NYSE, LSE, etc.
    - **currency**: EUR, USD, GBP, etc.
    - **is_active**: true or false
    - **search**: partial match on ticker or name
    
    Supports pagination with **skip** and **limit**.
    """
    query = select(Asset)

    # Apply filters
    if asset_class is not None:
        query = query.where(Asset.asset_class == asset_class)

    if exchange is not None:
        query = query.where(Asset.exchange == exchange.upper())

    if currency is not None:
        query = query.where(Asset.currency == currency.upper())

    if is_active is not None:
        query = query.where(Asset.is_active == is_active)

    if search is not None:
        search_pattern = f"%{search}%"
        query = query.where(
            or_(
                Asset.ticker.ilike(search_pattern),
                Asset.name.ilike(search_pattern)
            )
        )

    # Order by exchange first, then ticker (logical grouping)
    query = query.order_by(Asset.exchange, Asset.ticker)

    # Get total count BEFORE applying pagination (for the metadata)
    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query)

    # Apply pagination
    assets = db.scalars(query.offset(skip).limit(limit)).all()

    return AssetListResponse(items=list(assets), total=total, skip=skip, limit=limit)


@router.get(
    "/{asset_id}",
    response_model=AssetResponse,
    summary="Get an asset by ID",
    response_description="The requested asset"
)
def get_asset(
        asset_id: int,
        db: Session = Depends(get_db)
) -> Asset:
    """
    Retrieve a single asset by its ID.
    
    Raises **404** if the asset does not exist.
    """
    return get_asset_or_404(db, asset_id)


@router.patch(
    "/{asset_id}",
    response_model=AssetResponse,
    summary="Update an asset",
    response_description="The updated asset"
)
def update_asset(
        asset_id: int,
        asset_update: AssetUpdate,
        db: Session = Depends(get_db)
) -> Asset:
    """
    Update an existing asset (partial update).
    
    Only the provided fields will be updated.
    Omitted fields remain unchanged.
    
    **Note:** Changing ticker or exchange is validated for uniqueness,
    as the ticker+exchange combination must remain unique.
    
    Raises **404** if the asset does not exist.
    Raises **409** if the new ticker+exchange combination already exists.
    """
    db_asset = get_asset_or_404(db, asset_id)

    update_data = asset_update.model_dump(exclude_unset=True)

    # Determine the final ticker and exchange after update
    new_ticker = update_data.get("ticker", db_asset.ticker)
    new_exchange = update_data.get("exchange", db_asset.exchange)

    # Check uniqueness only if ticker or exchange is being changed
    ticker_changed = "ticker" in update_data and update_data["ticker"] != db_asset.ticker
    exchange_changed = "exchange" in update_data and update_data["exchange"] != db_asset.exchange

    if ticker_changed or exchange_changed:
        if check_ticker_exchange_exists(db, new_ticker, new_exchange, exclude_id=asset_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Asset with ticker '{new_ticker}' on exchange '{new_exchange}' already exists"
            )

    # Check ISIN uniqueness if being changed
    if "isin" in update_data and update_data["isin"] != db_asset.isin:
        if update_data["isin"] and check_isin_exists(db, update_data["isin"], exclude_id=asset_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Asset with ISIN '{update_data['isin']}' already exists"
            )

    # Apply updates
    for field, value in update_data.items():
        setattr(db_asset, field, value)

    db.commit()
    db.refresh(db_asset)

    return db_asset


@router.delete(
    "/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate an asset",
)
def delete_asset(
        asset_id: int,
        db: Session = Depends(get_db)
) -> None:
    """
    Deactivate an asset (soft delete).
    
    The asset is not removed from the database — it is marked as inactive.
    This preserves historical data and transaction integrity.
    
    Raises **404** if the asset does not exist.
    """
    db_asset = get_asset_or_404(db, asset_id)

    db_asset.is_active = False
    db.commit()

    return None
