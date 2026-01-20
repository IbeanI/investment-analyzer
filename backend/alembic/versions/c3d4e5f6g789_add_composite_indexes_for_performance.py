"""Add composite indexes for performance optimization

This migration adds composite indexes to optimize the most common query patterns:

1. Transaction (portfolio_id, date):
   - Speeds up point-in-time valuation queries: "Get all transactions for
     portfolio X up to date Y"
   - Used heavily in valuation/history_calculator.py and calculators.py
   - Typical query: SELECT * FROM transactions WHERE portfolio_id = ? AND date <= ?

2. ExchangeRate (quote_currency, base_currency, date):
   - Speeds up FX rate lookups where quote_currency is the portfolio's base currency
   - The common pattern is: WHERE quote_currency = 'EUR' AND base_currency IN ('USD', 'GBP')
   - Putting quote_currency first allows index to filter by equality before the IN clause
   - Used heavily in history_calculator.py and fx_rate_service.py

Note: The unique constraint on ExchangeRate already creates an index on
(base_currency, quote_currency, date), but that order is suboptimal for
the common query pattern where quote_currency is always an equality condition.

Revision ID: c3d4e5f6g789
Revises: 9fa4a978ee74
Create Date: 2026-01-20 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6g789'
down_revision: Union[str, Sequence[str], None] = '9fa4a978ee74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add composite indexes for improved query performance."""
    # Composite index for point-in-time transaction queries
    # Optimizes: SELECT * FROM transactions WHERE portfolio_id = ? AND date <= ?
    op.create_index(
        'ix_transaction_portfolio_date',
        'transactions',
        ['portfolio_id', 'date'],
        unique=False
    )

    # Composite index for FX rate lookups with quote_currency equality
    # Optimizes: SELECT * FROM exchange_rates
    #            WHERE quote_currency = ? AND base_currency IN (?) AND date BETWEEN ? AND ?
    op.create_index(
        'ix_exchange_rate_quote_base_date',
        'exchange_rates',
        ['quote_currency', 'base_currency', 'date'],
        unique=False
    )


def downgrade() -> None:
    """Remove composite indexes."""
    op.drop_index('ix_exchange_rate_quote_base_date', table_name='exchange_rates')
    op.drop_index('ix_transaction_portfolio_date', table_name='transactions')
