"""Add missing FK indexes and remove redundant index

This migration addresses two performance issues:

1. Missing indexes on foreign key columns:
   - portfolios.user_id: Speeds up "get portfolios for user" queries
   - transactions.portfolio_id: Speeds up "get transactions for portfolio" queries
   - transactions.asset_id: Speeds up "get transactions for asset" queries

   PostgreSQL does NOT auto-create indexes on FK columns (unlike MySQL InnoDB).
   Without these indexes, queries filter via sequential scans O(n).

2. Redundant index removal:
   - ix_exchange_rate_lookup on exchange_rates is redundant because
     the UniqueConstraint 'uq_exchange_rate_pair_date' already creates
     an index on the same columns (base_currency, quote_currency, date).

Revision ID: b2c3d4e5f678
Revises: a1b2c3d4e5f6
Create Date: 2026-01-16 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f678'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add missing FK indexes and remove redundant composite index."""
    # Add missing index on portfolios.user_id
    op.create_index(
        'ix_portfolios_user_id',
        'portfolios',
        ['user_id'],
        unique=False
    )

    # Add missing index on transactions.portfolio_id
    op.create_index(
        'ix_transactions_portfolio_id',
        'transactions',
        ['portfolio_id'],
        unique=False
    )

    # Add missing index on transactions.asset_id
    op.create_index(
        'ix_transactions_asset_id',
        'transactions',
        ['asset_id'],
        unique=False
    )

    # Remove redundant index (UniqueConstraint already creates one)
    op.drop_index('ix_exchange_rate_lookup', table_name='exchange_rates')


def downgrade() -> None:
    """Revert: remove FK indexes and restore redundant index."""
    # Restore redundant index
    op.create_index(
        'ix_exchange_rate_lookup',
        'exchange_rates',
        ['base_currency', 'quote_currency', 'date'],
        unique=False
    )

    # Remove FK indexes
    op.drop_index('ix_transactions_asset_id', table_name='transactions')
    op.drop_index('ix_transactions_portfolio_id', table_name='transactions')
    op.drop_index('ix_portfolios_user_id', table_name='portfolios')
