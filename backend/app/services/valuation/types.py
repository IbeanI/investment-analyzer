# backend/app/services/valuation/types.py
"""
Internal data types for the Valuation Service.

These dataclasses are used internally by the valuation calculators.
They are NOT Pydantic schemas - those are defined in app/schemas/valuation.py
for API serialization.

Design Principles:
- Immutable where possible (frozen=True for value objects)
- Use Decimal for ALL financial values (never float)
- Use date (not datetime) for valuation dates
- Optional fields use None, not sentinel values
- Warnings accumulate for data quality tracking

Type Hierarchy:
    HoldingPosition     - Aggregated transaction data for one asset
    CostBasisResult     - Cost basis calculation output
    ValueResult         - Current value with FX conversion
    PnLResult           - Unrealized + Realized P&L
    HoldingValuation    - Complete valuation for one holding
    PortfolioValuation  - Complete portfolio valuation
    HistoryPoint        - Single point in time series
    PortfolioHistory    - Time series result
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import Asset


# =============================================================================
# POSITION & HOLDINGS
# =============================================================================

@dataclass
class HoldingPosition:
    """
    Aggregated position data for a single asset.

    This represents the result of processing all transactions for one asset
    up to a specific date. It contains everything needed for cost basis,
    value, and P&L calculations.

    Attributes:
        asset_id: Database ID of the asset
        asset: Full Asset model object (for currency, name, etc.)
        quantity: Current shares held (bought - sold)
        total_bought_qty: Total shares ever purchased
        total_bought_cost_local: Total cost in asset's trading currency
        total_bought_cost_portfolio: Total cost in portfolio currency
        total_sold_qty: Total shares ever sold
        total_sold_proceeds_portfolio: Total proceeds from sales in portfolio currency

    Note:
        - All costs INCLUDE fees (cost = qty × price + fee)
        - All proceeds EXCLUDE fees (proceeds = qty × price - fee)
        - Portfolio currency amounts use transaction.exchange_rate (broker rate)
    """

    asset_id: int
    asset: Asset
    quantity: Decimal
    total_bought_qty: Decimal
    total_bought_cost_local: Decimal
    total_bought_cost_portfolio: Decimal
    total_sold_qty: Decimal
    total_sold_proceeds_portfolio: Decimal

    @property
    def has_position(self) -> bool:
        """True if there are shares currently held."""
        return self.quantity > Decimal("0")

    @property
    def avg_cost_per_share_local(self) -> Decimal | None:
        """
        Weighted average cost per share in local currency.

        Returns None if no shares were ever bought (division by zero).
        """
        if self.total_bought_qty == Decimal("0"):
            return None
        return (self.total_bought_cost_local / self.total_bought_qty).quantize(
            Decimal("0.00000001")
        )

    @property
    def avg_cost_per_share_portfolio(self) -> Decimal | None:
        """
        Weighted average cost per share in portfolio currency.

        Returns None if no shares were ever bought (division by zero).
        """
        if self.total_bought_qty == Decimal("0"):
            return None
        return (self.total_bought_cost_portfolio / self.total_bought_qty).quantize(
            Decimal("0.00000001")
        )


@dataclass
class HoldingsResult:
    """
    Result of holdings calculation including data integrity warnings.

    This is the return type for HoldingsCalculator.calculate().
    It contains both the calculated positions and any warnings about
    data quality issues that users should be aware of.

    Attributes:
        positions: List of calculated holdings positions
        warnings: Data integrity warnings (e.g., sales without prior buys)

    Note:
        Warnings indicate potential data issues but don't prevent calculation.
        Positions with severe data issues (e.g., sales without buys) are
        excluded from the positions list but generate warnings.
    """

    positions: list[HoldingPosition]
    warnings: list[str] = field(default_factory=list)


# =============================================================================
# COST BASIS
# =============================================================================

@dataclass(frozen=True)
class CostBasisResult:
    """
    Cost basis calculation result for a holding.

    Represents the total cost of acquiring the currently-held shares,
    calculated using weighted average cost method.

    Attributes:
        local_currency: Currency the asset trades in (e.g., "USD")
        local_amount: Cost in asset's trading currency
        portfolio_currency: Portfolio's base currency (e.g., "EUR")
        portfolio_amount: Cost in portfolio currency (using transaction FX rates)
        avg_cost_per_share: Average cost per share in local currency

    Note:
        Cost basis is proportionally reduced when shares are sold.
        Formula: remaining_cost = (remaining_qty / total_bought_qty) × total_cost
    """

    local_currency: str
    local_amount: Decimal
    portfolio_currency: str
    portfolio_amount: Decimal
    avg_cost_per_share: Decimal


# =============================================================================
# CURRENT VALUE
# =============================================================================

@dataclass
class ValueResult:
    """
    Current market value calculation result for a holding.

    Represents the current market value of held shares, with FX conversion
    to the portfolio's base currency.

    Attributes:
        price: Market price per share (None if no price data)
        price_date: Date of the price (None if no price data)
        local_currency: Currency the asset trades in
        local_amount: Value in asset's trading currency (None if no price)
        portfolio_currency: Portfolio's base currency
        portfolio_amount: Value in portfolio currency (None if no price/FX)
        fx_rate_used: FX rate applied for conversion (None if same currency or no FX)
        warnings: List of data quality warnings

    Note:
        - All amounts can be None if price or FX data is missing
        - Warnings explain WHY data is missing (for debugging)
        - fx_rate_used is the market rate (not broker rate from transactions)
    """

    price: Decimal | None
    price_date: date | None
    local_currency: str
    local_amount: Decimal | None
    portfolio_currency: str
    portfolio_amount: Decimal | None
    fx_rate_used: Decimal | None
    warnings: list[str] = field(default_factory=list)

    @property
    def has_complete_data(self) -> bool:
        """True if both price and portfolio value are available."""
        return self.price is not None and self.portfolio_amount is not None


@dataclass
class PriceResult:
    """
    Result of fetching a price with quality metadata.

    Tracks whether the price is synthetic (from proxy backcasting)
    and which proxy asset was used.
    """
    price: Decimal | None
    date: date
    is_synthetic: bool = False
    proxy_source_id: int | None = None
    proxy_ticker: str | None = None
    proxy_exchange: str | None = None


# =============================================================================
# PROFIT & LOSS
# =============================================================================

@dataclass(frozen=True)
class PnLResult:
    """
    Profit and Loss calculation result for a holding.

    Contains both unrealized P&L (paper gains/losses on open positions)
    and realized P&L (actual gains/losses from closed positions).

    Attributes:
        unrealized_amount: Gain/loss on open positions (None if value unknown)
        unrealized_percentage: Unrealized P&L as % of cost basis (None if unknown)
        realized_amount: Gain/loss on closed positions (always Decimal, 0 if no sales)
        realized_percentage: Realized P&L as % of cost of sold shares (None if no sales)
        total_amount: unrealized + realized (None if unrealized unknown)
        total_percentage: Total P&L as % (None if incomplete)

    Formulas:
        unrealized = current_value - remaining_cost_basis
        realized = sale_proceeds - cost_of_sold_shares
        total = unrealized + realized

    Note:
        - Realized P&L is always a concrete Decimal (0 if no sales)
        - Unrealized P&L can be None if current value is unknown
        - Percentages can be None even when amounts are known (if cost is 0)
    """

    unrealized_amount: Decimal | None
    unrealized_percentage: Decimal | None
    realized_amount: Decimal
    realized_percentage: Decimal | None
    total_amount: Decimal | None
    total_percentage: Decimal | None


# =============================================================================
# HOLDING VALUATION (Complete for one asset)
# =============================================================================

@dataclass
class HoldingValuation:
    """
    Complete valuation for a single holding (position).

    Aggregates all valuation components for one asset: position size,
    cost basis, current value, and P&L.

    Attributes:
        asset_id: Database ID of the asset
        ticker: Trading symbol (e.g., "AAPL")
        exchange: Exchange code (e.g., "NASDAQ")
        asset_name: Full name (e.g., "Apple Inc.")
        asset_class: Asset class (e.g., "STOCK", "ETF", "BOND")
        asset_currency: Currency the asset trades in
        quantity: Number of shares/units held
        cost_basis: Cost basis calculation result
        current_value: Current market value result
        pnl: P&L calculation result
        warnings: Holding-level warnings
        has_complete_data: True if all calculations succeeded

    Note:
        has_complete_data = False means some values are None due to
        missing price or FX data. The holding is still included in
        results, but its value doesn't contribute to portfolio totals.
    """

    asset_id: int
    ticker: str
    exchange: str
    asset_name: str | None
    asset_class: str
    asset_currency: str
    quantity: Decimal
    cost_basis: CostBasisResult
    current_value: ValueResult
    pnl: PnLResult
    warnings: list[str] = field(default_factory=list)
    has_complete_data: bool = True

    # Daily change (price change since previous trading day)
    day_change: Decimal | None = None  # In asset currency
    day_change_percentage: Decimal | None = None

    # Synthetic data tracking (for transparency)
    price_is_synthetic: bool = False
    price_source: str = "market"  # "market" | "proxy_backcast" | "unavailable"
    proxy_ticker: str | None = None
    proxy_exchange: str | None = None


# =============================================================================
# CASH BALANCE
# =============================================================================

@dataclass
class CashBalance:
    """
    Cash balance in a specific currency.

    Tracks cash from deposits, withdrawals, and transaction settlements.

    Attributes:
        currency: The currency code (e.g., "EUR", "USD")
        amount: Cash amount in this currency
        amount_portfolio: Cash amount converted to portfolio currency (None if FX unavailable)
        fx_rate_used: FX rate used for conversion (None if same as portfolio currency)
    """

    currency: str
    amount: Decimal
    amount_portfolio: Decimal | None = None
    fx_rate_used: Decimal | None = None


# =============================================================================
# PORTFOLIO VALUATION (Complete for portfolio)
# =============================================================================

@dataclass
class PortfolioValuation:
    """
    Complete valuation for an entire portfolio.

    Aggregates all holdings, cash balances, and provides portfolio-level totals.

    Attributes:
        portfolio_id: Database ID of the portfolio
        portfolio_name: Name of the portfolio
        portfolio_currency: Base currency for all valuations
        valuation_date: Date of this valuation
        holdings: List of individual holding valuations
        tracks_cash: True if portfolio has DEPOSIT/WITHDRAWAL transactions
        cash_balances: Cash balances by currency (empty if tracks_cash=False)
        total_cost_basis: Sum of all cost bases in portfolio currency
        total_value: Sum of all current values (None if any incomplete)
        total_cash: Sum of all cash in portfolio currency (None if not tracking or FX incomplete)
        total_equity: total_value + total_cash (None if either incomplete)
        total_unrealized_pnl: Sum of unrealized P&L (None if any incomplete)
        total_realized_pnl: Sum of realized P&L (always Decimal)
        total_pnl: Total P&L (None if unrealized unknown)
        warnings: Portfolio-level warnings
        has_complete_data: True if ALL holdings have complete data

    Note:
        - tracks_cash is auto-detected: True if ANY DEPOSIT/WITHDRAWAL exists
        - If tracks_cash=False, cash_balances=[], total_cash=None, total_equity=total_value
        - total_value is the value of SECURITIES only
        - total_equity = total_value + total_cash (the true portfolio value)
    """

    portfolio_id: int
    portfolio_name: str
    portfolio_currency: str
    valuation_date: date
    holdings: list[HoldingValuation]
    tracks_cash: bool
    cash_balances: list[CashBalance]
    total_cost_basis: Decimal
    total_net_invested: Decimal  # Deposits - Withdrawals (or BUYs - SELLs)
    total_value: Decimal | None
    total_cash: Decimal | None
    total_equity: Decimal | None
    total_unrealized_pnl: Decimal | None
    total_realized_pnl: Decimal
    total_pnl: Decimal | None
    warnings: list[str] = field(default_factory=list)
    has_complete_data: bool = True

    # Synthetic data summary (for transparency)
    has_synthetic_data: bool = False
    synthetic_holdings_count: int = 0

    @property
    def total_pnl_percentage(self) -> Decimal | None:
        """Total P&L as percentage of net invested capital.

        Returns None during gap periods (when cost_basis is 0 but net_invested > 0)
        to avoid misleading percentage calculations.
        """
        if self.total_pnl is None:
            return None
        if self.total_net_invested <= Decimal("0"):
            return None  # Cannot calculate when net invested is zero or negative
        # Handle zero cost basis (gap period or no holdings)
        if self.total_cost_basis <= Decimal("0"):
            return None
        return (self.total_pnl / self.total_net_invested).quantize(
            Decimal("0.0001")
        )


# =============================================================================
# SYNTHETIC DATA TRACKING
# =============================================================================

@dataclass
class SyntheticAssetDetail:
    """
    Per-asset synthetic data details for transparency.

    Tracks when and how synthetic prices were used for a specific asset.

    Synthetic methods:
    - "proxy_backcast": Prices modeled using a correlated proxy asset
    - "cost_carry": Prices valued at purchase cost (no proxy available)

    Attributes:
        ticker: Asset ticker symbol
        proxy_ticker: Ticker of the proxy asset used (None for cost_carry)
        first_synthetic_date: First date synthetic price was used
        last_synthetic_date: Last date synthetic price was used
        synthetic_days: Number of days with synthetic prices
        total_days_held: Total days this asset was in the portfolio
        synthetic_method: Method used ("proxy_backcast" or "cost_carry")
        percentage: Percentage of holding period using synthetic data
    """
    ticker: str
    proxy_ticker: str | None
    first_synthetic_date: date
    last_synthetic_date: date
    synthetic_days: int
    total_days_held: int
    synthetic_method: str = "proxy_backcast"  # "proxy_backcast" or "cost_carry"

    @property
    def percentage(self) -> Decimal:
        """Percentage of holding period with synthetic data."""
        if self.total_days_held == 0:
            return Decimal("0")
        return (
                Decimal(str(self.synthetic_days)) / Decimal(str(self.total_days_held)) * Decimal("100")
        ).quantize(Decimal("0.01"))


# =============================================================================
# HISTORY (Time series for charts)
# =============================================================================

@dataclass
class HistoryPoint:
    """
    A single point in portfolio valuation history.

    Used for charting portfolio performance over time.

    Attributes:
        date: Date of this data point
        value: Portfolio securities value (None if incomplete data)
        cash: Total cash in portfolio currency (None if not tracking or FX incomplete)
        equity: value + cash - the true portfolio value (None if either incomplete)
        cost_basis: Total cost basis at this date
        unrealized_pnl: Unrealized P&L (None if value unknown)
        realized_pnl: Realized P&L from sales up to this date
        total_pnl: Total P&L (None if unrealized unknown)
        has_complete_data: True if value is reliable

    Note:
        - If portfolio doesn't track cash: cash=None, equity=value
    """

    date: date
    value: Decimal | None
    cash: Decimal | None
    equity: Decimal | None
    cost_basis: Decimal
    net_invested: Decimal  # Cumulative net invested as of this date
    unrealized_pnl: Decimal | None
    realized_pnl: Decimal
    total_pnl: Decimal | None
    has_complete_data: bool = True
    has_synthetic_data: bool = False
    synthetic_holdings: dict[str, str | None] = field(default_factory=dict)  # {ticker: proxy_ticker}
    holdings_count: int = 0  # Total holdings on this day (for % calculation)
    drawdown: Decimal | None = None  # TWR-based drawdown as decimal (e.g., -0.0385)

    @property
    def pnl_percentage(self) -> Decimal | None:
        """P&L as percentage of net invested capital.

        Returns None during gap periods (when cost_basis is 0 but net_invested > 0)
        to avoid misleading percentage calculations.
        """
        if self.total_pnl is None:
            return None
        if self.net_invested <= Decimal("0"):
            return None  # Cannot calculate when net invested is zero or negative
        # During gap periods, cost_basis is 0 but net_invested may be positive
        # Return None to avoid misleading percentages
        if self.cost_basis <= Decimal("0"):
            return None
        return (self.total_pnl / self.net_invested).quantize(
            Decimal("0.0001")
        )

    @property
    def is_gap_period(self) -> bool:
        """True if this is a gap period (no holdings, zero equity)."""
        # value can be None (incomplete data) or Decimal("0") (gap period)
        # Gap period is when we have no cost basis and either zero value or no value
        return self.cost_basis <= Decimal("0") and (
            self.value is None or self.value == Decimal("0")
        )


@dataclass
class PortfolioHistory:
    """
    Portfolio valuation history (time series).

    Contains a series of data points for charting portfolio
    performance over a date range.

    Attributes:
        portfolio_id: Database ID of the portfolio
        portfolio_currency: Base currency for all values
        start_date: First date in the series
        end_date: Last date in the series
        interval: Data interval ("daily", "weekly", "monthly")
        tracks_cash: True if portfolio tracks cash (has DEPOSIT/WITHDRAWAL)
        data: List of history points
        warnings: Any warnings about data gaps or issues

    Note:
        - tracks_cash is auto-detected from transactions
        - If tracks_cash=False, all points have cash=None, equity=value
    """

    portfolio_id: int
    portfolio_currency: str
    start_date: date
    end_date: date
    interval: str
    tracks_cash: bool
    data: list[HistoryPoint]
    warnings: list[str] = field(default_factory=list)
    has_synthetic_data: bool = False
    synthetic_holdings: dict[str, str | None] = field(default_factory=dict)  # {ticker: proxy_ticker}
    synthetic_date_range: tuple[date, date] | None = None  # (start, end) when synthetic data used
    synthetic_lookups: int = 0  # Number of price lookups that were synthetic
    total_lookups: int = 0  # Total number of price lookups
    synthetic_details: dict[str, SyntheticAssetDetail] = field(default_factory=dict)  # Per-asset details

    @property
    def synthetic_percentage(self) -> Decimal:
        """Percentage of price lookups that used synthetic data."""
        if self.total_lookups == 0:
            return Decimal("0")
        return (
                Decimal(str(self.synthetic_lookups)) / Decimal(str(self.total_lookups)) * Decimal("100")
        ).quantize(Decimal("0.01"))

    @property
    def total_points(self) -> int:
        """Number of data points in the series."""
        return len(self.data)

    @property
    def complete_points(self) -> int:
        """Number of points with complete data."""
        return sum(1 for p in self.data if p.has_complete_data)
