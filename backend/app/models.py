# backend/app/models.py
import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import String, Date, DateTime, ForeignKey, Enum, Numeric, UniqueConstraint, Boolean, JSON, BigInteger, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


# Enums help enforce data integrity at the database level
class TransactionType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"

    # Not yet supported
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    DIVIDEND = "DIVIDEND"
    FEE = "FEE"
    TAX = "TAX"


class AssetClass(str, enum.Enum):
    STOCK = "STOCK"
    ETF = "ETF"
    BOND = "BOND"
    OPTION = "OPTION"
    CRYPTO = "CRYPTO"
    CASH = "CASH"
    INDEX = "INDEX"
    FUTURE = "FUTURE"
    OTHER = "OTHER"


class SyncStatusEnum(str, enum.Enum):
    """
    Status values for market data sync operations.

    State transitions:
        NEVER → IN_PROGRESS → COMPLETED
        NEVER → IN_PROGRESS → PARTIAL (some assets failed)
        NEVER → IN_PROGRESS → FAILED (all assets failed or error)

        Any state → IN_PROGRESS (when re-sync triggered)
    """
    NEVER = "NEVER"  # Initial state, never synced
    IN_PROGRESS = "IN_PROGRESS"  # Sync currently running
    COMPLETED = "COMPLETED"  # All assets synced successfully
    PARTIAL = "PARTIAL"  # Some assets synced, some failed
    FAILED = "FAILED"  # Sync failed completely
    PENDING = "PENDING"  # Scheduled but not started (future use)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationship: One User has Many Portfolios
    portfolios: Mapped[list["Portfolio"]] = relationship(back_populates="owner")


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String, default="EUR")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Phase 3: Settings and Sync Status
    settings: Mapped["PortfolioSettings | None"] = relationship(
        back_populates="portfolio",
        uselist=False,  # One-to-one relationship
        cascade="all, delete-orphan"
    )
    sync_status: Mapped["SyncStatus | None"] = relationship(
        back_populates="portfolio",
        uselist=False,  # One-to-one relationship
        cascade="all, delete-orphan"
    )

    owner: Mapped["User"] = relationship(back_populates="portfolios")
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan"
    )


class Asset(Base):
    """
    Global table of assets shared by all users.

    An asset is uniquely identified by the combination of ticker AND exchange.
    Example: VUAA on XETRA is different from VUAA on LSE (different currency, price).
    """
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint('ticker', 'exchange', name='uq_ticker_exchange'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Ticker is NOT unique alone — must be combined with exchange
    ticker: Mapped[str] = mapped_column(String, index=True)  # e.g. "AAPL"

    # Exchange is required — together with ticker forms unique identity
    exchange: Mapped[str] = mapped_column(String, index=True)  # e.g. "XETRA", "LSE"

    isin: Mapped[str | None] = mapped_column(String, index=True)  # ISIN (International Securities Identification Number)
    name: Mapped[str | None] = mapped_column(String)
    asset_class: Mapped[AssetClass] = mapped_column(Enum(AssetClass))
    currency: Mapped[str] = mapped_column(String, default="EUR")  # e.g. "EUR", "USD" (Critical for valuation)
    sector: Mapped[str | None] = mapped_column(String)
    region: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # =========================================================================
    # PROXY BACKCASTING (Phase 3)
    # =========================================================================
    # When an asset has missing historical data (delisted, merged, renamed), we use a similar asset (proxy) to generate synthetic price history.
    # NULL = standard asset (use its own data)
    # SET = use this asset's prices to backfill gaps
    proxy_asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True, default=None)
    proxy_notes: Mapped[str | None] = mapped_column(String, nullable=True, default=None)  # e.g., "Lyxor MSCI World Climate Change → Deka MSCI World Climate Change ESG"

    # Self-referential relationship for proxy navigation
    proxy: Mapped["Asset | None"] = relationship("Asset", remote_side="Asset.id", foreign_keys=[proxy_asset_id])

    # Relationship to prices and transactions
    prices: Mapped[list["MarketData"]] = relationship(back_populates="asset", foreign_keys="MarketData.asset_id")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="asset")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        # Composite index for point-in-time valuation queries:
        # "Get all transactions for portfolio X up to date Y"
        # This is the most common query pattern in valuation/history_calculator.py
        Index('ix_transaction_portfolio_date', 'portfolio_id', 'date'),
        # Composite index for filtering by portfolio + asset:
        # "Get all transactions for asset A in portfolio X"
        # Used by transaction listing and analytics
        Index('ix_transaction_portfolio_asset_date', 'portfolio_id', 'asset_id', 'date'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True, index=True)
    transaction_type: Mapped[TransactionType] = mapped_column(Enum(TransactionType))
    date: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))  # When it was recorded

    # Use Decimal with high precision to support crypto (up to 8 decimal places)
    # Numeric(18, 8) supports values up to 9,999,999,999.99999999
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    price_per_share: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    currency: Mapped[str] = mapped_column(String, default="EUR")
    fee: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal(0))
    fee_currency: Mapped[str] = mapped_column(String)  # If different from trade currency (e.g. EUR)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), default=Decimal(1))  # Conversion rate to Portfolio Base Currency at time of trade

    portfolio: Mapped["Portfolio"] = relationship(back_populates="transactions")
    asset: Mapped["Asset | None"] = relationship(back_populates="transactions")


class MarketData(Base):
    """
    Historical price data cache (OHLCV format).

    Stores daily price data fetched from market data providers (Yahoo Finance).
    Each record represents one trading day for one asset.

    OHLCV = Open, High, Low, Close, Volume (standard financial data format)

    Synthetic Data:
        When proxy backcasting is used (Phase 3), prices can be synthetically
        generated from a proxy asset. These records are marked with:
        - is_synthetic = True
        - proxy_source_id = ID of the proxy asset used
    """
    __tablename__ = "market_data"
    __table_args__ = (
        UniqueConstraint('asset_id', 'date', name='uq_asset_date'),
        # Composite index for queries filtering by synthetic status:
        # "Get all non-synthetic prices for asset X in date range"
        # Used by proxy backcasting to detect price gaps
        Index('ix_market_data_asset_synthetic_date', 'asset_id', 'is_synthetic', 'date'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)  # Daily data - no time component

    # =========================================================================
    # OHLCV DATA (Open, High, Low, Close, Volume)
    # =========================================================================
    # Standard financial price data format
    # All prices use Decimal for financial precision (18 digits, 8 decimals)

    open_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    high_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    low_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    close_price: Mapped[Decimal] = mapped_column(Numeric(18, 8))  # Required - primary valuation price
    adjusted_close: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)  # Adjusted for splits/dividends
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # Trading volume

    # =========================================================================
    # METADATA (Data Lineage)
    # =========================================================================
    provider: Mapped[str] = mapped_column(String(50), default="yahoo")  # e.g., "yahoo", "alpha_vantage"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # =========================================================================
    # SYNTHETIC DATA TRACKING (Phase 3 - Proxy Backcasting)
    # =========================================================================
    # When prices are generated via proxy backcasting, we track:
    # - is_synthetic: True if this price was calculated, not fetched from provider
    # - proxy_source_id: The proxy asset whose prices were used for calculation

    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    proxy_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id"), nullable=True, default=None
    )

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================
    # Explicit foreign_keys required due to multiple FKs pointing to assets table

    asset: Mapped["Asset"] = relationship(back_populates="prices", foreign_keys=[asset_id])
    proxy_source: Mapped["Asset | None"] = relationship("Asset", foreign_keys=[proxy_source_id])


class ExchangeRate(Base):
    """
    Historical exchange rates between currency pairs.

    Used for converting asset values to portfolio base currency
    at any historical date.

    Convention: rate represents "1 base_currency = X quote_currency"
    Example: base=USD, quote=EUR, rate=0.92 means 1 USD = 0.92 EUR

    Data is fetched from Yahoo Finance using symbols like "USDEUR=X"
    """
    __tablename__ = "exchange_rates"
    __table_args__ = (
        # UniqueConstraint automatically creates an index on (base, quote, date)
        UniqueConstraint('base_currency', 'quote_currency', 'date',
                         name='uq_exchange_rate_pair_date'),
        # Optimized index for the common FX lookup pattern:
        # "Get rates where quote_currency = portfolio_currency AND base_currency IN (...)"
        # quote_currency is always an equality condition (the portfolio's base currency),
        # while base_currency varies (different asset currencies). Putting quote_currency
        # first allows PostgreSQL to use the index more efficiently.
        Index('ix_exchange_rate_quote_base_date', 'quote_currency', 'base_currency', 'date'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Currency pair (e.g., USD/EUR means 1 USD = X EUR)
    base_currency: Mapped[str] = mapped_column(String(3), index=True)  # e.g., "USD"
    quote_currency: Mapped[str] = mapped_column(String(3), index=True)  # e.g., "EUR"

    # The date for this rate (daily data - no time component)
    date: Mapped[date] = mapped_column(Date, index=True)

    # The exchange rate (Decimal for precision)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8))  # e.g., 0.92610000

    # Metadata
    provider: Mapped[str] = mapped_column(String(50), default="yahoo")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )


class SyncStatus(Base):
    """
    Tracks market data synchronization status per portfolio.

    Allows users to see:
    - When data was last synced
    - What date range is covered
    - Any errors that occurred
    """
    __tablename__ = "sync_status"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id"),
        unique=True,  # One status record per portfolio
        index=True
    )

    # Sync timing
    last_sync_started: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    last_sync_completed: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    # Sync status
    status: Mapped[SyncStatusEnum] = mapped_column(
        Enum(SyncStatusEnum),
        default=SyncStatusEnum.NEVER
    )

    # Coverage summary (JSON for flexibility)
    # Example: {
    #   "assets": {"AAPL": {"from": "2020-01-01", "to": "2024-01-15", "gaps": []}},
    #   "fx_pairs": {"USD/EUR": {"from": "2020-01-01", "to": "2024-01-15"}}
    # }
    coverage_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Error tracking
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationship
    portfolio: Mapped["Portfolio"] = relationship(back_populates="sync_status")


class PortfolioSettings(Base):
    """
    User preferences for a portfolio.

    Currently stores:
    - enable_proxy_backcasting: Whether to use synthetic data for gaps (Beta)

    Future settings could include:
    - Reporting preferences
    - Notification settings
    - Display preferences
    """
    __tablename__ = "portfolio_settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id"),
        unique=True,  # One settings record per portfolio
        index=True
    )

    # Proxy backcasting opt-in (Beta feature)
    enable_proxy_backcasting: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationship
    portfolio: Mapped["Portfolio"] = relationship(back_populates="settings")
