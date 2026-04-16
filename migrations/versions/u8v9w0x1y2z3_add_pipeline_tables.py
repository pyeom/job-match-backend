"""add_pipeline_tables

Revision ID: u8v9w0x1y2z3
Revises: t7u8v9w0x1y2
Create Date: 2026-04-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "u8v9w0x1y2z3"
down_revision: Union[str, Sequence[str], None] = "t7u8v9w0x1y2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipeline_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("stages", postgresql.JSONB, nullable=False),
        sa.Column("is_default", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_pipeline_templates_company_id", "pipeline_templates", ["company_id"])

    op.create_table(
        "application_stage_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage_order", sa.Integer, nullable=False),
        sa.Column("stage_name", sa.String(100), nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("exited_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text),
        sa.Column("moved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
    )
    op.create_index("ix_application_stage_history_app", "application_stage_history", ["application_id"])


def downgrade() -> None:
    op.drop_index("ix_application_stage_history_app", table_name="application_stage_history")
    op.drop_table("application_stage_history")
    op.drop_index("ix_pipeline_templates_company_id", table_name="pipeline_templates")
    op.drop_table("pipeline_templates")
