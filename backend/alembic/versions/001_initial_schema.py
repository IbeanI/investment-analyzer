"""Initial schema baseline

This migration creates the complete database schema for the Investment Analyzer.

Tables:
    - users: User accounts
    - portfolios: Investment portfolios owned by users
    - assets: Global asset registry (stocks, ETFs, etc.)
    - transactions: Buy/sell transactions within portfolios
    - market_data: Historical price data (OHLCV)
    - exchange_rates: Currency conversion rates
    - sync_status: Market data sync tracking per portfolio
    - portfolio_settings: User preferences per portfolio

Revision ID: 001
Revises: None
Create Date: 2026-01-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ==========================================================================
    # USERS
    # ==========================================================================
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('email', sa.String(), nullable=False, unique=True, index=True),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # ==========================================================================
    # PORTFOLIOS
    # ==========================================================================
    op.create_table(
        'portfolios',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('currency', sa.String(), nullable=False, server_default='EUR'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # ==========================================================================
    # ASSETS
    # ==========================================================================
    op.create_table(
        'assets',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('ticker', sa.String(), nullable=False, index=True),
        sa.Column('exchange', sa.String(), nullable=False, index=True),
        sa.Column('isin', sa.String(), nullable=True, index=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('asset_class', sa.Enum('STOCK', 'ETF', 'BOND', 'OPTION', 'CRYPTO', 'CASH', 'INDEX', 'FUTURE', 'OTHER', name='assetclass'), nullable=False),
        sa.Column('currency', sa.String(), nullable=False, server_default='EUR'),
        sa.Column('sector', sa.String(), nullable=True),
        sa.Column('region', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('proxy_asset_id', sa.Integer(), sa.ForeignKey('assets.id'), nullable=True, index=True),
        sa.Column('proxy_notes', sa.String(), nullable=True),
        sa.UniqueConstraint('ticker', 'exchange', name='uq_ticker_exchange'),
    )

    # ==========================================================================
    # TRANSACTIONS
    # ==========================================================================
    op.create_table(
        'transactions',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('portfolio_id', sa.Integer(), sa.ForeignKey('portfolios.id'), nullable=False, index=True),
        sa.Column('asset_id', sa.Integer(), sa.ForeignKey('assets.id'), nullable=True, index=True),
        sa.Column('transaction_type', sa.Enum('BUY', 'SELL', 'DEPOSIT', 'WITHDRAWAL', 'DIVIDEND', 'FEE', 'TAX', name='transactiontype'), nullable=False),
        sa.Column('date', sa.DateTime(), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('quantity', sa.Numeric(18, 8), nullable=False),
        sa.Column('price_per_share', sa.Numeric(18, 8), nullable=False),
        sa.Column('currency', sa.String(), nullable=False, server_default='EUR'),
        sa.Column('fee', sa.Numeric(18, 8), nullable=False, server_default='0'),
        sa.Column('fee_currency', sa.String(), nullable=False),
        sa.Column('exchange_rate', sa.Numeric(18, 8), nullable=True, server_default='1'),
    )

    # Composite indexes for transactions
    op.create_index('ix_transaction_portfolio_date', 'transactions', ['portfolio_id', 'date'])
    op.create_index('ix_transaction_portfolio_asset_date', 'transactions', ['portfolio_id', 'asset_id', 'date'])

    # ==========================================================================
    # MARKET DATA
    # ==========================================================================
    op.create_table(
        'market_data',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('asset_id', sa.Integer(), sa.ForeignKey('assets.id'), nullable=False, index=True),
        sa.Column('date', sa.Date(), nullable=False, index=True),
        sa.Column('open_price', sa.Numeric(18, 8), nullable=True),
        sa.Column('high_price', sa.Numeric(18, 8), nullable=True),
        sa.Column('low_price', sa.Numeric(18, 8), nullable=True),
        sa.Column('close_price', sa.Numeric(18, 8), nullable=False),
        sa.Column('adjusted_close', sa.Numeric(18, 8), nullable=True),
        sa.Column('volume', sa.BigInteger(), nullable=True),
        sa.Column('provider', sa.String(50), nullable=False, server_default='yahoo'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_synthetic', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('proxy_source_id', sa.Integer(), sa.ForeignKey('assets.id'), nullable=True, index=True),
        sa.UniqueConstraint('asset_id', 'date', name='uq_asset_date'),
    )

    # Composite index for market_data
    op.create_index('ix_market_data_asset_synthetic_date', 'market_data', ['asset_id', 'is_synthetic', 'date'])

    # ==========================================================================
    # EXCHANGE RATES
    # ==========================================================================
    op.create_table(
        'exchange_rates',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('base_currency', sa.String(3), nullable=False, index=True),
        sa.Column('quote_currency', sa.String(3), nullable=False, index=True),
        sa.Column('date', sa.Date(), nullable=False, index=True),
        sa.Column('rate', sa.Numeric(18, 8), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False, server_default='yahoo'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('base_currency', 'quote_currency', 'date', name='uq_exchange_rate_pair_date'),
    )

    # Composite index for exchange_rates
    op.create_index('ix_exchange_rate_quote_base_date', 'exchange_rates', ['quote_currency', 'base_currency', 'date'])

    # ==========================================================================
    # SYNC STATUS
    # ==========================================================================
    op.create_table(
        'sync_status',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('portfolio_id', sa.Integer(), sa.ForeignKey('portfolios.id'), nullable=False, unique=True, index=True),
        sa.Column('last_sync_started', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_completed', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.Enum('NEVER', 'IN_PROGRESS', 'COMPLETED', 'PARTIAL', 'FAILED', 'PENDING', name='syncstatusenum'), nullable=False, server_default='NEVER'),
        sa.Column('coverage_summary', sa.JSON(), nullable=True),
        sa.Column('last_error', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # ==========================================================================
    # PORTFOLIO SETTINGS
    # ==========================================================================
    op.create_table(
        'portfolio_settings',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('portfolio_id', sa.Integer(), sa.ForeignKey('portfolios.id'), nullable=False, unique=True, index=True),
        sa.Column('enable_proxy_backcasting', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('portfolio_settings')
    op.drop_table('sync_status')
    op.drop_index('ix_exchange_rate_quote_base_date', table_name='exchange_rates')
    op.drop_table('exchange_rates')
    op.drop_index('ix_market_data_asset_synthetic_date', table_name='market_data')
    op.drop_table('market_data')
    op.drop_index('ix_transaction_portfolio_asset_date', table_name='transactions')
    op.drop_index('ix_transaction_portfolio_date', table_name='transactions')
    op.drop_table('transactions')
    op.drop_table('assets')
    op.drop_table('portfolios')
    op.drop_table('users')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS assetclass')
    op.execute('DROP TYPE IF EXISTS transactiontype')
    op.execute('DROP TYPE IF EXISTS syncstatusenum')
