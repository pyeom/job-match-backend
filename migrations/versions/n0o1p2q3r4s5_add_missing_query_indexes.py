"""Add missing database indexes for key query patterns

Revision ID: n0o1p2q3r4s5
Revises: m9n0o1p2q3r4
Create Date: 2026-02-23 00:00:00.000000

Adds indexes for high-frequency query patterns that were missing:
- GIN index on jobs.tags (JSONB) for skill overlap / tag filter queries
- Composite index on applications(job_id, stage) for stage-filtered lookups
- Composite index on notifications(user_id, is_read, created_at DESC) for unread queries
- Index on push_tokens(user_id) for token lookups per user
- Composite index on interactions(user_id, action) for embedding update calculations
- Composite index on swipes(user_id, is_undone) for undo-aware right-swipe counts

Note: ix_jobs_work_arrangement, ix_jobs_salary_range, and ix_jobs_salary_negotiable
already exist from migration g2h3i4j5k6l7 and are not duplicated here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'n0o1p2q3r4s5'
down_revision: Union[str, Sequence[str], None] = 'm9n0o1p2q3r4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # GIN index on jobs.tags for skill overlap and tag filter queries
    # Cast to jsonb since the column is json type (json has no default GIN operator class)
    op.execute(
        "CREATE INDEX ix_jobs_tags_gin ON jobs USING gin ((tags::jsonb))"
    )

    # Composite index for applications filtered by job + stage
    op.create_index(
        'ix_applications_job_stage',
        'applications',
        ['job_id', 'stage'],
    )

    # Composite index for unread notifications per user (DESC on created_at for latest-first)
    op.create_index(
        'ix_notifications_user_unread',
        'notifications',
        ['user_id', 'is_read', 'created_at'],
        postgresql_ops={'created_at': 'DESC NULLS LAST'},
    )

    # Composite index on interactions for embedding update calculations
    op.create_index(
        'ix_interactions_user_action',
        'interactions',
        ['user_id', 'action'],
    )

    # Composite index on swipes(user_id, is_undone) for counting active right swipes
    op.create_index(
        'ix_swipes_user_is_undone',
        'swipes',
        ['user_id', 'is_undone'],
    )


def downgrade() -> None:
    op.drop_index('ix_swipes_user_is_undone', table_name='swipes')
    op.drop_index('ix_interactions_user_action', table_name='interactions')
    op.drop_index('ix_notifications_user_unread', table_name='notifications')
    op.drop_index('ix_applications_job_stage', table_name='applications')
    op.drop_index('ix_jobs_tags_gin', table_name='jobs')
