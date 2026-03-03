"""Add work_arrangement column to users table

Revision ID: o1p2q3r4s5t6
Revises: n0o1p2q3r4s5
Create Date: 2026-03-03 00:00:00.000000

Adds work_arrangement as a nullable JSON column that stores a list of
preferred work arrangements for a user (e.g. Remote, Hybrid, On-site).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'o1p2q3r4s5t6'
down_revision: Union[str, Sequence[str], None] = 'n0o1p2q3r4s5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('work_arrangement', sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('users', 'work_arrangement')
