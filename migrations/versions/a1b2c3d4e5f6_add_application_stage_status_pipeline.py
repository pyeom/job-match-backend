"""add application stage status pipeline

Revision ID: a1b2c3d4e5f6
Revises: 755a6028d870
Create Date: 2025-10-21 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '755a6028d870'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Map old status to new (stage, status) tuple
OLD_TO_NEW_MAPPING = {
    'SUBMITTED': ('SUBMITTED', 'ACTIVE'),
    'WAITING_FOR_REVIEW': ('REVIEW', 'ACTIVE'),
    'HR_MEETING': ('INTERVIEW', 'ACTIVE'),
    'TECHNICAL_INTERVIEW': ('TECHNICAL', 'ACTIVE'),
    'FINAL_INTERVIEW': ('DECISION', 'ACTIVE'),
    'HIRED': ('DECISION', 'HIRED'),
    'REJECTED': ('SUBMITTED', 'REJECTED')
}


def upgrade() -> None:
    """Upgrade schema."""
    # Add new columns
    op.add_column('applications', sa.Column('stage', sa.String(length=25), nullable=True, server_default='SUBMITTED'))
    op.add_column('applications', sa.Column('new_status', sa.String(length=25), nullable=True, server_default='ACTIVE'))
    op.add_column('applications', sa.Column('stage_updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.add_column('applications', sa.Column('rejection_reason', sa.Text(), nullable=True))
    op.add_column('applications', sa.Column('stage_history', JSONB, nullable=True))

    # Create indexes
    op.create_index('ix_applications_stage', 'applications', ['stage'])
    op.create_index('ix_applications_new_status', 'applications', ['new_status'])

    # Migrate existing data
    connection = op.get_bind()

    # Update new columns based on old status
    for old_status, (new_stage, new_status) in OLD_TO_NEW_MAPPING.items():
        connection.execute(
            text(
                "UPDATE applications SET stage = :stage, new_status = :status, "
                "stage_history = '[]'::jsonb WHERE status = :old_status"
            ),
            {"stage": new_stage, "status": new_status, "old_status": old_status}
        )

    # Handle any statuses not in the mapping
    connection.execute(
        text(
            "UPDATE applications SET stage = 'SUBMITTED', new_status = 'ACTIVE', "
            "stage_history = '[]'::jsonb WHERE stage IS NULL"
        )
    )

    # Drop old status column index
    op.drop_index('ix_applications_status', table_name='applications')

    # Drop old status column
    op.drop_column('applications', 'status')

    # Rename new_status to status
    op.alter_column('applications', 'new_status', new_column_name='status')

    # Rename the index as well
    op.drop_index('ix_applications_new_status', table_name='applications')
    op.create_index('ix_applications_status', 'applications', ['status'])

    # Make columns NOT NULL now that data is migrated
    op.alter_column('applications', 'stage', nullable=False)
    op.alter_column('applications', 'status', nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Add back old status column
    op.add_column('applications', sa.Column('old_status', sa.String(length=25), nullable=True))

    # Migrate data back from new schema to old schema
    connection = op.get_bind()

    # Reverse mapping
    reverse_mapping = {
        ('SUBMITTED', 'ACTIVE'): 'SUBMITTED',
        ('REVIEW', 'ACTIVE'): 'WAITING_FOR_REVIEW',
        ('INTERVIEW', 'ACTIVE'): 'HR_MEETING',
        ('TECHNICAL', 'ACTIVE'): 'TECHNICAL_INTERVIEW',
        ('DECISION', 'ACTIVE'): 'FINAL_INTERVIEW',
        ('DECISION', 'HIRED'): 'HIRED',
        ('SUBMITTED', 'REJECTED'): 'REJECTED',
        ('REVIEW', 'REJECTED'): 'REJECTED',
        ('INTERVIEW', 'REJECTED'): 'REJECTED',
        ('TECHNICAL', 'REJECTED'): 'REJECTED',
        ('DECISION', 'REJECTED'): 'REJECTED',
    }

    for (stage, status), old_status in reverse_mapping.items():
        connection.execute(
            text(
                "UPDATE applications SET old_status = :old_status "
                "WHERE stage = :stage AND status = :status"
            ),
            {"old_status": old_status, "stage": stage, "status": status}
        )

    # Default any remaining to SUBMITTED
    connection.execute(
        text("UPDATE applications SET old_status = 'SUBMITTED' WHERE old_status IS NULL")
    )

    # Rename old_status to status
    op.alter_column('applications', 'old_status', new_column_name='status', nullable=False)

    # Create index on old status
    op.create_index('ix_applications_status', 'applications', ['status'])

    # Drop new columns
    op.drop_index('ix_applications_new_status', table_name='applications')
    op.drop_index('ix_applications_stage', table_name='applications')
    op.drop_column('applications', 'stage_history')
    op.drop_column('applications', 'rejection_reason')
    op.drop_column('applications', 'stage_updated_at')
    op.drop_column('applications', 'stage')
