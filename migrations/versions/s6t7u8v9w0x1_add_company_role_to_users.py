"""add_company_role_to_users

Revision ID: s6t7u8v9w0x1
Revises: r5s6t7u8v9w0
Create Date: 2026-04-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "s6t7u8v9w0x1"
down_revision: Union[str, Sequence[str], None] = "r5s6t7u8v9w0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE companyrole AS ENUM ('admin', 'recruiter', 'hiring_manager', 'viewer')")
    op.add_column(
        "users",
        sa.Column("company_role", sa.Enum("admin", "recruiter", "hiring_manager", "viewer", name="companyrole"), nullable=True),
    )
    op.create_index("ix_users_company_role", "users", ["company_role"])
    op.execute("UPDATE users SET company_role = 'admin' WHERE role::text ILIKE 'company_admin'")
    op.execute("UPDATE users SET company_role = 'recruiter' WHERE role::text ILIKE 'company_recruiter'")


def downgrade() -> None:
    op.drop_index("ix_users_company_role", table_name="users")
    op.drop_column("users", "company_role")
    op.execute("DROP TYPE companyrole")
