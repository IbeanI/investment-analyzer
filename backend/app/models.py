# backend/app/models.py
import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import String, DateTime, ForeignKey, Enum, Numeric, UniqueConstraint, Integer, Boolean
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
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String, default="EUR")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

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

    # Relationship to prices
    prices: Mapped[list["MarketData"]] = relationship(back_populates="asset")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="asset")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    transaction_type: Mapped[TransactionType] = mapped_column(Enum(TransactionType))
    date: Mapped[datetime] = mapped_column(DateTime)
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
    asset: Mapped["Asset"] = relationship(back_populates="transactions")


class MarketData(Base):
    """
    Historical price data cache.
    """
    __tablename__ = "market_data"
    __table_args__ = (
        UniqueConstraint('asset_id', 'date', name='uq_asset_date'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    date: Mapped[datetime] = mapped_column(DateTime, index=True)
    close_price: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    adjusted_close: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    volume: Mapped[int | None] = mapped_column(Integer)  # Standard market metric

    # Metadata (Data Lineage)
    provider: Mapped[str] = mapped_column(String, default="yahoo")  # e.g. "yahoo", "alpha_vantage"
    asset: Mapped["Asset"] = relationship(back_populates="prices")
