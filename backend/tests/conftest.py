# backend/tests/conftest.py
"""
Pytest configuration and fixtures.

This module provides shared fixtures for all tests:
- Database session fixtures (in-memory SQLite)
- Mock provider fixtures
- Sample data factories
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    Base,
    Asset,
    AssetClass,
    Portfolio,
    User,
)
from app.services.exceptions import TickerNotFoundError
from app.services.market_data.base import MarketDataProvider, AssetInfo, BatchResult
from app.services.market_data.base import OHLCVData, HistoricalPricesResult


# =============================================================================
# DATABASE FIXTURES
# =============================================================================

@pytest.fixture(scope="function")
def db_engine():
    """Create an in-memory SQLite database engine for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db(db_engine) -> Iterator[Session]:
    """Create a database session for testing."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# =============================================================================
# MOCK MARKET DATA PROVIDER
# =============================================================================

class MockMarketDataProvider(MarketDataProvider):
    """
    Mock implementation of MarketDataProvider for testing.

    Allows configuring responses for specific tickers and simulating errors.
    """

    def __init__(self):
        self._responses: dict[tuple[str, str], AssetInfo] = {}
        self._errors: dict[tuple[str, str], Exception] = {}
        self._call_count: dict[str, int] = {"single": 0, "batch": 0}
        self._available = True
        self._historical_prices: dict[tuple[str, str], HistoricalPricesResult] = {}
        self._fail_tickers: set[str] = set()

    @property
    def name(self) -> str:
        return "mock"

    def add_response(self, ticker: str, exchange: str, info: AssetInfo) -> None:
        """Configure a successful response for a ticker."""
        self._responses[(ticker.upper(), exchange.upper())] = info

    def add_error(self, ticker: str, exchange: str, error: Exception) -> None:
        """Configure an error response for a ticker."""
        self._errors[(ticker.upper(), exchange.upper())] = error

    def set_available(self, available: bool) -> None:
        """Set provider availability for health checks."""
        self._available = available

    def reset(self) -> None:
        """Reset all configured responses and call counts."""
        self._responses.clear()
        self._errors.clear()
        self._call_count = {"single": 0, "batch": 0}
        self._available = True
        self._historical_prices.clear()
        self._fail_tickers.clear()

    @property
    def single_call_count(self) -> int:
        return self._call_count["single"]

    @property
    def batch_call_count(self) -> int:
        return self._call_count["batch"]

    def get_asset_info(self, ticker: str, exchange: str) -> AssetInfo:
        """Fetch asset info from configured responses."""
        self._call_count["single"] += 1

        key = (ticker.upper(), exchange.upper())

        # Check for configured error
        if key in self._errors:
            raise self._errors[key]

        # Check for configured response
        if key in self._responses:
            return self._responses[key]

        # Default: ticker not found
        raise TickerNotFoundError(ticker=ticker, exchange=exchange, provider=self.name)

    def get_asset_info_batch(self, tickers: list[tuple[str, str]]) -> BatchResult:
        """Fetch batch asset info from configured responses."""
        self._call_count["batch"] += 1

        result = BatchResult()

        for ticker, exchange in tickers:
            key = (ticker.upper(), exchange.upper())

            if key in self._errors:
                result.failed[key] = self._errors[key]
            elif key in self._responses:
                result.successful[key] = self._responses[key]
            else:
                result.failed[key] = TickerNotFoundError(
                    ticker=ticker, exchange=exchange, provider=self.name
                )

        return result

    # =========================================================================
    # Historical prices methods for Phase 3
    # =========================================================================

    def get_historical_prices(
            self,
            ticker: str,
            exchange: str,
            start_date: date,
            end_date: date,
    ) -> HistoricalPricesResult:
        """
        Mock implementation of historical price fetching.

        Returns configured results or generates sample data.
        """
        ticker = ticker.upper()
        exchange = exchange.upper() if exchange else ""
        key = (ticker, exchange)

        # Check if we have configured response for this ticker
        if key in self._historical_prices:
            return self._historical_prices[key]

        # Check if ticker should fail
        if ticker in self._fail_tickers:
            raise TickerNotFoundError(
                ticker=ticker,
                exchange=exchange,
                provider=self.name
            )

        # Generate sample data
        prices = []
        current = start_date
        price = Decimal("100.00")

        while current <= end_date:
            if current.weekday() < 5:  # Skip weekends
                prices.append(OHLCVData(
                    date=current,
                    open=price,
                    high=price * Decimal("1.02"),
                    low=price * Decimal("0.98"),
                    close=price * Decimal("1.01"),
                    volume=1000000,
                    adjusted_close=price * Decimal("1.01"),
                ))
                price = price * Decimal("1.005")
            current += timedelta(days=1)

        return HistoricalPricesResult(
            ticker=ticker,
            exchange=exchange,
            prices=prices,
            success=True,
            from_date=start_date,
            to_date=end_date,
        )

    def set_historical_prices(
            self,
            ticker: str,
            exchange: str,
            result: HistoricalPricesResult
    ) -> None:
        """Configure specific historical prices result for a ticker."""
        key = (ticker.upper(), exchange.upper() if exchange else "")
        self._historical_prices[key] = result

    def set_fail_ticker(self, ticker: str) -> None:
        """Configure a ticker to fail when fetching prices."""
        self._fail_tickers.add(ticker.upper())

    def is_available(self) -> bool:
        """Return configured availability."""
        return self._available


@pytest.fixture
def mock_provider() -> MockMarketDataProvider:
    """Create a fresh mock provider for each test."""
    return MockMarketDataProvider()


# =============================================================================
# SAMPLE DATA FACTORIES
# =============================================================================

def create_asset_info(
        ticker: str = "NVDA",
        exchange: str = "NASDAQ",
        name: str = "NVIDIA Corporation",
        asset_class: AssetClass = AssetClass.STOCK,
        currency: str = "USD",
        sector: str = "Technology",
        region: str = "United States",
        isin: str | None = None,
) -> AssetInfo:
    """Factory function for creating AssetInfo test data."""
    return AssetInfo(
        ticker=ticker,
        exchange=exchange,
        name=name,
        asset_class=asset_class,
        currency=currency,
        sector=sector,
        region=region,
        isin=isin,
    )


def create_asset(
        db: Session,
        ticker: str = "NVDA",
        exchange: str = "NASDAQ",
        name: str = "NVIDIA Corporation",
        asset_class: AssetClass = AssetClass.STOCK,
        currency: str = "USD",
        is_active: bool = True,
) -> Asset:
    """Factory function for creating Asset entities in the database."""
    asset = Asset(
        ticker=ticker,
        exchange=exchange,
        name=name,
        asset_class=asset_class,
        currency=currency,
        is_active=is_active,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def create_user(
        db: Session,
        email: str = "test@example.com",
        hashed_password: str = "hashed_password",
) -> User:
    """Factory function for creating User entities in the database."""
    user = User(
        email=email,
        hashed_password=hashed_password,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_portfolio(
        db: Session,
        user: User,
        name: str = "Test Portfolio",
        currency: str = "EUR",
) -> Portfolio:
    """Factory function for creating Portfolio entities in the database."""
    portfolio = Portfolio(
        user_id=user.id,
        name=name,
        currency=currency,
    )
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return portfolio


# =============================================================================
# FIXTURE EXPORTS (for convenience imports in tests)
# =============================================================================

@pytest.fixture
def sample_asset_info() -> AssetInfo:
    """Provide a sample AssetInfo for tests."""
    return create_asset_info()


@pytest.fixture
def sample_user(db: Session) -> User:
    """Provide a sample User for tests."""
    return create_user(db)


@pytest.fixture
def sample_portfolio(db: Session, sample_user: User) -> Portfolio:
    """Provide a sample Portfolio for tests."""
    return create_portfolio(db, sample_user)
