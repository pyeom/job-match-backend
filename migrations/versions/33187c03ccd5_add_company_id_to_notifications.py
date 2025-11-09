"""add_company_id_to_notifications

Revision ID: 33187c03ccd5
Revises: b7c8d9e0f1g2
Create Date: 2025-11-08 16:01:55.193808

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '33187c03ccd5'
down_revision: Union[str, Sequence[str], None] = 'b7c8d9e0f1g2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add company_id column to notifications table
    op.add_column('notifications', sa.Column('company_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_notifications_company', 'notifications', 'companies', ['company_id'], ['id'])
    op.create_index('ix_notifications_company_id', 'notifications', ['company_id'])
    op.create_index('ix_notifications_company_read_date', 'notifications', ['company_id', 'is_read', 'created_at'])

    # Also add NEW_APPLICATION to the notification type enum
    op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'NEW_APPLICATION'")


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes and foreign key
    op.drop_index('ix_notifications_company_read_date', 'notifications')
    op.drop_index('ix_notifications_company_id', 'notifications')
    op.drop_constraint('fk_notifications_company', 'notifications', type_='foreignkey')
    op.drop_column('notifications', 'company_id')

    # Note: Cannot remove enum value in PostgreSQL without recreating the type
