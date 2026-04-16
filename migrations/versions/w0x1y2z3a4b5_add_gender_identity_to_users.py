"""add_gender_identity_to_users

Revision ID: w0x1y2z3a4b5
Revises: v9w0x1y2z3a4
Create Date: 2026-04-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "w0x1y2z3a4b5"
down_revision: Union[str, None] = "v9w0x1y2z3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("gender_identity", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "gender_identity")
