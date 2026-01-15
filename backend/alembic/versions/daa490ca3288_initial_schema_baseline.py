"""Initial schema baseline

Revision ID: daa490ca3288
Revises: 
Create Date: 2026-01-15 19:06:25.585272

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'daa490ca3288'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Existing tables already in database - baseline only."""
    pass


def downgrade() -> None:
    """Baseline migration - nothing to downgrade."""
    pass
