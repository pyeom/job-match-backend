"""Add remaining composite indexes for TASK-018

Revision ID: q3r4s5t6u7v8
Revises: p2q3r4s5t6u7
Create Date: 2026-03-08 00:00:00.000000

Adds the three composite indexes not yet covered by n0o1p2q3r4s5:

- swipes(user_id, created_at DESC): undo window query — find swipes in the
  last 120 seconds for a user (TASK-003 undo feature)
- applications(user_id, stage): user's applications filtered by pipeline stage
  (Matches tab; existing ix_applications_job_stage covers the job/company side)
- jobs(is_active, created_at DESC): PostgreSQL fallback query when Elasticsearch
  is unavailable — active jobs ordered by recency

Already covered by migration n0o1p2q3r4s5 (not duplicated here):
- swipes(user_id, is_undone) → ix_swipes_user_is_undone
- applications(job_id, stage) → ix_applications_job_stage
- notifications(user_id, is_read, created_at DESC) → ix_notifications_user_unread

Note: applications(company_id, stage) from the PRD is not applicable — the
Application model has no company_id column; company filtering goes through jobs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'q3r4s5t6u7v8'
down_revision: Union[str, Sequence[str], None] = 'p2q3r4s5t6u7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Undo window: find swipes made in the last 120 seconds for a user
    # Query: WHERE user_id = X AND created_at > NOW() - INTERVAL '120 seconds'
    # ORDER BY created_at DESC
    op.create_index(
        'ix_swipes_user_created_at',
        'swipes',
        ['user_id', sa.text('created_at DESC')],
    )

    # User's applications filtered by pipeline stage (Matches tab)
    # Query: WHERE user_id = X AND stage = Y
    op.create_index(
        'ix_applications_user_stage',
        'applications',
        ['user_id', 'stage'],
    )

    # PG fallback query when Elasticsearch is unavailable
    # Query: WHERE is_active = true ORDER BY created_at DESC
    op.create_index(
        'ix_jobs_active_created_at',
        'jobs',
        ['is_active', sa.text('created_at DESC')],
    )


def downgrade() -> None:
    op.drop_index('ix_jobs_active_created_at', table_name='jobs')
    op.drop_index('ix_applications_user_stage', table_name='applications')
    op.drop_index('ix_swipes_user_created_at', table_name='swipes')
