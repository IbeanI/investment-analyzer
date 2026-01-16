# backend/app/services/fx_rate_service.py
"""
FX Rate Service for fetching and storing historical exchange rates.

This service handles:
- Fetching historical FX rates from Yahoo Finance
- Storing rates in the exchange_rates table
- Retrieving rates for specific dates (with fallback logic)
- Detecting required currency pairs from portfolio transactions

=============================================================================
FX RATE CONVENTION (IMPORTANT!)
=============================================================================

This service uses the Yahoo Finance convention:

    rate = "1 base_currency = X quote_currency"

Example:
    base_currency = "USD"
    quote_currency = "EUR"
    rate = 0.92

    Meaning: 1 USD = 0.92 EUR

Conversion formula:
    To convert USD → EUR:  EUR_amount = USD_amount × rate
    To convert EUR → USD:  USD_amount = EUR_amount ÷ rate

=============================================================================
THIS IS DIFFERENT FROM TRANSACTION.EXCHANGE_RATE!
=============================================================================

The broker-provided exchange_rate in transactions uses the OPPOSITE convention:

    transaction.exchange_rate = "1 portfolio_currency = X transaction_currency"

Example (EUR portfolio buying USD stock):
    exchange_rate = 1.0779

    Meaning: 1 EUR = 1.0779 USD

Conversion formula:
    cost_EUR = cost_USD ÷ exchange_rate

=============================================================================
SUMMARY: The two rates are INVERSES of each other!
=============================================================================

    FX Service rate (USD/EUR):     0.9277  →  1 USD = 0.9277 EUR
    Transaction rate:              1.0779  →  1 EUR = 1.0779 USD

    0.9277 ≈ 1 / 1.0779

The ValuationService will handle both conventions appropriately:
- Cost basis: uses transaction.exchange_rate (broker rate at time of trade)
- Current value: uses FX Service rate (market rate for valuation date)

=============================================================================

Design Principles:
- Single Responsibility: Only handles FX rate operations
- No HTTP Knowledge: Raises domain exceptions, not HTTPException
- Financial Precision: Uses Decimal for all rates
- Fallback Logic: Returns nearest available rate when exact date missing

Yahoo Finance FX Symbols:
- Format: {BASE}{QUOTE}=X (e.g., USDEUR=X means USD to EUR)
- Returns: 1 BASE = X QUOTE

Usage:
    from app.services import FXRateService, FXRateNotFoundError

    service = FXRateService()

    # Sync rates for a date range
    result = service.sync_rates(db, "USD", "EUR", start_date, end_date)

    # Get rate for a specific date (1 USD = X EUR)
    rate = service.get_rate(db, "USD", "EUR", date)

    # Convert USD to EUR
    eur_amount = usd_amount * rate.rate

    # Get required pairs for a portfolio
    pairs = service.get_required_pairs(db, portfolio_id)
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import yfinance as yf
from sqlalchemy import select, and_, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import ExchangeRate, Transaction, Asset, Portfolio
from app.services.exceptions import FXRateNotFoundError, FXProviderError

logger = logging.getLogger(__name__)


# =============================================================================
# RESULT DATA CLASSES
# =============================================================================

@dataclass
class FXSyncResult:
    """Result of an FX rate sync operation."""

    base_currency: str
    quote_currency: str
    start_date: date
    end_date: date
    rates_fetched: int = 0
    rates_inserted: int = 0
    rates_updated: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


@dataclass
class FXRateResult:
    """Result of an FX rate lookup."""

    base_currency: str
    quote_currency: str
    date: date
    rate: Decimal
    is_exact_match: bool = True  # False if fallback was used
    actual_date: date | None = None  # The date the rate is actually from

    def __post_init__(self):
        if self.actual_date is None:
            self.actual_date = self.date


# =============================================================================
# FX RATE SERVICE
# =============================================================================

class FXRateService:
    """
    Service for managing historical exchange rates.

    Fetches rates from Yahoo Finance and stores them in the database.
    Provides rate lookups with fallback to nearest available date.

    Attributes:
        _max_fallback_days: Maximum days to look back for fallback rate

    Example:
        service = FXRateService()

        # Sync USD/EUR rates for 2023
        result = service.sync_rates(
            db, "USD", "EUR",
            date(2023, 1, 1), date(2023, 12, 31)
        )
        print(f"Fetched {result.rates_fetched} rates")

        # Get rate for specific date
        rate_result = service.get_rate(db, "USD", "EUR", date(2023, 6, 15))
        print(f"1 USD = {rate_result.rate} EUR")
    """

    # Provider configuration
    PROVIDER_NAME: str = "yahoo"

    # Fallback configuration
    MAX_FALLBACK_DAYS: int = 7  # Max days to look back for missing rate

    # Yahoo Finance timeout
    YAHOO_TIMEOUT: int = 10

    def __init__(
            self,
            max_fallback_days: int | None = None,
    ) -> None:
        """
        Initialize the FX Rate Service.

        Args:
            max_fallback_days: Maximum days to search for fallback rate.
                              Defaults to MAX_FALLBACK_DAYS (7).
        """
        self._max_fallback_days = max_fallback_days or self.MAX_FALLBACK_DAYS
        logger.info(f"FXRateService initialized (max_fallback_days={self._max_fallback_days})")

    # =========================================================================
    # PUBLIC METHODS
    # =========================================================================

    def sync_rates(
            self,
            db: Session,
            base_currency: str,
            quote_currency: str,
            start_date: date,
            end_date: date,
            force: bool = False,
    ) -> FXSyncResult:
        """
        Fetch and store FX rates for a currency pair and date range.

        Args:
            db: Database session
            base_currency: Base currency code (e.g., "USD")
            quote_currency: Quote currency code (e.g., "EUR")
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)
            force: If True, re-fetch all dates. If False, only fetch missing.

        Returns:
            FXSyncResult with sync statistics

        Raises:
            FXProviderError: If Yahoo Finance fails
        """
        base = base_currency.upper().strip()
        quote = quote_currency.upper().strip()

        result = FXSyncResult(
            base_currency=base,
            quote_currency=quote,
            start_date=start_date,
            end_date=end_date,
        )

        # Same currency = no conversion needed
        if base == quote:
            logger.info(f"Skipping sync for {base}/{quote} (same currency)")
            return result

        logger.info(f"Syncing FX rates: {base}/{quote} from {start_date} to {end_date}")

        # Determine which dates to fetch
        if force:
            dates_to_fetch = self._get_business_days(start_date, end_date)
        else:
            existing_dates = self._get_existing_dates(db, base, quote, start_date, end_date)
            all_dates = self._get_business_days(start_date, end_date)
            dates_to_fetch = [d for d in all_dates if d not in existing_dates]

        if not dates_to_fetch:
            logger.info(f"No missing dates for {base}/{quote}")
            return result

        logger.info(f"Fetching {len(dates_to_fetch)} dates for {base}/{quote}")

        # Fetch from Yahoo Finance
        try:
            rates = self._fetch_rates_from_yahoo(
                base, quote,
                min(dates_to_fetch),
                max(dates_to_fetch)
            )
            result.rates_fetched = len(rates)
        except FXProviderError as e:
            result.errors.append(str(e))
            logger.error(f"Yahoo Finance error: {e}")
            return result

        if not rates:
            result.errors.append(f"No rates returned for {base}/{quote}")
            return result

        # Store in database
        inserted, updated = self._upsert_rates(db, base, quote, rates)
        result.rates_inserted = inserted
        result.rates_updated = updated

        logger.info(
            f"Sync complete: {base}/{quote} - "
            f"fetched={result.rates_fetched}, inserted={inserted}, updated={updated}"
        )

        return result

    def get_rate(
            self,
            db: Session,
            base_currency: str,
            quote_currency: str,
            target_date: date,
            allow_fallback: bool = True,
    ) -> FXRateResult:
        """
        Get the exchange rate for a specific date.

        Args:
            db: Database session
            base_currency: Base currency code (e.g., "USD")
            quote_currency: Quote currency code (e.g., "EUR")
            target_date: Date to get rate for
            allow_fallback: If True, search for nearest rate if exact not found

        Returns:
            FXRateResult with the rate and metadata

        Raises:
            FXRateNotFoundError: If no rate found (and no fallback available)
        """
        base = base_currency.upper().strip()
        quote = quote_currency.upper().strip()

        # Same currency = 1:1 rate
        if base == quote:
            return FXRateResult(
                base_currency=base,
                quote_currency=quote,
                date=target_date,
                rate=Decimal("1"),
                is_exact_match=True,
                actual_date=target_date,
            )

        # Try exact match first
        rate_record = self._get_exact_rate(db, base, quote, target_date)

        if rate_record:
            return FXRateResult(
                base_currency=base,
                quote_currency=quote,
                date=target_date,
                rate=rate_record.rate,
                is_exact_match=True,
                actual_date=self._extract_date(rate_record.date),
            )

        # Try fallback if allowed
        if allow_fallback:
            rate_record = self._get_fallback_rate(db, base, quote, target_date)

            if rate_record:
                actual_date = self._extract_date(rate_record.date)
                logger.debug(
                    f"Using fallback rate for {base}/{quote} on {target_date}: "
                    f"actual date = {actual_date}"
                )
                return FXRateResult(
                    base_currency=base,
                    quote_currency=quote,
                    date=target_date,
                    rate=rate_record.rate,
                    is_exact_match=False,
                    actual_date=actual_date,
                )

        # No rate found
        raise FXRateNotFoundError(base, quote, target_date)

    def get_rate_or_none(
            self,
            db: Session,
            base_currency: str,
            quote_currency: str,
            target_date: date,
            allow_fallback: bool = True,
    ) -> FXRateResult | None:
        """
        Get the exchange rate, returning None if not found.

        Same as get_rate() but returns None instead of raising exception.
        """
        try:
            return self.get_rate(db, base_currency, quote_currency, target_date, allow_fallback)
        except FXRateNotFoundError:
            return None

    def get_required_pairs(
            self,
            db: Session,
            portfolio_id: int,
    ) -> list[tuple[str, str]]:
        """
        Detect which currency pairs are needed for a portfolio.

        Analyzes transactions to find all unique asset currencies,
        then returns pairs needed to convert to portfolio base currency.

        Args:
            db: Database session
            portfolio_id: Portfolio to analyze

        Returns:
            List of (base_currency, quote_currency) tuples
            where quote_currency is the portfolio's base currency
        """
        # Get portfolio base currency
        portfolio = db.get(Portfolio, portfolio_id)
        if not portfolio:
            return []

        portfolio_currency = portfolio.currency.upper()

        # Get all unique asset currencies from transactions
        query = (
            select(Asset.currency)
            .join(Transaction, Transaction.asset_id == Asset.id)
            .where(Transaction.portfolio_id == portfolio_id)
            .distinct()
        )

        asset_currencies = set(db.scalars(query).all())

        # Build list of required pairs (asset_currency -> portfolio_currency)
        pairs = []
        for asset_currency in asset_currencies:
            asset_currency = asset_currency.upper()
            if asset_currency != portfolio_currency:
                pairs.append((asset_currency, portfolio_currency))

        logger.debug(f"Required FX pairs for portfolio {portfolio_id}: {pairs}")
        return pairs

    def sync_portfolio_rates(
            self,
            db: Session,
            portfolio_id: int,
            start_date: date,
            end_date: date,
            force: bool = False,
    ) -> list[FXSyncResult]:
        """
        Sync all required FX rates for a portfolio.

        Convenience method that:
        1. Detects required currency pairs
        2. Syncs rates for each pair

        Args:
            db: Database session
            portfolio_id: Portfolio to sync rates for
            start_date: Start of date range
            end_date: End of date range
            force: If True, re-fetch all dates

        Returns:
            List of FXSyncResult for each currency pair
        """
        pairs = self.get_required_pairs(db, portfolio_id)
        results = []

        for base, quote in pairs:
            result = self.sync_rates(db, base, quote, start_date, end_date, force)
            results.append(result)

        return results

    def get_coverage(
            self,
            db: Session,
            base_currency: str,
            quote_currency: str,
    ) -> dict[str, Any]:
        """
        Get coverage information for a currency pair.

        Returns:
            Dict with from_date, to_date, total_days, gaps
        """
        base = base_currency.upper().strip()
        quote = quote_currency.upper().strip()

        if base == quote:
            return {
                "base_currency": base,
                "quote_currency": quote,
                "from_date": None,
                "to_date": None,
                "total_days": 0,
                "note": "Same currency, no rates needed"
            }

        # Get min/max dates and count
        query = select(
            func.min(ExchangeRate.date),
            func.max(ExchangeRate.date),
            func.count(ExchangeRate.id),
        ).where(
            and_(
                ExchangeRate.base_currency == base,
                ExchangeRate.quote_currency == quote,
            )
        )

        result = db.execute(query).one()
        min_date, max_date, count = result

        return {
            "base_currency": base,
            "quote_currency": quote,
            "from_date": self._extract_date(min_date) if min_date else None,
            "to_date": self._extract_date(max_date) if max_date else None,
            "total_days": count,
        }

    # =========================================================================
    # PRIVATE METHODS - Yahoo Finance
    # =========================================================================

    def _fetch_rates_from_yahoo(
            self,
            base_currency: str,
            quote_currency: str,
            start_date: date,
            end_date: date,
    ) -> dict[date, Decimal]:
        """
        Fetch FX rates from Yahoo Finance.

        Args:
            base_currency: Base currency (e.g., "USD")
            quote_currency: Quote currency (e.g., "EUR")
            start_date: Start date
            end_date: End date

        Returns:
            Dict mapping date -> rate (Decimal)

        Raises:
            FXProviderError: If Yahoo Finance fails
        """
        # Build Yahoo symbol: USDEUR=X
        symbol = f"{base_currency}{quote_currency}=X"

        logger.debug(f"Fetching {symbol} from Yahoo Finance: {start_date} to {end_date}")

        try:
            ticker = yf.Ticker(symbol)

            # Yahoo needs end_date + 1 day for inclusive range
            yahoo_end = end_date + timedelta(days=1)

            # Fetch historical data
            df = ticker.history(
                start=start_date.isoformat(),
                end=yahoo_end.isoformat(),
                interval="1d",
            )

            if df.empty:
                logger.warning(f"No data returned for {symbol}")
                return {}

            # Extract close prices
            rates = {}
            for idx, row in df.iterrows():
                # idx is a Timestamp, convert to date
                rate_date = idx.date() if hasattr(idx, 'date') else idx
                close_price = row.get('Close')

                if close_price is not None and not self._is_nan(close_price):
                    # Convert to Decimal with 8 decimal places
                    rates[rate_date] = Decimal(str(close_price)).quantize(Decimal("0.00000001"))

            logger.debug(f"Fetched {len(rates)} rates for {symbol}")
            return rates

        except Exception as e:
            logger.error(f"Yahoo Finance error for {symbol}: {e}")
            raise FXProviderError(
                provider="yahoo",
                reason=f"Failed to fetch {symbol}: {e}"
            )

    @staticmethod
    def _is_nan(value: Any) -> bool:
        """Check if value is NaN."""
        try:
            import math
            return math.isnan(float(value))
        except (TypeError, ValueError):
            return False

    # =========================================================================
    # PRIVATE METHODS - Database
    # =========================================================================

    def _get_existing_dates(
            self,
            db: Session,
            base_currency: str,
            quote_currency: str,
            start_date: date,
            end_date: date,
    ) -> set[date]:
        """Get dates that already have rates in the database."""
        query = (
            select(ExchangeRate.date)
            .where(
                and_(
                    ExchangeRate.base_currency == base_currency,
                    ExchangeRate.quote_currency == quote_currency,
                    func.date(ExchangeRate.date) >= start_date,
                    func.date(ExchangeRate.date) <= end_date,
                )
            )
        )

        dates = set()
        for dt in db.scalars(query).all():
            dates.add(self._extract_date(dt))

        return dates

    def _get_exact_rate(
            self,
            db: Session,
            base_currency: str,
            quote_currency: str,
            target_date: date,
    ) -> ExchangeRate | None:
        """Get rate for exact date."""
        query = (
            select(ExchangeRate)
            .where(
                and_(
                    ExchangeRate.base_currency == base_currency,
                    ExchangeRate.quote_currency == quote_currency,
                    func.date(ExchangeRate.date) == target_date,
                )
            )
        )

        return db.scalar(query)

    def _get_fallback_rate(
            self,
            db: Session,
            base_currency: str,
            quote_currency: str,
            target_date: date,
    ) -> ExchangeRate | None:
        """
        Get the most recent rate before target_date (within fallback window).

        Looks back up to MAX_FALLBACK_DAYS to find a rate.
        """
        min_date = target_date - timedelta(days=self._max_fallback_days)

        query = (
            select(ExchangeRate)
            .where(
                and_(
                    ExchangeRate.base_currency == base_currency,
                    ExchangeRate.quote_currency == quote_currency,
                    func.date(ExchangeRate.date) >= min_date,
                    func.date(ExchangeRate.date) < target_date,
                )
            )
            .order_by(ExchangeRate.date.desc())
            .limit(1)
        )

        return db.scalar(query)

    def _upsert_rates(
            self,
            db: Session,
            base_currency: str,
            quote_currency: str,
            rates: dict[date, Decimal],
    ) -> tuple[int, int]:
        """
        Insert or update rates in the database.

        Uses PostgreSQL ON CONFLICT for efficient upsert.

        Returns:
            Tuple of (inserted_count, updated_count)
        """
        if not rates:
            return 0, 0

        # Prepare records - convert date to datetime for storage
        records = [
            {
                "base_currency": base_currency,
                "quote_currency": quote_currency,
                "date": datetime.combine(rate_date, datetime.min.time(), tzinfo=timezone.utc),
                "rate": rate,
                "provider": self.PROVIDER_NAME,
            }
            for rate_date, rate in rates.items()
        ]

        # Use PostgreSQL upsert
        stmt = pg_insert(ExchangeRate).values(records)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_exchange_rate_pair_date",
            set_={
                "rate": stmt.excluded.rate,
                "provider": stmt.excluded.provider,
            }
        )

        db.execute(stmt)
        db.commit()

        # PostgreSQL doesn't easily distinguish inserts vs updates in upsert
        return len(rates), 0

    @staticmethod
    def _extract_date(dt: datetime | date | None) -> date | None:
        """Extract date from datetime or return date as-is."""
        if dt is None:
            return None
        if isinstance(dt, datetime):
            return dt.date()
        return dt

    @staticmethod
    def _get_business_days(start_date: date, end_date: date) -> list[date]:
        """
        Get list of business days (weekdays) in range.

        FX markets are generally closed on weekends.
        """
        days = []
        current = start_date

        while current <= end_date:
            # Monday = 0, Sunday = 6
            if current.weekday() < 5:  # Monday to Friday
                days.append(current)
            current += timedelta(days=1)

        return days

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    @staticmethod
    def build_yahoo_symbol(base_currency: str, quote_currency: str) -> str:
        """Build Yahoo Finance FX symbol."""
        return f"{base_currency.upper()}{quote_currency.upper()}=X"

    @staticmethod
    def invert_rate(rate: Decimal) -> Decimal:
        """
        Invert an exchange rate.

        If rate is USD/EUR = 0.92, inverted is EUR/USD = 1.087
        """
        if rate == 0:
            raise ValueError("Cannot invert zero rate")
        return (Decimal("1") / rate).quantize(Decimal("0.00000001"))

    # =========================================================================
    # CONVERSION HELPERS
    # =========================================================================

    def convert_to_quote_currency(
            self,
            amount: Decimal,
            rate_result: FXRateResult,
    ) -> Decimal:
        """
        Convert amount FROM base currency TO quote currency.

        Uses the FX rate convention: 1 base = rate quote

        Example:
            rate_result: USD/EUR = 0.92 (1 USD = 0.92 EUR)
            amount: 100 USD
            result: 100 × 0.92 = 92 EUR

        Args:
            amount: Amount in base currency
            rate_result: FX rate lookup result

        Returns:
            Amount in quote currency
        """
        return (amount * rate_result.rate).quantize(Decimal("0.01"))

    def convert_to_base_currency(
            self,
            amount: Decimal,
            rate_result: FXRateResult,
    ) -> Decimal:
        """
        Convert amount FROM quote currency TO base currency.

        Uses the FX rate convention: 1 base = rate quote

        Example:
            rate_result: USD/EUR = 0.92 (1 USD = 0.92 EUR)
            amount: 92 EUR
            result: 92 ÷ 0.92 = 100 USD

        Args:
            amount: Amount in quote currency
            rate_result: FX rate lookup result

        Returns:
            Amount in base currency
        """
        if rate_result.rate == 0:
            raise ValueError("Cannot convert with zero rate")
        return (amount / rate_result.rate).quantize(Decimal("0.01"))

    def convert_amount(
            self,
            db: Session,
            amount: Decimal,
            from_currency: str,
            to_currency: str,
            target_date: date,
    ) -> tuple[Decimal, FXRateResult]:
        """
        Convert amount between currencies.

        This is a convenience method that:
        1. Determines which rate to fetch (from/to or to/from)
        2. Fetches the rate
        3. Applies the correct conversion

        Example:
            # Convert 100 USD to EUR on Jan 15, 2024
            eur_amount, rate = service.convert_amount(
                db, Decimal("100"), "USD", "EUR", date(2024, 1, 15)
            )

        Args:
            db: Database session
            amount: Amount to convert
            from_currency: Source currency code
            to_currency: Target currency code
            target_date: Date for FX rate lookup

        Returns:
            Tuple of (converted_amount, rate_result)

        Raises:
            FXRateNotFoundError: If no rate available
        """
        from_curr = from_currency.upper().strip()
        to_curr = to_currency.upper().strip()

        # Same currency - no conversion needed
        if from_curr == to_curr:
            return amount, FXRateResult(
                base_currency=from_curr,
                quote_currency=to_curr,
                date=target_date,
                rate=Decimal("1"),
                is_exact_match=True,
                actual_date=target_date,
            )

        # Try to get rate in the direction we need (from → to)
        # This means: 1 from_currency = X to_currency
        rate_result = self.get_rate_or_none(db, from_curr, to_curr, target_date)

        if rate_result:
            # Direct rate found: multiply
            converted = self.convert_to_quote_currency(amount, rate_result)
            return converted, rate_result

        # Try inverse direction (to → from)
        # This means: 1 to_currency = X from_currency
        inverse_result = self.get_rate_or_none(db, to_curr, from_curr, target_date)

        if inverse_result:
            # Inverse rate found: divide
            converted = self.convert_to_base_currency(amount, inverse_result)
            # Return a "virtual" rate result with the direction the caller expected
            return converted, FXRateResult(
                base_currency=from_curr,
                quote_currency=to_curr,
                date=target_date,
                rate=self.invert_rate(inverse_result.rate),
                is_exact_match=inverse_result.is_exact_match,
                actual_date=inverse_result.actual_date,
            )

        # No rate in either direction
        raise FXRateNotFoundError(from_curr, to_curr, target_date)
