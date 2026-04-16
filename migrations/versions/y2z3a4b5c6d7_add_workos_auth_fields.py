"""add_workos_auth_fields

Revision ID: y2z3a4b5c6d7
Revises: x1y2z3a4b5c6
Create Date: 2026-04-14 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "y2z3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "x1y2z3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=True)

    op.add_column(
        "users",
        sa.Column(
            "auth_provider",
            sa.String(50),
            nullable=False,
            server_default="local",
        ),
    )
    op.add_column(
        "users",
        sa.Column("external_id", sa.String(255), nullable=True),
    )

    op.create_index("ix_users_auth_provider", "users", ["auth_provider"])
    op.create_index("ix_users_external_id", "users", ["external_id"])

    op.execute(
        "CREATE UNIQUE INDEX uq_users_external_id ON users (external_id) WHERE external_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_users_external_id")
    op.drop_index("ix_users_external_id", table_name="users")
    op.drop_index("ix_users_auth_provider", table_name="users")
    op.drop_column("users", "external_id")
    op.drop_column("users", "auth_provider")
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=False)
