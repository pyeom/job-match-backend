"""make notifications user_id nullable

Revision ID: c9f8e7d6a5b4
Revises: 14c802373b8e
Create Date: 2025-11-09 18:51:44.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c9f8e7d6a5b4'
down_revision: Union[str, Sequence[str], None] = '14c802373b8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make user_id nullable to allow company notifications."""
    # Make user_id nullable to allow company notifications
    # (notifications can be for either user OR company, not both)
    op.alter_column('notifications', 'user_id',
               existing_type=postgresql.UUID(),
               nullable=True)


def downgrade() -> None:
    """Revert user_id to NOT NULL."""
    # First delete any notifications with NULL user_id
    # (these would be company notifications created after this migration)
    op.execute("DELETE FROM notifications WHERE user_id IS NULL")

    # Then make user_id NOT NULL again
    op.alter_column('notifications', 'user_id',
               existing_type=postgresql.UUID(),
               nullable=False)
