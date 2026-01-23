# backend/app/services/valuation/service.py
"""
Valuation Service - Main orchestrator for portfolio valuation.

This is the single entry point for all valuation operations:
- get_valuation(): Complete portfolio valuation for a single date
- get_holdings(): Open positions as of a date
- get_history(): Time series for charts

Design Principles:
- Dependency Injection: FXRateService injected via constructor
- Single Entry Point: All valuation goes through this service
- No HTTP Knowledge: Raises domain exceptions, not HTTPException
- Composable: Uses specialized calculators for each task

Usage:
    from app.services.valuation import ValuationService

    service = ValuationService()

    # Single date valuation
    result = service.get_valuation(db, portfolio_id=1)

    # Open positions
    holdings = service.get_holdings(db, portfolio_id=1)

    # Time series for charts
    history = service.get_history(
        db, portfolio_id=1,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        interval="monthly"
    )
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select, and_, func
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    Transaction,
    Portfolio,
    MarketData,
)
from app.services.valuation.calculators import (
    HoldingsCalculator,
    CostBasisCalculator,
    ValueCalculator,
    UnrealizedPnLCalculator,
    RealizedPnLCalculator,
    CashCalculator,
)
from app.services.valuation.history_calculator import HistoryCalculator
from app.services.valuation.types import (
    HoldingPosition,
    PnLResult,
    HoldingValuation,
    PortfolioValuation,
    CashBalance,
    PortfolioHistory,
)
from app.services.constants import PRICE_FALLBACK_DAYS
from app.services.exceptions import PortfolioNotFoundError

if TYPE_CHECKING:
    from app.services.protocols import FXRateServiceProtocol

logger = logging.getLogger(__name__)


class ValuationService:
    """
    Main service for portfolio valuation operations.

    Orchestrates all valuation calculations by composing specialized
    calculators. Handles data fetching, calculation delegation, and
    result aggregation.

    Attributes:
        PRICE_FALLBACK_DAYS: Maximum days to look back for missing prices
        _fx_service: Injected FX rate service
        _holdings_calc: Calculator for position aggregation
        _cost_calc: Calculator for cost basis
        _value_calc: Calculator for current value
        _unrealized_pnl_calc: Calculator for unrealized P&L
        _realized_pnl_calc: Calculator for realized P&L
        _history_calc: Calculator for time series
    """

    def __init__(self, fx_service: FXRateServiceProtocol | None = None) -> None:
        """
        Initialize the valuation service.

        Args:
            fx_service: FX rate service for currency conversions.
                       If None, creates a new instance.
        """
        # Lazy import to avoid circular dependencies
        if fx_service is None:
            from app.services.fx_rate_service import FXRateService
            from app.services.market_data import YahooFinanceProvider
            fx_service = FXRateService(provider=YahooFinanceProvider())

        self._fx_service: FXRateServiceProtocol = fx_service

        # Initialize point-in-time calculators
        self._holdings_calc = HoldingsCalculator()
        self._cost_calc = CostBasisCalculator()
        self._value_calc = ValueCalculator(fx_service)
        self._unrealized_pnl_calc = UnrealizedPnLCalculator()
        self._realized_pnl_calc = RealizedPnLCalculator()
        self._cash_calc = CashCalculator()

        # Initialize history calculator (reuses point-in-time calculators)
        self._history_calc = HistoryCalculator(
            holdings_calc=self._holdings_calc,
            cost_calc=self._cost_calc,
            realized_pnl_calc=self._realized_pnl_calc,
            fx_service=self._fx_service,
        )

        logger.info("ValuationService initialized")

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def get_valuation(
            self,
            db: Session,
            portfolio_id: int,
            valuation_date: date | None = None,
    ) -> PortfolioValuation:
        """
        Calculate complete portfolio valuation for a single date.

        Includes both securities (holdings) and cash balances.

        Args:
            db: Database session
            portfolio_id: Portfolio to value
            valuation_date: Date to calculate (default: today)

        Returns:
            PortfolioValuation with holdings breakdown, cash, and totals

        Raises:
            ValueError: If portfolio not found
        """
        # Default to today
        if valuation_date is None:
            valuation_date = date.today()

        logger.info(
            f"Calculating valuation for portfolio {portfolio_id} "
            f"as of {valuation_date}"
        )

        # Step 1: Get portfolio
        portfolio = db.get(Portfolio, portfolio_id)
        if portfolio is None:
            raise PortfolioNotFoundError(portfolio_id)

        portfolio_currency = portfolio.currency

        # Step 2: Get ALL transactions up to valuation date
        all_transactions = self._fetch_all_transactions(db, portfolio_id, valuation_date)

        # Handle empty portfolio
        if not all_transactions:
            return PortfolioValuation(
                portfolio_id=portfolio_id,
                portfolio_name=portfolio.name,
                portfolio_currency=portfolio_currency,
                valuation_date=valuation_date,
                holdings=[],
                tracks_cash=False,
                cash_balances=[],
                total_cost_basis=Decimal("0"),
                total_value=Decimal("0"),
                total_cash=None,
                total_equity=Decimal("0"),
                total_unrealized_pnl=Decimal("0"),
                total_realized_pnl=Decimal("0"),
                total_pnl=Decimal("0"),
                warnings=["No transactions found for this portfolio"],
                has_complete_data=True,
            )

        # Step 3: Detect if portfolio tracks cash (has DEPOSIT/WITHDRAWAL)
        tracks_cash = CashCalculator.has_cash_transactions(all_transactions)

        # Step 4: Calculate cash balances (only if tracking)
        if tracks_cash:
            cash_by_currency = self._cash_calc.calculate(all_transactions, portfolio_currency)
        else:
            cash_by_currency = {}

        # Step 5: Get transactions by asset (for holdings calculation)
        transactions_by_asset, assets = self._fetch_transactions_and_assets(
            db, portfolio_id, valuation_date
        )

        # Step 5: Calculate holdings
        holdings_result = self._holdings_calc.calculate(
            transactions_by_asset=transactions_by_asset,
            assets=assets,
            portfolio_currency=portfolio_currency,
        )
        positions = holdings_result.positions

        # Step 5b: Batch fetch prices for all open positions (avoids N+1 queries)
        open_asset_ids = {p.asset_id for p in positions if p.quantity > Decimal("0")}
        price_map = self._fetch_prices_batch(db, open_asset_ids, valuation_date)

        # Step 5c: Fetch any proxy assets referenced in synthetic prices
        proxy_asset_ids = {
            proxy_id
            for (_, is_synthetic, proxy_id) in price_map.values()
            if is_synthetic and proxy_id is not None and proxy_id not in assets
        }
        if proxy_asset_ids:
            proxy_query = select(Asset).where(Asset.id.in_(proxy_asset_ids))
            for proxy_asset in db.scalars(proxy_query).all():
                assets[proxy_asset.id] = proxy_asset

        # Step 6: Value each holding
        holdings: list[HoldingValuation] = []
        total_cost_basis = Decimal("0")
        total_value = Decimal("0")
        total_unrealized_pnl = Decimal("0")
        total_realized_pnl = Decimal("0")
        all_complete = True
        portfolio_warnings: list[str] = list(holdings_result.warnings)  # Start with holdings warnings

        for position in positions:
            # For closed positions (quantity=0), only count realized P&L
            # Don't add to holdings list or try to get current value
            if position.quantity == Decimal("0"):
                # Calculate realized P&L for fully closed position
                realized_amount, _ = self._realized_pnl_calc.calculate(position)
                total_realized_pnl += realized_amount
                continue

            # For open positions, calculate full valuation
            holding = self._value_holding(
                db=db,
                position=position,
                valuation_date=valuation_date,
                portfolio_currency=portfolio_currency,
                price_map=price_map,
                assets=assets,
            )
            holdings.append(holding)

            # Aggregate totals
            total_cost_basis += holding.cost_basis.portfolio_amount
            total_realized_pnl += holding.pnl.realized_amount

            if holding.has_complete_data:
                if holding.current_value.portfolio_amount is not None:
                    total_value += holding.current_value.portfolio_amount
                if holding.pnl.unrealized_amount is not None:
                    total_unrealized_pnl += holding.pnl.unrealized_amount
            else:
                all_complete = False

        # Step 7: Convert cash to portfolio currency (only if tracking cash)
        cash_balances: list[CashBalance] = []
        total_cash: Decimal | None = None

        if tracks_cash:
            total_cash = Decimal("0")
            for currency, amount in cash_by_currency.items():
                if currency.upper() == portfolio_currency.upper():
                    # Same currency - no conversion needed
                    cash_balances.append(CashBalance(
                        currency=currency,
                        amount=amount,
                        amount_portfolio=amount,
                        fx_rate_used=Decimal("1"),
                    ))
                    total_cash += amount
                else:
                    # Need FX conversion
                    fx_result = self._fx_service.get_rate_or_none(
                        db=db,
                        base_currency=currency,
                        quote_currency=portfolio_currency,
                        target_date=valuation_date,
                        allow_fallback=True,
                    )

                    if fx_result is None:
                        all_complete = False
                        cash_balances.append(CashBalance(
                            currency=currency,
                            amount=amount,
                            amount_portfolio=None,
                            fx_rate_used=None,
                        ))
                        portfolio_warnings.append(
                            f"No FX rate for {currency}/{portfolio_currency} cash conversion"
                        )
                    else:
                        amount_portfolio = amount * fx_result.rate
                        cash_balances.append(CashBalance(
                            currency=currency,
                            amount=amount,
                            amount_portfolio=amount_portfolio.quantize(Decimal("0.01")),
                            fx_rate_used=fx_result.rate,
                        ))
                        total_cash += amount_portfolio

        # Step 8: Calculate totals
        if all_complete:
            total_pnl = total_unrealized_pnl + total_realized_pnl
            # total_equity = securities + cash (or just securities if not tracking cash)
            if tracks_cash and total_cash is not None:
                total_equity = total_value + total_cash
            else:
                total_equity = total_value
        else:
            total_pnl = None
            total_value = None
            total_equity = None
            total_unrealized_pnl = None
            if tracks_cash:
                total_cash = None
            portfolio_warnings.append(
                "Some holdings or cash have incomplete price or FX data"
            )

        # Aggregate synthetic data stats from holdings
        has_synthetic = any(h.price_is_synthetic for h in holdings)
        synthetic_count = sum(1 for h in holdings if h.price_is_synthetic)

        return PortfolioValuation(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio.name,
            portfolio_currency=portfolio_currency,
            valuation_date=valuation_date,
            holdings=holdings,
            tracks_cash=tracks_cash,
            cash_balances=cash_balances,
            total_cost_basis=total_cost_basis.quantize(Decimal("0.01")),
            total_value=(
                total_value.quantize(Decimal("0.01"))
                if total_value is not None else None
            ),
            total_cash=(
                total_cash.quantize(Decimal("0.01"))
                if total_cash is not None else None
            ),
            total_equity=(
                total_equity.quantize(Decimal("0.01"))
                if total_equity is not None else None
            ),
            total_unrealized_pnl=(
                total_unrealized_pnl.quantize(Decimal("0.01"))
                if total_unrealized_pnl is not None else None
            ),
            total_realized_pnl=total_realized_pnl.quantize(Decimal("0.01")),
            total_pnl=(
                total_pnl.quantize(Decimal("0.01"))
                if total_pnl is not None else None
            ),
            warnings=portfolio_warnings,
            has_complete_data=all_complete,
            has_synthetic_data=has_synthetic,
            synthetic_holdings_count=synthetic_count,
        )

    def get_holdings(
            self,
            db: Session,
            portfolio_id: int,
            as_of_date: date | None = None,
    ) -> list[HoldingPosition]:
        """
        Get open positions (quantity > 0) as of a date.

        This is a lightweight method that returns just the positions
        without full valuation. Useful for portfolio overview.

        Args:
            db: Database session
            portfolio_id: Portfolio to query
            as_of_date: Date to calculate holdings (default: today)

        Returns:
            List of HoldingPosition for open positions

        Raises:
            ValueError: If portfolio not found
        """
        # Default to today
        if as_of_date is None:
            as_of_date = date.today()

        # Verify portfolio exists
        portfolio = db.get(Portfolio, portfolio_id)
        if portfolio is None:
            raise PortfolioNotFoundError(portfolio_id)

        # Fetch data
        transactions_by_asset, assets = self._fetch_transactions_and_assets(
            db, portfolio_id, as_of_date
        )

        # Calculate and return holdings
        holdings_result = self._holdings_calc.calculate(
            transactions_by_asset=transactions_by_asset,
            assets=assets,
            portfolio_currency=portfolio.currency,
        )
        # Note: warnings are logged but not returned from this lightweight method
        # Full warnings are available via get_valuation() which includes them in PortfolioValuation
        return holdings_result.positions

    def get_history(
            self,
            db: Session,
            portfolio_id: int,
            start_date: date,
            end_date: date,
            interval: str = "daily",
    ) -> PortfolioHistory:
        """
        Get portfolio valuation history (time series).

        Optimized for charting with batch data fetching.

        Args:
            db: Database session
            portfolio_id: Portfolio to query
            start_date: First date in series
            end_date: Last date in series
            interval: "daily", "weekly", or "monthly"

        Returns:
            PortfolioHistory with time series data

        Raises:
            ValueError: If portfolio not found or invalid interval
        """
        logger.info(
            f"Calculating history for portfolio {portfolio_id} "
            f"from {start_date} to {end_date} ({interval})"
        )

        return self._history_calc.calculate(
            db=db,
            portfolio_id=portfolio_id,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )

    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================

    def _fetch_all_transactions(
            self,
            db: Session,
            portfolio_id: int,
            as_of_date: date,
    ) -> list[Transaction]:
        """
        Fetch ALL transactions for a portfolio up to a date.

        Includes DEPOSIT, WITHDRAWAL, BUY, SELL - everything needed
        for both holdings and cash calculations.

        Returns:
            List of transactions ordered by date
        """
        query = (
            select(Transaction)
            .where(
                and_(
                    Transaction.portfolio_id == portfolio_id,
                    Transaction.date <= as_of_date,
                )
            )
            .order_by(Transaction.date)
        )
        return list(db.scalars(query).all())

    def _fetch_transactions_and_assets(
            self,
            db: Session,
            portfolio_id: int,
            as_of_date: date,
    ) -> tuple[dict[int, list[Transaction]], dict[int, Asset]]:
        """
        Fetch transactions and related assets for a portfolio.

        Returns:
            Tuple of (transactions_by_asset, assets_by_id)
        """
        # Fetch transactions
        query = (
            select(Transaction)
            .where(
                and_(
                    Transaction.portfolio_id == portfolio_id,
                    Transaction.date <= as_of_date,
                )
            )
            .order_by(Transaction.date)
        )
        transactions = list(db.scalars(query).all())

        if not transactions:
            return {}, {}

        # Group by asset (skip non-asset transactions)
        transactions_by_asset: dict[int, list[Transaction]] = {}
        asset_ids: set[int] = set()

        for txn in transactions:
            if txn.asset_id is None:
                continue
            if txn.asset_id not in transactions_by_asset:
                transactions_by_asset[txn.asset_id] = []
            transactions_by_asset[txn.asset_id].append(txn)
            asset_ids.add(txn.asset_id)

        if not asset_ids:
            return {}, {}

        # Fetch assets
        assets_query = select(Asset).where(Asset.id.in_(asset_ids))
        assets = {asset.id: asset for asset in db.scalars(assets_query).all()}

        return transactions_by_asset, assets

    def _fetch_prices_batch(
            self,
            db: Session,
            asset_ids: set[int],
            target_date: date,
    ) -> dict[tuple[int, date], tuple[Decimal, bool, int | None]]:
        """
        Batch fetch prices for multiple assets with fallback date range.

        Fetches all prices from (target_date - PRICE_FALLBACK_DAYS) to target_date
        for all given asset_ids in a single query.

        Args:
            db: Database session
            asset_ids: Set of asset IDs to fetch prices for
            target_date: The target valuation date

        Returns:
            Dict mapping (asset_id, date) -> (close_price, is_synthetic, proxy_source_id)
        """
        if not asset_ids:
            return {}

        # Calculate extended date range for fallback
        start_date = target_date - timedelta(days=PRICE_FALLBACK_DAYS)

        query = (
            select(MarketData)
            .where(
                and_(
                    MarketData.asset_id.in_(asset_ids),
                    MarketData.date >= start_date,
                    MarketData.date <= target_date,
                    MarketData.no_data_available == False,  # Exclude no-data markers
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

        return price_map

    def _lookup_price_with_fallback(
            self,
            price_map: dict[tuple[int, date], tuple[Decimal, bool, int | None]],
            asset_id: int,
            target_date: date,
    ) -> tuple[Decimal | None, date | None, bool, int | None]:
        """
        Look up price from pre-fetched map with fallback for weekends/holidays.

        Args:
            price_map: Pre-fetched prices from _fetch_prices_batch
            asset_id: Asset to look up
            target_date: Target date

        Returns:
            Tuple of (price, price_date, is_synthetic, proxy_source_id)
            All None if not found within fallback window.
        """
        for days_back in range(PRICE_FALLBACK_DAYS + 1):
            check_date = target_date - timedelta(days=days_back)
            price_data = price_map.get((asset_id, check_date))
            if price_data is not None:
                return price_data[0], check_date, price_data[1], price_data[2]

        return None, None, False, None

    def _value_holding(
            self,
            db: Session,
            position: HoldingPosition,
            valuation_date: date,
            portfolio_currency: str,
            price_map: dict[tuple[int, date], tuple[Decimal, bool, int | None]],
            assets: dict[int, Asset],
    ) -> HoldingValuation:
        """
        Calculate complete valuation for a single holding.

        Combines all calculators to produce full HoldingValuation.

        Args:
            db: Database session (for FX lookups only)
            position: The holding position to value
            valuation_date: Date for valuation
            portfolio_currency: Portfolio's base currency
            price_map: Pre-fetched prices from _fetch_prices_batch
            assets: Pre-fetched assets dict (includes proxy assets)
        """
        warnings: list[str] = []

        # Cost basis
        cost_basis = self._cost_calc.calculate(position, portfolio_currency)

        # Get price (with fallback for weekends/holidays) - uses pre-fetched data
        price, price_date, is_synthetic, proxy_source_id = self._lookup_price_with_fallback(
            price_map, position.asset_id, valuation_date
        )

        # Get proxy ticker if synthetic - uses pre-fetched assets
        proxy_ticker: str | None = None
        proxy_exchange: str | None = None
        if is_synthetic and proxy_source_id:
            proxy_asset = assets.get(proxy_source_id)
            if proxy_asset:
                proxy_ticker = proxy_asset.ticker
                proxy_exchange = proxy_asset.exchange

        # Current value
        current_value = self._value_calc.calculate(
            db=db,
            position=position,
            price=price,
            price_date=price_date,
            portfolio_currency=portfolio_currency,
        )
        warnings.extend(current_value.warnings)

        # Unrealized P&L
        unrealized_amount, unrealized_pct = self._unrealized_pnl_calc.calculate(
            cost_basis_portfolio=cost_basis.portfolio_amount,
            current_value_portfolio=current_value.portfolio_amount,
        )

        # Realized P&L
        realized_amount, realized_pct = self._realized_pnl_calc.calculate(position)

        # Total P&L
        if unrealized_amount is not None:
            total_amount = unrealized_amount + realized_amount
            if cost_basis.portfolio_amount > Decimal("0"):
                total_pct = (
                        total_amount / cost_basis.portfolio_amount
                ).quantize(Decimal("0.0001"))
            else:
                total_pct = None
        else:
            total_amount = None
            total_pct = None

        pnl = PnLResult(
            unrealized_amount=unrealized_amount,
            unrealized_percentage=unrealized_pct,
            realized_amount=realized_amount,
            realized_percentage=realized_pct,
            total_amount=total_amount,
            total_percentage=total_pct,
        )

        has_complete_data = current_value.has_complete_data

        # Determine price source
        if price is None:
            price_source = "unavailable"
        elif is_synthetic:
            price_source = "proxy_backcast"
        else:
            price_source = "market"

        return HoldingValuation(
            asset_id=position.asset_id,
            ticker=position.asset.ticker,
            exchange=position.asset.exchange,
            asset_name=position.asset.name,
            asset_class=position.asset.asset_class.value,
            asset_currency=position.asset.currency,
            quantity=position.quantity,
            cost_basis=cost_basis,
            current_value=current_value,
            pnl=pnl,
            warnings=warnings,
            has_complete_data=has_complete_data,
            price_is_synthetic=is_synthetic,
            price_source=price_source,
            proxy_ticker=proxy_ticker,
            proxy_exchange=proxy_exchange,
        )

