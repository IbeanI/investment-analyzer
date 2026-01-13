import enum
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Numeric, UniqueConstraint
from sqlalchemy.orm import relationship, declarative_base

# The Base class for all our models
Base = declarative_base()


# Enums help enforce data integrity at the database level
class TransactionType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"

    # Not yet implemented
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


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationship: One User has Many Portfolios
    portfolios = relationship("Portfolio", back_populates="owner")


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    currency = Column(String, default="USD", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="portfolios")
    transactions = relationship("Transaction", back_populates="portfolio")


class Asset(Base):
    """
    Global table of assets (AAPL, MSFT, etc.) shared by all users.
    This prevents storing duplicate data for 'Apple' for every user.
    """
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, unique=True, index=True, nullable=False)  # e.g. "AAPL"
    name = Column(String, nullable=True)
    asset_class = Column(Enum(AssetClass), nullable=False)
    sector = Column(String, nullable=True)
    region = Column(String, nullable=True)

    # Relationship to prices
    prices = relationship("MarketData", back_populates="asset")
    transactions = relationship("Transaction", back_populates="asset")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)

    type = Column(Enum(TransactionType), nullable=False)
    date = Column(DateTime, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))  # When it was recorded

    # Use Numeric for financial calculations to avoid floating point errors
    quantity = Column(Numeric(10, 4), nullable=False)
    price_per_share = Column(Numeric(10, 2), nullable=False)
    currency = Column(String, default="USD")

    portfolio = relationship("Portfolio", back_populates="transactions")
    asset = relationship("Asset", back_populates="transactions")


class MarketData(Base):
    """
    Historical price data cache.
    """
    __tablename__ = "market_data"
    __table_args__ = (
        UniqueConstraint('asset_id', 'date', name='uq_asset_date'),
    )

    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)
    date = Column(DateTime, nullable=False, index=True)
    close_price = Column(Numeric(10, 2), nullable=False)
    adjusted_close = Column(Numeric(10, 2), nullable=True)

    asset = relationship("Asset", back_populates="prices")
