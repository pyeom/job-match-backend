"""Add avatar columns to users

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2026-01-21 22:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h3i4j5k6l7m8'
down_revision: Union[str, Sequence[str], None] = 'b1a4a4bd8436'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add avatar_url and avatar_thumbnail_url columns to users table."""
    op.add_column('users', sa.Column('avatar_url', sa.String(length=500), nullable=True))
    op.add_column('users', sa.Column('avatar_thumbnail_url', sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Remove avatar columns from users table."""
    op.drop_column('users', 'avatar_thumbnail_url')
    op.drop_column('users', 'avatar_url')
