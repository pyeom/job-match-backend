"""Add email_verified column to users table

Revision ID: p2q3r4s5t6u7
Revises: o1p2q3r4s5t6
Create Date: 2026-03-07 00:00:00.000000

Adds email_verified boolean column (default False for new users).
Existing users are backfilled to True so they are not locked out.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'p2q3r4s5t6u7'
down_revision: Union[str, Sequence[str], None] = 'o1p2q3r4s5t6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add column as nullable first so we can backfill
    op.add_column(
        'users',
        sa.Column('email_verified', sa.Boolean(), nullable=True)
    )
    # Mark all existing users as verified so they are not locked out
    op.execute("UPDATE users SET email_verified = TRUE")
    # Now make it non-nullable with default False for new rows
    op.alter_column('users', 'email_verified', nullable=False, server_default=sa.false())


def downgrade() -> None:
    op.drop_column('users', 'email_verified')
