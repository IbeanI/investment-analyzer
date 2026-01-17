#!/usr/bin/env python3
# backend/scripts/seed_sample_data.py
import logging
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Setup path to import app modules
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal
from app.models import User, Portfolio, Asset, Transaction, TransactionType, AssetClass
from app.models import MarketData, ExchangeRate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def seed():
    db = SessionLocal()
    try:
        logger.info("🌱 Starting Database Seeding...")

        # 1. Create Test User
        user = db.query(User).filter(User.email == "demo@example.com").first()
        if not user:
            user = User(
                email="demo@example.com",
                hashed_password="hashed_secret_password",  # In real app, hash this!
                created_at=datetime.now(timezone.utc)
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info(f"✅ Created User: {user.email}")
        else:
            logger.info(f"ℹ️ User exists: {user.email}")

        # 2. Create Portfolio
        portfolio = db.query(Portfolio).filter(Portfolio.user_id == user.id).first()
        if not portfolio:
            portfolio = Portfolio(
                user_id=user.id,
                name="Retirement Fund 2050",
                currency="EUR",
                created_at=datetime.now(timezone.utc)
            )
            db.add(portfolio)
            db.commit()
            db.refresh(portfolio)
            logger.info(f"✅ Created Portfolio: {portfolio.name}")
        else:
            logger.info(f"ℹ️ Portfolio exists: {portfolio.name}")

        # 3. Create/Resolve Assets (using Service logic)
        # We manually insert to ensure they exist for the transaction
        assets_data = [
            {"ticker": "NVDA", "exchange": "NASDAQ", "name": "NVIDIA Corp", "type": AssetClass.STOCK, "curr": "USD"},
            {"ticker": "VWCE", "exchange": "XETRA", "name": "Vanguard FTSE All-World", "type": AssetClass.ETF, "curr": "EUR"},
        ]

        created_assets = {}

        for data in assets_data:
            asset = db.query(Asset).filter(
                Asset.ticker == data["ticker"],
                Asset.exchange == data["exchange"]
            ).first()

            if not asset:
                asset = Asset(
                    ticker=data["ticker"],
                    exchange=data["exchange"],
                    name=data["name"],
                    asset_class=data["type"],
                    currency=data["curr"],
                    is_active=True
                )
                db.add(asset)
                db.commit()
                db.refresh(asset)
                logger.info(f"✅ Created Asset: {asset.ticker}")
            created_assets[data["ticker"]] = asset

        # 4. Create Transactions
        if not db.query(Transaction).filter(Transaction.portfolio_id == portfolio.id).first():
            t1 = Transaction(
                portfolio_id=portfolio.id,
                asset_id=created_assets["NVDA"].id,
                transaction_type=TransactionType.BUY,
                date=datetime(2023, 1, 15, 10, 30, tzinfo=timezone.utc),
                quantity=Decimal("10.0"),
                price_per_share=Decimal("150.00"),
                currency="USD",
                exchange_rate=Decimal("0.92"),  # USD to EUR
                fee=Decimal("2.0"),
                fee_currency="USD"
            )

            t2 = Transaction(
                portfolio_id=portfolio.id,
                asset_id=created_assets["VWCE"].id,
                transaction_type=TransactionType.BUY,
                date=datetime(2023, 2, 20, 11, 00, tzinfo=timezone.utc),
                quantity=Decimal("50.0"),
                price_per_share=Decimal("105.50"),
                currency="EUR",
                exchange_rate=Decimal("1.0"),
                fee=Decimal("5.0"),
                fee_currency="EUR"
            )

            db.add_all([t1, t2])
            db.commit()
            logger.info("✅ Created Sample Transactions")

        logger.info("🚀 Seeding Complete!")

        # 5. Seed Market Data for Valuation
        # We need prices for the 'current' date (or the date you want to value at)
        # Let's assume we want to value the portfolio as of TODAY (or a fixed date)

        # Example: Seed data for NVDA (USD)
        nvda = created_assets["NVDA"]
        if not db.query(MarketData).filter_by(asset_id=nvda.id).first():
            md_nvda = MarketData(
                asset_id=nvda.id,
                date=datetime.now(timezone.utc).date(),
                close_price=Decimal("450.00"),  # Static price for demo
                open_price=Decimal("445.00"),
                high_price=Decimal("455.00"),
                low_price=Decimal("440.00"),
                volume=1000000
            )
            db.add(md_nvda)
            logger.info(f"✅ Created Market Data for {nvda.ticker}")

        # Example: Seed Exchange Rate (USD -> EUR)
        # Valuation Service needs this to convert NVDA value to Portfolio Currency
        if not db.query(ExchangeRate).filter_by(base_currency="USD", quote_currency="EUR").first():
            fx_rate = ExchangeRate(
                base_currency="USD",
                quote_currency="EUR",
                date=datetime.now(timezone.utc).date(),
                rate=Decimal("0.92")
            )
            db.add(fx_rate)
            logger.info("✅ Created Exchange Rate USD/EUR")

        db.commit()

    except Exception as e:
        logger.error(f"❌ Seeding Failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
