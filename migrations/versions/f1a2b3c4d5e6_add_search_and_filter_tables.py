"""add_search_and_filter_tables

Revision ID: f1a2b3c4d5e6
Revises: 14c802373b8e
Create Date: 2026-01-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = '14c802373b8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add filter_presets and recent_searches tables, plus new job fields."""

    # Add new columns to jobs table
    op.add_column('jobs', sa.Column('currency', sa.String(length=3), server_default='USD', nullable=True))
    op.add_column('jobs', sa.Column('work_arrangement', sa.String(length=50), nullable=True))
    op.add_column('jobs', sa.Column('job_type', sa.String(length=50), nullable=True))

    # Create filter_presets table
    op.create_table(
        'filter_presets',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('filters', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=True, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE')
    )

    # Create indexes for filter_presets
    op.create_index('ix_filter_presets_id', 'filter_presets', ['id'])
    op.create_index('ix_filter_presets_user_id', 'filter_presets', ['user_id'])
    op.create_index('ix_filter_presets_is_default', 'filter_presets', ['is_default'])

    # Create recent_searches table
    op.create_table(
        'recent_searches',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('query', sa.String(length=255), nullable=True),
        sa.Column('filters_used', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('searched_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE')
    )

    # Create indexes for recent_searches
    op.create_index('ix_recent_searches_id', 'recent_searches', ['id'])
    op.create_index('ix_recent_searches_user_id', 'recent_searches', ['user_id'])
    op.create_index('ix_recent_searches_searched_at', 'recent_searches', ['searched_at'])


def downgrade() -> None:
    """Downgrade schema - remove filter_presets and recent_searches tables, plus new job fields."""

    # Drop recent_searches table and indexes
    op.drop_index('ix_recent_searches_searched_at', 'recent_searches')
    op.drop_index('ix_recent_searches_user_id', 'recent_searches')
    op.drop_index('ix_recent_searches_id', 'recent_searches')
    op.drop_table('recent_searches')

    # Drop filter_presets table and indexes
    op.drop_index('ix_filter_presets_is_default', 'filter_presets')
    op.drop_index('ix_filter_presets_user_id', 'filter_presets')
    op.drop_index('ix_filter_presets_id', 'filter_presets')
    op.drop_table('filter_presets')

    # Remove new columns from jobs table
    op.drop_column('jobs', 'job_type')
    op.drop_column('jobs', 'work_arrangement')
    op.drop_column('jobs', 'currency')
