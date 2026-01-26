"""Add undo swipe tracking

Revision ID: j6k7l8m9n0o1
Revises: i4j5k6l7m8n9
Create Date: 2026-01-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'j6k7l8m9n0o1'
down_revision: Union[str, Sequence[str], None] = 'i4j5k6l7m8n9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add undo tracking columns to swipes and users tables."""
    # Add undo tracking to swipes
    op.add_column('swipes', sa.Column('is_undone', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('swipes', sa.Column('undone_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_swipes_is_undone', 'swipes', ['is_undone'])

    # Add premium and undo counter to users
    op.add_column('users', sa.Column('is_premium', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('daily_undo_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('undo_count_reset_date', sa.Date(), nullable=True))


def downgrade() -> None:
    """Remove undo tracking columns from swipes and users tables."""
    # Remove columns from users
    op.drop_column('users', 'undo_count_reset_date')
    op.drop_column('users', 'daily_undo_count')
    op.drop_column('users', 'is_premium')

    # Remove columns from swipes
    op.drop_index('ix_swipes_is_undone', 'swipes')
    op.drop_column('swipes', 'undone_at')
    op.drop_column('swipes', 'is_undone')
