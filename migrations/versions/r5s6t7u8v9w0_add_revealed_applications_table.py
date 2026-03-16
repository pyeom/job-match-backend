"""add_revealed_applications_table

Revision ID: r5s6t7u8v9w0
Revises: q3r4s5t6u7v8
Create Date: 2026-03-16 00:00:00.000000

Adds the ``revealed_applications`` table used by TASK-041 (always-on
candidate anonymization / blind review).

A row in this table means a company recruiter has explicitly chosen to
reveal the identity of an applicant.  The UNIQUE constraint on
``application_id`` enforces the "reveal once, permanent" invariant —
a candidate's identity can only be revealed once per application.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "r5s6t7u8v9w0"
down_revision: Union[str, Sequence[str], None] = "q3r4s5t6u7v8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create revealed_applications table."""
    op.create_table(
        "revealed_applications",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "revealed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "revealed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("stage_at_reveal", sa.String(25), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "application_id",
            name="uq_revealed_applications_application_id",
        ),
    )
    op.create_index(
        "ix_revealed_applications_application_id",
        "revealed_applications",
        ["application_id"],
    )


def downgrade() -> None:
    """Drop revealed_applications table."""
    op.drop_index(
        "ix_revealed_applications_application_id",
        table_name="revealed_applications",
    )
    op.drop_table("revealed_applications")
