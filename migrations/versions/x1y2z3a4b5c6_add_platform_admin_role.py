"""add_platform_admin_role

Revision ID: x1y2z3a4b5c6
Revises: w0x1y2z3a4b5
Create Date: 2026-04-11 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "x1y2z3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "w0x1y2z3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL requires this two-step approach to add a value to an existing enum
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'platform_admin'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; a full type replacement is needed
    op.execute("""
        ALTER TABLE users
            ALTER COLUMN role TYPE VARCHAR(50);
        DROP TYPE userrole;
        CREATE TYPE userrole AS ENUM ('job_seeker', 'company_recruiter', 'company_admin');
        UPDATE users SET role = 'job_seeker' WHERE role = 'platform_admin';
        ALTER TABLE users
            ALTER COLUMN role TYPE userrole USING role::userrole;
    """)
