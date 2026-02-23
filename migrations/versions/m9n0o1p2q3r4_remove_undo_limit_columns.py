"""Remove daily undo limit columns from users

Revision ID: m9n0o1p2q3r4
Revises: l8m9n0o1p2q3
Create Date: 2026-02-22 00:00:00.000000

Daily undo limits have been removed from the product. The columns
is_premium, daily_undo_count, and undo_count_reset_date are no longer
needed on the users table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'm9n0o1p2q3r4'
down_revision: Union[str, Sequence[str], None] = 'l8m9n0o1p2q3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop daily undo limit and premium columns from users."""
    op.drop_column('users', 'undo_count_reset_date')
    op.drop_column('users', 'daily_undo_count')
    op.drop_column('users', 'is_premium')


def downgrade() -> None:
    """Re-add daily undo limit and premium columns to users."""
    op.add_column(
        'users',
        sa.Column('is_premium', sa.Boolean(), nullable=False, server_default='false')
    )
    op.add_column(
        'users',
        sa.Column('daily_undo_count', sa.Integer(), nullable=False, server_default='0')
    )
    op.add_column(
        'users',
        sa.Column('undo_count_reset_date', sa.Date(), nullable=True)
    )
