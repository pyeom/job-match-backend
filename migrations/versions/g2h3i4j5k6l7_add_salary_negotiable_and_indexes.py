"""add_salary_negotiable_and_indexes

Revision ID: g2h3i4j5k6l7
Revises: f1a2b3c4d5e6
Create Date: 2026-01-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g2h3i4j5k6l7'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add salary_negotiable field and create indexes for filtering."""

    # Add salary_negotiable column to jobs table
    op.add_column('jobs', sa.Column('salary_negotiable', sa.Boolean(), server_default=sa.text('false'), nullable=True))

    # Create indexes on jobs table for filter performance
    # work_arrangement and job_type indexes (if they don't already exist)
    op.create_index('ix_jobs_work_arrangement', 'jobs', ['work_arrangement'], unique=False)
    op.create_index('ix_jobs_job_type', 'jobs', ['job_type'], unique=False)

    # Create index on salary_negotiable for filtering
    op.create_index('ix_jobs_salary_negotiable', 'jobs', ['salary_negotiable'], unique=False)

    # Create composite index for salary filtering (useful for range queries)
    op.create_index('ix_jobs_salary_range', 'jobs', ['salary_min', 'salary_max'], unique=False)

    # Create composite index for active jobs + work_arrangement (common filter combination)
    op.create_index('ix_jobs_active_arrangement', 'jobs', ['is_active', 'work_arrangement'], unique=False)

    # Create composite index for active jobs + job_type (common filter combination)
    op.create_index('ix_jobs_active_type', 'jobs', ['is_active', 'job_type'], unique=False)


def downgrade() -> None:
    """Downgrade schema - remove salary_negotiable field and indexes."""

    # Drop composite indexes
    op.drop_index('ix_jobs_active_type', 'jobs')
    op.drop_index('ix_jobs_active_arrangement', 'jobs')
    op.drop_index('ix_jobs_salary_range', 'jobs')
    op.drop_index('ix_jobs_salary_negotiable', 'jobs')

    # Drop single column indexes
    op.drop_index('ix_jobs_job_type', 'jobs')
    op.drop_index('ix_jobs_work_arrangement', 'jobs')

    # Remove salary_negotiable column
    op.drop_column('jobs', 'salary_negotiable')
