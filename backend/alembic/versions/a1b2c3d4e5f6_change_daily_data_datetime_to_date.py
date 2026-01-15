"""Change daily data columns from DateTime to Date

This migration changes the 'date' column in market_data and exchange_rates
tables from DateTime to Date type. Daily data (prices, FX rates) should use
Date type to avoid time component mismatches during lookups.

Revision ID: a1b2c3d4e5f6
Revises: e8193cc7257e
Create Date: 2026-01-15 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'e8193cc7257e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change DateTime columns to Date for daily data tables."""
    # Change market_data.date from DateTime to Date
    # Using ALTER COLUMN with TYPE cast to preserve existing data
    op.alter_column(
        'market_data',
        'date',
        existing_type=sa.DateTime(),
        type_=sa.Date(),
        existing_nullable=False,
        postgresql_using='date::date'  # PostgreSQL cast syntax
    )

    # Change exchange_rates.date from DateTime to Date
    op.alter_column(
        'exchange_rates',
        'date',
        existing_type=sa.DateTime(),
        type_=sa.Date(),
        existing_nullable=False,
        postgresql_using='date::date'  # PostgreSQL cast syntax
    )


def downgrade() -> None:
    """Revert Date columns back to DateTime."""
    # Revert market_data.date to DateTime
    op.alter_column(
        'market_data',
        'date',
        existing_type=sa.Date(),
        type_=sa.DateTime(),
        existing_nullable=False,
        postgresql_using='date::timestamp'  # PostgreSQL cast syntax
    )

    # Revert exchange_rates.date to DateTime
    op.alter_column(
        'exchange_rates',
        'date',
        existing_type=sa.Date(),
        type_=sa.DateTime(),
        existing_nullable=False,
        postgresql_using='date::timestamp'  # PostgreSQL cast syntax
    )
