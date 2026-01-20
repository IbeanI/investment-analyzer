# backend/app/services/valuation/history_calculator.py
"""
History Calculator for time series portfolio valuation.

This calculator generates portfolio value time series efficiently by:
1. Batch-fetching all prices and FX rates upfront (3 queries total)
2. Iterating through dates using in-memory lookups
3. Recalculating holdings at each date (positions change over time)

Performance Optimization:
    Instead of N database queries for N dates, we use:
    - 1 query for all transactions
    - 1 query for all prices in date range
    - 1 query for all FX rates in date range
    Then iterate in memory.

Design Principles:
- Batch operations where possible
- Graceful handling of missing data
- Clear separation of data fetching and calculation
- Reuses point-in-time calculators for consistency
"""

from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    Transaction,
    MarketData,
    ExchangeRate,
    Portfolio,
)
from app.services.valuation.calculators import (
    HoldingsCalculator,
    CostBasisCalculator,
    RealizedPnLCalculator,
)
from app.services.valuation.types import (
    HistoryPoint,
    PortfolioHistory,
)

if TYPE_CHECKING:
    from app.services.fx_rate_service import FXRateService

logger = logging.getLogger(__name__)


class HistoryCalculator:
    """
    Calculates portfolio valuation history (time series).

    Generates a series of data points showing portfolio value over time.
    Optimized for efficiency with batch data fetching.

    Key Insight:
        Holdings CHANGE over time as buys/sells occur. So we can't
        just fetch today's holdings and apply historical prices.
        We must recalculate holdings for each date in the series.

    Optimization Strategy:
        1. Fetch ALL data upfront in 3 queries
        2. Build in-memory lookup maps
        3. For each date: filter transactions, calculate holdings, apply prices

    Attributes:
        _holdings_calc: Calculator for position aggregation
        _cost_calc: Calculator for cost basis
        _realized_pnl_calc: Calculator for realized P&L
        _fx_service: Service for FX rate lookups (used for batch fetch)
    """

    # Maximum days to look back for missing prices (weekends/holidays)
    PRICE_FALLBACK_DAYS: int = 5

    # Maximum days to look back for missing FX rates
    FX_FALLBACK_DAYS: int = 7

    def __init__(
            self,
            holdings_calc: HoldingsCalculator,
            cost_calc: CostBasisCalculator,
            realized_pnl_calc: RealizedPnLCalculator,
            fx_service: FXRateService,
    ) -> None:
        """
        Initialize with calculator dependencies.

        Note: We don't use ValueCalculator here because we do batch
        price/FX lookups instead of individual queries.
        """
        self._holdings_calc = holdings_calc
        self._cost_calc = cost_calc
        self._realized_pnl_calc = realized_pnl_calc
        self._fx_service = fx_service

    def calculate(
            self,
            db: Session,
            portfolio_id: int,
            start_date: date,
            end_date: date,
            interval: str = "daily",
    ) -> PortfolioHistory:
        """
        Calculate portfolio valuation history using the Rolling State pattern.

        Complexity: O(D + T) where D = number of dates, T = number of transactions.
        NOT O(D * T) like the naive approach!

        Args:
            db: Database session
            portfolio_id: Portfolio to calculate history for
            start_date: First date in the series
            end_date: Last date in the series
            interval: "daily", "weekly", or "monthly"

        Returns:
            PortfolioHistory with time series data
        """
        warnings: list[str] = []

        # Step 0: Get portfolio
        portfolio = db.get(Portfolio, portfolio_id)
        if portfolio is None:
            raise ValueError(f"Portfolio {portfolio_id} not found")

        portfolio_currency = portfolio.currency

        # Step 1: Get ALL transactions up to end_date, SORTED BY DATE
        transactions = self._fetch_transactions(db, portfolio_id, end_date)

        if not transactions:
            return PortfolioHistory(
                portfolio_id=portfolio_id,
                portfolio_currency=portfolio_currency,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
                tracks_cash=False,
                data=[],
                warnings=["No transactions found for this portfolio"],
            )

        # Step 2: Detect if portfolio tracks cash
        from app.services.valuation.calculators import CashCalculator
        tracks_cash = CashCalculator.has_cash_transactions(transactions)

        # Step 3: Identify all assets involved and fetch them
        asset_ids = list({txn.asset_id for txn in transactions if txn.asset_id is not None})

        # Step 4: Batch fetch ALL prices in date range
        price_map = self._fetch_prices_batch(db, asset_ids, start_date, end_date)

        # Step 4b: Collect proxy asset IDs from synthetic prices and add to asset fetch
        proxy_asset_ids = {
            proxy_id
            for (price, is_synthetic, proxy_id) in price_map.values()
            if is_synthetic and proxy_id is not None
        }
        all_asset_ids = set(asset_ids) | proxy_asset_ids
        assets = self._fetch_assets(db, list(all_asset_ids))

        # Step 5: Batch fetch ALL FX rates in date range
        currencies_needed = {
            asset.currency
            for asset in assets.values()
            if asset.currency.upper() != portfolio_currency.upper()
        }
        fx_map = self._fetch_fx_rates_batch(
            db, currencies_needed, portfolio_currency, start_date, end_date
        )

        # Step 6: Generate target dates based on interval (SORTED)
        target_dates = self._generate_dates(start_date, end_date, interval)

        # Step 7: ROLLING STATE - O(D + T) algorithm
        data_points = self._calculate_history_rolling(
            transactions=transactions,
            assets=assets,
            portfolio_currency=portfolio_currency,
            target_dates=target_dates,
            price_map=price_map,
            fx_map=fx_map,
            tracks_cash=tracks_cash,
        )

        # Check for incomplete data
        incomplete_count = sum(1 for p in data_points if not p.has_complete_data)
        if incomplete_count > 0:
            warnings.append(
                f"{incomplete_count} of {len(data_points)} data points have "
                f"incomplete price or FX data"
            )

        # Aggregate synthetic data statistics across all data points
        has_synthetic = any(point.has_synthetic_data for point in data_points)

        # Collect all synthetic holdings and their proxies
        all_synthetic_holdings: dict[str, str | None] = {}
        synthetic_dates: list[date] = []
        total_lookups = 0
        synthetic_lookups = 0

        # Per-asset tracking for detailed stats
        # Structure: {ticker: {"proxy": str, "synthetic_dates": [date], "total_dates": [date]}}
        asset_tracking: dict[str, dict] = {}

        for point in data_points:
            # Count price lookups (one per active holding per day)
            total_lookups += point.holdings_count
            synthetic_lookups += len(point.synthetic_holdings)

            # Track which assets were present on this day
            for ticker, proxy in point.synthetic_holdings.items():
                if ticker not in asset_tracking:
                    asset_tracking[ticker] = {
                        "proxy": proxy,
                        "synthetic_dates": [],
                        "total_dates": [],
                    }
                asset_tracking[ticker]["synthetic_dates"].append(point.date)
                asset_tracking[ticker]["total_dates"].append(point.date)

                # Keep first proxy seen
                if ticker not in all_synthetic_holdings:
                    all_synthetic_holdings[ticker] = proxy

            if point.has_synthetic_data:
                synthetic_dates.append(point.date)

        # Also track total days held for assets (including non-synthetic days)
        # We need to scan all holdings across all days
        for point in data_points:
            for ticker in point.synthetic_holdings.keys():
                # Already tracked above
                pass
            # For non-synthetic holdings on this day, we need holdings info
            # This is implicitly tracked via holdings_count but we don't have tickers
            # For now, we'll only have accurate total_days for assets WITH synthetic data

        # Calculate date range of synthetic data usage
        synthetic_date_range: tuple[date, date] | None = None
        if synthetic_dates:
            synthetic_date_range = (min(synthetic_dates), max(synthetic_dates))

        # Build per-asset synthetic details
        from app.services.valuation.types import SyntheticAssetDetail
        synthetic_details: dict[str, SyntheticAssetDetail] = {}

        for ticker, tracking in asset_tracking.items():
            if tracking["synthetic_dates"]:
                synthetic_details[ticker] = SyntheticAssetDetail(
                    ticker=ticker,
                    proxy_ticker=tracking["proxy"],
                    first_synthetic_date=min(tracking["synthetic_dates"]),
                    last_synthetic_date=max(tracking["synthetic_dates"]),
                    synthetic_days=len(tracking["synthetic_dates"]),
                    total_days_held=len(tracking["synthetic_dates"]),  # Only synthetic days known
                )

        return PortfolioHistory(
            portfolio_id=portfolio_id,
            portfolio_currency=portfolio_currency,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
            tracks_cash=tracks_cash,
            data=data_points,
            warnings=warnings,
            has_synthetic_data=has_synthetic,
            synthetic_holdings=all_synthetic_holdings,
            synthetic_date_range=synthetic_date_range,
            synthetic_lookups=synthetic_lookups,
            total_lookups=total_lookups,
            synthetic_details=synthetic_details,
        )

    def _calculate_history_rolling(
            self,
            transactions: list[Transaction],
            assets: dict[int, Asset],
            portfolio_currency: str,
            target_dates: list[date],
            price_map: dict[tuple[int, date], tuple[Decimal, bool, int | None]],
            fx_map: dict[tuple[str, str, date], Decimal],
            tracks_cash: bool,
    ) -> list[HistoryPoint]:
        """
        Calculate history using the Rolling State pattern.

        Instead of filtering all transactions for each date (O(D*T)),
        we iterate through sorted dates and apply only NEW transactions
        since the last snapshot (O(D+T)).

        Args:
            transactions: ALL transactions, already sorted by date
            assets: Asset lookup dict
            portfolio_currency: Portfolio's base currency
            target_dates: Dates to generate points for (must be sorted)
            price_map: Batch-fetched prices
            fx_map: Batch-fetched FX rates
            tracks_cash: True if portfolio tracks cash (has DEPOSIT/WITHDRAWAL)

        Returns:
            List of HistoryPoint in chronological order
        """
        data_points: list[HistoryPoint] = []

        # Rolling state - mutated as we process transactions
        holdings_state: dict[int, dict] = {}  # asset_id -> position aggregates
        cash_state: dict[str, Decimal] = {}  # currency -> balance (only used if tracks_cash)

        # Transaction iterator
        txn_index = 0
        num_txns = len(transactions)

        # Import calculator methods for state updates (only if tracking cash)
        cash_calc = None
        if tracks_cash:
            from app.services.valuation.calculators import CashCalculator
            cash_calc = CashCalculator()

        for target_date in target_dates:
            # === PHASE 1: Apply all transactions up to and including target_date ===
            while txn_index < num_txns:
                txn = transactions[txn_index]
                txn_date = self._transaction_date(txn)

                if txn_date > target_date:
                    break  # This transaction is in the future

                # Apply transaction to holdings state
                if txn.asset_id is not None:
                    asset = assets.get(txn.asset_id)
                    if asset:
                        self._holdings_calc.apply_transaction(
                            holdings_state, txn, asset
                        )

                # Apply transaction to cash state (only if tracking)
                if tracks_cash and cash_calc is not None:
                    cash_calc.calculate_with_state(cash_state, txn)

                txn_index += 1

            # === PHASE 2: Snapshot - Calculate values at this date ===
            point = self._snapshot_state(
                holdings_state=holdings_state,
                cash_state=cash_state if tracks_cash else {},
                portfolio_currency=portfolio_currency,
                target_date=target_date,
                price_map=price_map,
                fx_map=fx_map,
                tracks_cash=tracks_cash,
                assets=assets,
            )
            data_points.append(point)

        return data_points

    def _snapshot_state(
            self,
            holdings_state: dict[int, dict],
            cash_state: dict[str, Decimal],
            portfolio_currency: str,
            target_date: date,
            price_map: dict[tuple[int, date], tuple[Decimal, bool, int | None]],
            fx_map: dict[tuple[str, str, date], Decimal],
            tracks_cash: bool,
            assets: dict[int, Asset],
    ) -> HistoryPoint:
        """
        Take a snapshot of current state and calculate valuation.

        Args:
            holdings_state: Current holdings state
            cash_state: Current cash balances by currency (empty if not tracking)
            portfolio_currency: Portfolio's base currency
            target_date: Date for this snapshot
            price_map: Batch-fetched prices
            fx_map: Batch-fetched FX rates
            tracks_cash: True if portfolio tracks cash

        Returns:
            HistoryPoint for this date
        """
        # Convert state to positions
        positions = self._holdings_calc.state_to_positions(holdings_state)

        # If no positions and no cash, return zero point
        if not positions and not cash_state:
            return HistoryPoint(
                date=target_date,
                value=Decimal("0"),
                cash=Decimal("0") if tracks_cash else None,
                equity=Decimal("0"),
                cost_basis=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
                total_pnl=Decimal("0"),
                has_complete_data=True,
                has_synthetic_data=False,
                synthetic_holdings={},
                holdings_count=0,
            )

        # Calculate totals
        total_cost = Decimal("0")
        total_value = Decimal("0")
        total_realized = Decimal("0")
        all_complete = True

        # Track synthetic data for this day
        day_has_synthetic = False
        synthetic_holdings_map: dict[str, str | None] = {}  # {ticker: proxy_ticker}

        # Track the latest price date for consistent FX lookups
        latest_price_date: date | None = None

        for position in positions:
            # Cost basis (will be 0 for closed positions)
            cost_result = self._cost_calc.calculate(position, portfolio_currency)
            total_cost += cost_result.portfolio_amount

            # Realized P&L (calculated for all positions with sales)
            realized_pnl, _ = self._realized_pnl_calc.calculate(position)
            total_realized += realized_pnl

            # Skip current value calculation for closed positions
            # (quantity=0 means nothing to value, but we still counted realized P&L)
            if position.quantity == Decimal("0"):
                continue

            # Current value (using batch-fetched data with synthetic info)
            price, price_date, is_synthetic, proxy_source_id = self._lookup_price_with_fallback(
                price_map, position.asset_id, target_date
            )

            if price is None or price_date is None:
                all_complete = False
                continue

            # Track synthetic data
            if is_synthetic:
                day_has_synthetic = True
                # Get proxy ticker from proxy_source_id
                proxy_ticker: str | None = None
                if proxy_source_id and proxy_source_id in assets:
                    proxy_ticker = assets[proxy_source_id].ticker
                synthetic_holdings_map[position.asset.ticker] = proxy_ticker

                # Track the latest price date found (for cash FX consistency)
            if latest_price_date is None or price_date > latest_price_date:
                latest_price_date = price_date

            # Calculate local value
            value_local = position.quantity * price

            # FX conversion - use price_date for consistency
            asset_currency = position.asset.currency.upper()
            if asset_currency == portfolio_currency.upper():
                total_value += value_local
            else:
                fx_rate = self._lookup_fx_with_fallback(
                    fx_map, asset_currency, portfolio_currency, price_date
                )
                if fx_rate is None:
                    all_complete = False
                    continue
                total_value += value_local * fx_rate

        # Calculate total cash in portfolio currency (only if tracking)
        total_cash: Decimal | None = None
        if tracks_cash:
            total_cash = Decimal("0")
            # Use latest_price_date for cash FX to ensure consistency,
            # fall back to target_date if no prices were found
            fx_reference_date = latest_price_date or target_date
            for currency, balance in cash_state.items():
                if currency.upper() == portfolio_currency.upper():
                    total_cash += balance
                else:
                    fx_rate = self._lookup_fx_with_fallback(
                        fx_map, currency.upper(), portfolio_currency, fx_reference_date
                    )
                    if fx_rate is None:
                        all_complete = False
                    else:
                        total_cash += balance * fx_rate

        # Calculate P&L and equity
        if all_complete:
            unrealized = total_value - total_cost
            total_pnl = unrealized + total_realized
            final_value = total_value
            final_cash = total_cash  # None if not tracking
            if tracks_cash and total_cash is not None:
                final_equity = final_value + total_cash
            else:
                final_equity = final_value
        else:
            unrealized = None
            total_pnl = None
            final_value = None
            final_cash = None if tracks_cash else None  # stays None
            final_equity = None

        # Count active holdings (non-zero quantity)
        active_holdings_count = sum(1 for p in positions if p.quantity > Decimal("0"))

        return HistoryPoint(
            date=target_date,
            value=final_value.quantize(Decimal("0.01")) if final_value is not None else None,
            cash=final_cash.quantize(Decimal("0.01")) if final_cash is not None else None,
            equity=final_equity.quantize(Decimal("0.01")) if final_equity is not None else None,
            cost_basis=total_cost.quantize(Decimal("0.01")),
            unrealized_pnl=unrealized.quantize(Decimal("0.01")) if unrealized is not None else None,
            realized_pnl=total_realized.quantize(Decimal("0.01")),
            total_pnl=total_pnl.quantize(Decimal("0.01")) if total_pnl is not None else None,
            has_complete_data=all_complete,
            has_synthetic_data=day_has_synthetic,
            synthetic_holdings=synthetic_holdings_map,
            holdings_count=active_holdings_count,
        )

    # =========================================================================
    # DATA FETCHING (Batch Operations)
    # =========================================================================

    def _fetch_transactions(
            self,
            db: Session,
            portfolio_id: int,
            end_date: date,
    ) -> list[Transaction]:
        """
        Fetch all transactions for portfolio up to end_date.

        Returns transactions ordered by date for correct processing.
        """
        query = (
            select(Transaction)
            .where(
                and_(
                    Transaction.portfolio_id == portfolio_id,
                    Transaction.date <= end_date,
                )
            )
            .order_by(Transaction.date)
        )
        return list(db.scalars(query).all())

    def _fetch_assets(
            self,
            db: Session,
            asset_ids: list[int],
    ) -> dict[int, Asset]:
        """
        Fetch all assets by ID.

        Returns dict mapping asset_id -> Asset.
        """
        if not asset_ids:
            return {}

        query = select(Asset).where(Asset.id.in_(asset_ids))
        assets = db.scalars(query).all()
        return {asset.id: asset for asset in assets}

    def _fetch_prices_batch(
            self,
            db: Session,
            asset_ids: list[int],
            start_date: date,
            end_date: date,
    ) -> dict[tuple[int, date], tuple[Decimal, bool, int | None]]:
        """
        Batch fetch all prices for given assets in date range.

        IMPORTANT: Extends the fetch range backwards by PRICE_FALLBACK_DAYS
        to enable fallback lookups for weekends/holidays at the start of
        the requested range.

        Returns dict mapping (asset_id, date) -> (close_price, is_synthetic, proxy_source_id)
        """
        if not asset_ids:
            return {}

        # Extend range backwards to include potential fallback prices
        # This ensures we have data for weekends/holidays at range start
        extended_start = start_date - timedelta(days=self.PRICE_FALLBACK_DAYS)

        query = (
            select(MarketData)
            .where(
                and_(
                    MarketData.asset_id.in_(asset_ids),
                    MarketData.date >= extended_start,
                    MarketData.date <= end_date,
                )
            )
        )

        price_map: dict[tuple[int, date], tuple[Decimal, bool, int | None]] = {}
        for record in db.scalars(query).all():
            # Handle both date and datetime
            record_date = (
                record.date.date()
                if hasattr(record.date, 'date')
                else record.date
            )
            price_map[(record.asset_id, record_date)] = (
                record.close_price,
                record.is_synthetic,
                record.proxy_source_id,
            )

        logger.debug(
            f"Fetched {len(price_map)} price records for {len(asset_ids)} assets "
            f"(extended range: {extended_start} to {end_date})"
        )
        return price_map

    def _fetch_fx_rates_batch(
            self,
            db: Session,
            currencies: set[str],
            portfolio_currency: str,
            start_date: date,
            end_date: date,
    ) -> dict[tuple[str, str, date], Decimal]:
        """
        Batch fetch all FX rates for given currencies in date range.

        IMPORTANT: Extends the fetch range backwards by FX_FALLBACK_DAYS
        to enable fallback lookups for weekends/holidays at the start of
        the requested range.

        Returns dict mapping (base_currency, quote_currency, date) -> rate
        """
        if not currencies:
            return {}

        # Extend range backwards to include potential fallback rates
        extended_start = start_date - timedelta(days=self.FX_FALLBACK_DAYS)

        query = (
            select(ExchangeRate)
            .where(
                and_(
                    ExchangeRate.base_currency.in_(currencies),
                    ExchangeRate.quote_currency == portfolio_currency.upper(),
                    ExchangeRate.date >= extended_start,  # CHANGED
                    ExchangeRate.date <= end_date,
                )
            )
        )

        fx_map: dict[tuple[str, str, date], Decimal] = {}
        for record in db.scalars(query).all():
            # Handle both date and datetime
            record_date = (
                record.date.date()
                if hasattr(record.date, 'date')
                else record.date
            )
            fx_map[(
                record.base_currency.upper(),
                record.quote_currency.upper(),
                record_date
            )] = record.rate

        logger.debug(
            f"Fetched {len(fx_map)} FX rate records for {len(currencies)} currencies "
            f"(extended range: {extended_start} to {end_date})"
        )
        return fx_map

    # =========================================================================
    # DATE GENERATION
    # =========================================================================

    def _generate_dates(
            self,
            start_date: date,
            end_date: date,
            interval: str,
    ) -> list[date]:
        """
        Generate list of dates based on interval.

        Args:
            start_date: First date
            end_date: Last date
            interval: "daily", "weekly", or "monthly"

        Returns:
            List of dates in chronological order
        """
        if interval == "daily":
            return self._generate_daily(start_date, end_date)
        elif interval == "weekly":
            return self._generate_weekly(start_date, end_date)
        elif interval == "monthly":
            return self._generate_monthly(start_date, end_date)
        else:
            raise ValueError(f"Invalid interval: {interval}. Use daily, weekly, or monthly.")

    def _generate_daily(self, start: date, end: date) -> list[date]:
        """Generate daily data points (every calendar day)."""
        dates = []
        current = start
        while current <= end:
            dates.append(current)
            current += timedelta(days=1)
        return dates

    def _generate_weekly(self, start: date, end: date) -> list[date]:
        """
        Generate weekly data points (Fridays or last trading day).

        Strategy: Find each Friday in the range. If the range doesn't
        end on a Friday, include the end date.
        """
        dates = []
        current = start

        # Find first Friday on or after start
        days_until_friday = (4 - current.weekday()) % 7
        if days_until_friday == 0 and current.weekday() != 4:
            days_until_friday = 7
        current = current + timedelta(days=days_until_friday)

        # Skip to first Friday if start is after it
        if current < start:
            current += timedelta(days=7)

        # Collect all Fridays
        while current <= end:
            dates.append(current)
            current += timedelta(days=7)

        # Always include end date if not already included
        if dates and dates[-1] != end:
            dates.append(end)
        elif not dates:
            dates.append(end)

        return dates

    def _generate_monthly(self, start: date, end: date) -> list[date]:
        """
        Generate monthly data points (last day of each month).

        Strategy: For each month in the range, use the last calendar day.
        Always include the end date.
        """
        dates = []

        # Start from the first month
        current_year = start.year
        current_month = start.month

        while True:
            # Get last day of current month
            last_day = calendar.monthrange(current_year, current_month)[1]
            month_end = date(current_year, current_month, last_day)

            # Only include if within our range
            if month_end >= start and month_end <= end:
                dates.append(month_end)
            elif month_end > end:
                break

            # Move to next month
            if current_month == 12:
                current_month = 1
                current_year += 1
            else:
                current_month += 1

            # Safety check
            if current_year > end.year + 1:
                break

        # Always include end date if not already included
        if dates and dates[-1] != end:
            dates.append(end)
        elif not dates:
            dates.append(end)

        return dates

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _transaction_date(self, txn: Transaction) -> date:
        """Extract date from transaction (handles datetime vs date)."""
        if hasattr(txn.date, 'date'):
            return txn.date.date()
        return txn.date

    def _lookup_price_with_fallback(
            self,
            price_map: dict[tuple[int, date], tuple[Decimal, bool, int | None]],
            asset_id: int,
            target_date: date,
            max_fallback_days: int | None = None,
    ) -> tuple[Decimal | None, date | None, bool, int | None]:
        """
        Look up price with fallback to recent dates.

        For weekends/holidays, looks back up to max_fallback_days.

        Returns:
            Tuple of (price, actual_date, is_synthetic, proxy_source_id).
            Price and date are None if no price found within fallback window.
        """
        if max_fallback_days is None:
            max_fallback_days = self.PRICE_FALLBACK_DAYS

        # Try exact date first
        price_data = price_map.get((asset_id, target_date))
        if price_data is not None:
            return price_data[0], target_date, price_data[1], price_data[2]

        # Fallback to recent dates
        for days_back in range(1, max_fallback_days + 1):
            fallback_date = target_date - timedelta(days=days_back)
            price_data = price_map.get((asset_id, fallback_date))
            if price_data is not None:
                return price_data[0], fallback_date, price_data[1], price_data[2]

        return None, None, False, None

    def _lookup_fx_with_fallback(
            self,
            fx_map: dict[tuple[str, str, date], Decimal],
            base_currency: str,
            quote_currency: str,
            target_date: date,
            max_fallback_days: int | None = None,
    ) -> Decimal | None:
        """
        Look up FX rate with fallback to recent dates.

        For weekends/holidays, looks back up to max_fallback_days.
        """
        if max_fallback_days is None:
            max_fallback_days = self.FX_FALLBACK_DAYS

        # Try exact date first
        rate = fx_map.get((base_currency, quote_currency.upper(), target_date))
        if rate is not None:
            return rate

        # Fallback to recent dates
        for days_back in range(1, max_fallback_days + 1):
            fallback_date = target_date - timedelta(days=days_back)
            rate = fx_map.get((base_currency, quote_currency.upper(), fallback_date))
            if rate is not None:
                return rate

        return None
