# backend/app/services/valuation/calculators.py
"""
Point-in-time valuation calculators.

Each calculator follows the Single Responsibility Principle:
- HoldingsCalculator: Aggregates transactions into positions
- CostBasisCalculator: Calculates cost basis for a position
- ValueCalculator: Calculates current value with FX conversion
- UnrealizedPnLCalculator: Calculates unrealized P&L
- RealizedPnLCalculator: Calculates realized P&L

Design Principles:
- Each calculator does ONE thing well
- Stateless (no instance state, pure functions)
- Receives all dependencies explicitly
- Returns structured result objects
- Uses Decimal for ALL financial calculations

Usage:
    holdings_calc = HoldingsCalculator()
    positions = holdings_calc.calculate(
        transactions_by_asset={...},
        assets={...},
        portfolio_currency="EUR"
    )
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.models import Asset, Transaction, TransactionType
from app.services.valuation.types import (
    HoldingPosition,
    CostBasisResult,
    ValueResult,
)

if TYPE_CHECKING:
    from app.services.fx_rate_service import FXRateService

logger = logging.getLogger(__name__)


# =============================================================================
# HOLDINGS CALCULATOR
# =============================================================================

class HoldingsCalculator:
    """
    Calculates portfolio positions from transactions.

    Aggregates all buy/sell transactions for each asset to determine:
    - Current quantity held
    - Total bought/sold quantities
    - Cost basis components (in both local and portfolio currency)
    - Sale proceeds (for realized P&L calculation)

    Note:
        Only returns positions where quantity > 0 (open positions).
        Fully closed positions (quantity = 0) are excluded.
    """

    def calculate(
            self,
            transactions_by_asset: dict[int, list[Transaction]],
            assets: dict[int, Asset],
            portfolio_currency: str,
    ) -> list[HoldingPosition]:
        """
        Calculate holdings from grouped transactions.

        Args:
            transactions_by_asset: Transactions grouped by asset_id
            assets: Asset objects keyed by asset_id
            portfolio_currency: Portfolio's base currency

        Returns:
            List of HoldingPosition for assets with quantity > 0
        """
        positions: list[HoldingPosition] = []

        for asset_id, transactions in transactions_by_asset.items():
            asset = assets.get(asset_id)
            if asset is None:
                logger.warning(f"Asset {asset_id} not found, skipping")
                continue

            position = self._calculate_position(
                asset=asset,
                transactions=transactions,
                portfolio_currency=portfolio_currency,
            )

            # Only include open positions (quantity > 0)
            if position.has_position:
                positions.append(position)

        return positions

    def _calculate_position(
            self,
            asset: Asset,
            transactions: list[Transaction],
            portfolio_currency: str,
    ) -> HoldingPosition:
        """
        Calculate position for a single asset from its transactions.

        Cost calculation (BUY):
            cost_local = quantity × price_per_share + fee
            cost_portfolio = cost_local ÷ exchange_rate

        Proceeds calculation (SELL):
            proceeds_local = quantity × price_per_share - fee
            proceeds_portfolio = proceeds_local ÷ exchange_rate

        Note on exchange_rate:
            Transaction.exchange_rate is the broker rate:
            "1 portfolio_currency = X transaction_currency"
            So to convert TO portfolio currency, we DIVIDE.
        """
        total_bought_qty = Decimal("0")
        total_bought_cost_local = Decimal("0")
        total_bought_cost_portfolio = Decimal("0")
        total_sold_qty = Decimal("0")
        total_sold_proceeds_portfolio = Decimal("0")

        for txn in transactions:
            if txn.transaction_type == TransactionType.BUY:
                # Cost includes fee
                cost_local = (txn.quantity * txn.price_per_share) + txn.fee

                # Convert to portfolio currency using broker rate
                # exchange_rate = "1 EUR = X USD" → to get EUR, divide by rate
                exchange_rate = txn.exchange_rate or Decimal("1")
                cost_portfolio = cost_local / exchange_rate

                total_bought_qty += txn.quantity
                total_bought_cost_local += cost_local
                total_bought_cost_portfolio += cost_portfolio

            elif txn.transaction_type == TransactionType.SELL:
                # Proceeds excludes fee (fee reduces proceeds)
                proceeds_local = (txn.quantity * txn.price_per_share) - txn.fee

                # Convert to portfolio currency
                exchange_rate = txn.exchange_rate or Decimal("1")
                proceeds_portfolio = proceeds_local / exchange_rate

                total_sold_qty += txn.quantity
                total_sold_proceeds_portfolio += proceeds_portfolio

        # Current quantity = bought - sold
        quantity = total_bought_qty - total_sold_qty

        return HoldingPosition(
            asset_id=asset.id,
            asset=asset,
            quantity=quantity,
            total_bought_qty=total_bought_qty,
            total_bought_cost_local=total_bought_cost_local,
            total_bought_cost_portfolio=total_bought_cost_portfolio,
            total_sold_qty=total_sold_qty,
            total_sold_proceeds_portfolio=total_sold_proceeds_portfolio,
        )

    def apply_transaction(
            self,
            holdings_state: dict[int, dict],
            transaction: Transaction,
            asset: Asset,
    ) -> None:
        """
        Apply a single transaction to holdings state (mutates holdings_state).

        Used by the rolling state pattern in history calculator for O(N+D)
        instead of O(N*D) complexity.

        Args:
            holdings_state: Current holdings state keyed by asset_id.
                           Each value is a dict with position aggregates.
            transaction: Transaction to apply
            asset: Asset model for this transaction

        Note:
            holdings_state[asset_id] contains:
            {
                'asset': Asset,
                'total_bought_qty': Decimal,
                'total_bought_cost_local': Decimal,
                'total_bought_cost_portfolio': Decimal,
                'total_sold_qty': Decimal,
                'total_sold_proceeds_portfolio': Decimal,
            }
        """
        asset_id = transaction.asset_id

        # Skip non-investment transactions (DEPOSIT/WITHDRAWAL have no asset)
        if asset_id is None:
            return

        # Initialize state for new asset
        if asset_id not in holdings_state:
            holdings_state[asset_id] = {
                'asset': asset,
                'total_bought_qty': Decimal("0"),
                'total_bought_cost_local': Decimal("0"),
                'total_bought_cost_portfolio': Decimal("0"),
                'total_sold_qty': Decimal("0"),
                'total_sold_proceeds_portfolio': Decimal("0"),
            }

        state = holdings_state[asset_id]
        exchange_rate = transaction.exchange_rate or Decimal("1")

        if transaction.transaction_type == TransactionType.BUY:
            cost_local = (transaction.quantity * transaction.price_per_share) + transaction.fee
            cost_portfolio = cost_local / exchange_rate

            state['total_bought_qty'] += transaction.quantity
            state['total_bought_cost_local'] += cost_local
            state['total_bought_cost_portfolio'] += cost_portfolio

        elif transaction.transaction_type == TransactionType.SELL:
            proceeds_local = (transaction.quantity * transaction.price_per_share) - transaction.fee
            proceeds_portfolio = proceeds_local / exchange_rate

            state['total_sold_qty'] += transaction.quantity
            state['total_sold_proceeds_portfolio'] += proceeds_portfolio

    def state_to_positions(
            self,
            holdings_state: dict[int, dict],
    ) -> list[HoldingPosition]:
        """
        Convert holdings state dict to list of HoldingPosition objects.

        Only returns positions with quantity > 0.

        Args:
            holdings_state: Holdings state from apply_transaction calls

        Returns:
            List of HoldingPosition for open positions
        """
        positions: list[HoldingPosition] = []

        for asset_id, state in holdings_state.items():
            quantity = state['total_bought_qty'] - state['total_sold_qty']

            if quantity > Decimal("0"):
                positions.append(HoldingPosition(
                    asset_id=asset_id,
                    asset=state['asset'],
                    quantity=quantity,
                    total_bought_qty=state['total_bought_qty'],
                    total_bought_cost_local=state['total_bought_cost_local'],
                    total_bought_cost_portfolio=state['total_bought_cost_portfolio'],
                    total_sold_qty=state['total_sold_qty'],
                    total_sold_proceeds_portfolio=state['total_sold_proceeds_portfolio'],
                ))

        return positions


# =============================================================================
# COST BASIS CALCULATOR
# =============================================================================

class CostBasisCalculator:
    """
    Calculates cost basis for a holding position.

    Uses Weighted Average Cost method:
    - avg_cost = total_cost / total_bought_qty
    - remaining_cost = current_qty × avg_cost

    This proportionally reduces cost basis when shares are sold.
    """

    def calculate(
            self,
            position: HoldingPosition,
            portfolio_currency: str,
    ) -> CostBasisResult:
        """
        Calculate cost basis for a position.

        Args:
            position: The holding position with transaction aggregates
            portfolio_currency: Portfolio's base currency

        Returns:
            CostBasisResult with cost in both local and portfolio currency
        """
        # Handle edge case: no buys (shouldn't happen for valid positions)
        if position.total_bought_qty == Decimal("0"):
            return CostBasisResult(
                local_currency=position.asset.currency,
                local_amount=Decimal("0"),
                portfolio_currency=portfolio_currency,
                portfolio_amount=Decimal("0"),
                avg_cost_per_share=Decimal("0"),
            )

        # Calculate average cost per share
        avg_cost_local = position.total_bought_cost_local / position.total_bought_qty
        avg_cost_portfolio = position.total_bought_cost_portfolio / position.total_bought_qty

        # Remaining cost basis = current quantity × average cost
        remaining_cost_local = position.quantity * avg_cost_local
        remaining_cost_portfolio = position.quantity * avg_cost_portfolio

        return CostBasisResult(
            local_currency=position.asset.currency,
            local_amount=remaining_cost_local.quantize(Decimal("0.01")),
            portfolio_currency=portfolio_currency,
            portfolio_amount=remaining_cost_portfolio.quantize(Decimal("0.01")),
            avg_cost_per_share=avg_cost_local.quantize(Decimal("0.00000001")),
        )


# =============================================================================
# VALUE CALCULATOR
# =============================================================================

class ValueCalculator:
    """
    Calculates current market value for a holding position.

    Handles FX conversion from asset currency to portfolio currency
    using the FXRateService.

    Note on FX conventions:
        FXRateService returns: 1 base = rate × quote
        Example: USD/EUR = 0.92 means 1 USD = 0.92 EUR

        To convert value: value_EUR = value_USD × rate

        This is DIFFERENT from transaction.exchange_rate which uses
        the inverse convention!
    """

    def __init__(self, fx_service: FXRateService) -> None:
        """
        Initialize with FX service dependency.

        Args:
            fx_service: Service for FX rate lookups
        """
        self._fx_service = fx_service

    def calculate(
            self,
            db: Session,
            position: HoldingPosition,
            price: Decimal | None,
            price_date: date | None,
            portfolio_currency: str,
    ) -> ValueResult:
        """
        Calculate current value for a position.

        Args:
            db: Database session (for FX lookups)
            position: The holding position
            price: Market price per share (None if unavailable)
            price_date: Date of the price
            portfolio_currency: Portfolio's base currency

        Returns:
            ValueResult with value in both local and portfolio currency
        """
        warnings: list[str] = []
        asset_currency = position.asset.currency

        # No price data → return empty result
        if price is None or price_date is None:
            warnings.append(
                f"No price data available for {position.asset.ticker}"
            )
            return ValueResult(
                price=None,
                price_date=None,
                local_currency=asset_currency,
                local_amount=None,
                portfolio_currency=portfolio_currency,
                portfolio_amount=None,
                fx_rate_used=None,
                warnings=warnings,
            )

        # Calculate local value
        value_local = position.quantity * price

        # Same currency → no FX conversion needed
        if asset_currency.upper() == portfolio_currency.upper():
            return ValueResult(
                price=price,
                price_date=price_date,
                local_currency=asset_currency,
                local_amount=value_local.quantize(Decimal("0.01")),
                portfolio_currency=portfolio_currency,
                portfolio_amount=value_local.quantize(Decimal("0.01")),
                fx_rate_used=Decimal("1"),
                warnings=warnings,
            )

        # Different currency → need FX conversion
        fx_result = self._fx_service.get_rate_or_none(
            db=db,
            base_currency=asset_currency,
            quote_currency=portfolio_currency,
            target_date=price_date,
            allow_fallback=True,
        )

        if fx_result is None:
            warnings.append(
                f"No FX rate available for {asset_currency}/{portfolio_currency} "
                f"on {price_date}"
            )
            return ValueResult(
                price=price,
                price_date=price_date,
                local_currency=asset_currency,
                local_amount=value_local.quantize(Decimal("0.01")),
                portfolio_currency=portfolio_currency,
                portfolio_amount=None,  # Cannot calculate without FX
                fx_rate_used=None,
                warnings=warnings,
            )

        # FX conversion: value_portfolio = value_local × rate
        # Because FXRateService convention: 1 base = rate × quote
        value_portfolio = value_local * fx_result.rate

        # Add warning if fallback rate was used
        if not fx_result.is_exact_match:
            warnings.append(
                f"FX rate for {asset_currency}/{portfolio_currency} used fallback "
                f"from {fx_result.actual_date} (requested {price_date})"
            )

        return ValueResult(
            price=price,
            price_date=price_date,
            local_currency=asset_currency,
            local_amount=value_local.quantize(Decimal("0.01")),
            portfolio_currency=portfolio_currency,
            portfolio_amount=value_portfolio.quantize(Decimal("0.01")),
            fx_rate_used=fx_result.rate,
            warnings=warnings,
        )


# =============================================================================
# UNREALIZED P&L CALCULATOR
# =============================================================================

class UnrealizedPnLCalculator:
    """
    Calculates unrealized P&L (paper gains/losses) on open positions.

    Formula:
        unrealized_pnl = current_value - cost_basis
        unrealized_pct = (unrealized_pnl / cost_basis) × 100

    Note:
        Returns None for amount/percentage if current value is unknown.
    """

    def calculate(
            self,
            cost_basis_portfolio: Decimal,
            current_value_portfolio: Decimal | None,
    ) -> tuple[Decimal | None, Decimal | None]:
        """
        Calculate unrealized P&L.

        Args:
            cost_basis_portfolio: Cost basis in portfolio currency
            current_value_portfolio: Current value in portfolio currency (or None)

        Returns:
            Tuple of (amount, percentage) - both None if value unknown
        """
        # Cannot calculate without current value
        if current_value_portfolio is None:
            return None, None

        # Calculate P&L
        unrealized_pnl = current_value_portfolio - cost_basis_portfolio

        # Calculate percentage (guard against division by zero)
        if cost_basis_portfolio == Decimal("0"):
            unrealized_pct = None
        else:
            unrealized_pct = (
                    (unrealized_pnl / cost_basis_portfolio) * Decimal("100")
            ).quantize(Decimal("0.01"))

        return unrealized_pnl.quantize(Decimal("0.01")), unrealized_pct


# =============================================================================
# REALIZED P&L CALCULATOR
# =============================================================================

class RealizedPnLCalculator:
    """
    Calculates realized P&L from closed positions (sales).

    Uses Weighted Average Cost method:
        cost_of_sold = sold_qty × avg_cost_per_share
        realized_pnl = sale_proceeds - cost_of_sold
        realized_pct = (realized_pnl / cost_of_sold) × 100

    Note:
        - Always returns a concrete Decimal for amount (0 if no sales)
        - Returns None for percentage if no sales (division undefined)
    """

    def calculate(
            self,
            position: HoldingPosition,
    ) -> tuple[Decimal, Decimal | None]:
        """
        Calculate realized P&L from sales.

        Args:
            position: The holding position with transaction aggregates

        Returns:
            Tuple of (amount, percentage) - amount is always Decimal,
            percentage is None if no sales
        """
        # No sales → no realized P&L
        if position.total_sold_qty == Decimal("0"):
            return Decimal("0"), None

        # Guard against division by zero (shouldn't happen with sales)
        if position.total_bought_qty == Decimal("0"):
            return Decimal("0"), None

        # Calculate cost of shares that were sold using average cost
        avg_cost_portfolio = (
                position.total_bought_cost_portfolio / position.total_bought_qty
        )
        cost_of_sold = position.total_sold_qty * avg_cost_portfolio

        # Realized P&L = Proceeds - Cost of sold shares
        realized_pnl = position.total_sold_proceeds_portfolio - cost_of_sold

        # Calculate percentage
        if cost_of_sold == Decimal("0"):
            realized_pct = None
        else:
            realized_pct = (
                    (realized_pnl / cost_of_sold) * Decimal("100")
            ).quantize(Decimal("0.01"))

        return realized_pnl.quantize(Decimal("0.01")), realized_pct


# =============================================================================
# CASH CALCULATOR
# =============================================================================

class CashCalculator:
    """
    Calculates cash balances from transactions.

    Processes transactions sequentially to track cash flows:
    - DEPOSIT: Adds cash in the deposit currency
    - WITHDRAWAL: Removes cash
    - BUY: Removes cash (cost = qty × price + fee)
    - SELL: Adds cash (proceeds = qty × price - fee)

    Cash is tracked per currency, then converted to portfolio currency
    for total calculation.

    Smart Cash Detection:
        Cash tracking is ONLY enabled if the portfolio has at least one
        DEPOSIT or WITHDRAWAL transaction. Portfolios with only BUY/SELL
        transactions do not track cash (to avoid showing negative balances).

    Note:
        For DEPOSIT/WITHDRAWAL transactions:
        - quantity represents the cash amount
        - price_per_share is typically 1 (or amount = qty × price)
        - currency is the cash currency
        - fee is any transaction fee
    """

    @staticmethod
    def has_cash_transactions(transactions: list[Transaction]) -> bool:
        """
        Detect if portfolio tracks cash.

        A portfolio tracks cash if it has at least one DEPOSIT or WITHDRAWAL
        transaction. Portfolios with only BUY/SELL do not track cash.

        Args:
            transactions: All transactions for the portfolio

        Returns:
            True if cash tracking is enabled (has DEPOSIT/WITHDRAWAL)
        """
        return any(
            txn.transaction_type in (TransactionType.DEPOSIT, TransactionType.WITHDRAWAL)
            for txn in transactions
        )

    def calculate(
            self,
            transactions: list[Transaction],
            portfolio_currency: str,
    ) -> dict[str, Decimal]:
        """
        Calculate cash balances from transactions.

        Args:
            transactions: All transactions (should be sorted by date)
            portfolio_currency: Portfolio's base currency

        Returns:
            Dict mapping currency -> balance (e.g., {'EUR': Decimal('1000.00')})
        """
        cash_balances: dict[str, Decimal] = {}

        for txn in transactions:
            currency = txn.currency.upper()

            # Initialize currency if not seen
            if currency not in cash_balances:
                cash_balances[currency] = Decimal("0")

            if txn.transaction_type == TransactionType.DEPOSIT:
                # DEPOSIT: Add cash (amount = qty × price - fee)
                amount = (txn.quantity * txn.price_per_share) - txn.fee
                cash_balances[currency] += amount

            elif txn.transaction_type == TransactionType.WITHDRAWAL:
                # WITHDRAWAL: Remove cash (amount = qty × price + fee)
                amount = (txn.quantity * txn.price_per_share) + txn.fee
                cash_balances[currency] -= amount

            elif txn.transaction_type == TransactionType.BUY:
                # BUY: Remove cash for the purchase
                cost = (txn.quantity * txn.price_per_share) + txn.fee
                cash_balances[currency] -= cost

            elif txn.transaction_type == TransactionType.SELL:
                # SELL: Add cash from sale proceeds
                proceeds = (txn.quantity * txn.price_per_share) - txn.fee
                cash_balances[currency] += proceeds

        # Remove zero balances and round
        return {
            currency: balance.quantize(Decimal("0.01"))
            for currency, balance in cash_balances.items()
            if balance != Decimal("0")
        }

    def calculate_with_state(
            self,
            current_cash: dict[str, Decimal],
            transaction: Transaction,
    ) -> None:
        """
        Apply a single transaction to cash state (mutates current_cash).

        Used by the rolling state pattern in history calculator.

        Args:
            current_cash: Current cash balances (will be mutated)
            transaction: Transaction to apply
        """
        currency = transaction.currency.upper()

        if currency not in current_cash:
            current_cash[currency] = Decimal("0")

        if transaction.transaction_type == TransactionType.DEPOSIT:
            amount = (transaction.quantity * transaction.price_per_share) - transaction.fee
            current_cash[currency] += amount

        elif transaction.transaction_type == TransactionType.WITHDRAWAL:
            amount = (transaction.quantity * transaction.price_per_share) + transaction.fee
            current_cash[currency] -= amount

        elif transaction.transaction_type == TransactionType.BUY:
            cost = (transaction.quantity * transaction.price_per_share) + transaction.fee
            current_cash[currency] -= cost

        elif transaction.transaction_type == TransactionType.SELL:
            proceeds = (transaction.quantity * transaction.price_per_share) - transaction.fee
            current_cash[currency] += proceeds
