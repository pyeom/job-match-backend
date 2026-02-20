"""add notification delivery status

Revision ID: k7l8m9n0o1p2
Revises: j6k7l8m9n0o1
Create Date: 2026-02-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'k7l8m9n0o1p2'
down_revision = 'j6k7l8m9n0o1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the PostgreSQL enum type first
    deliverystatus_enum = sa.Enum('pending', 'delivered', 'failed', name='deliverystatus')
    deliverystatus_enum.create(op.get_bind(), checkfirst=True)

    # Add the delivery_status column to notifications
    op.add_column(
        'notifications',
        sa.Column(
            'delivery_status',
            sa.Enum('pending', 'delivered', 'failed', name='deliverystatus'),
            nullable=False,
            server_default='pending',
        )
    )


def downgrade() -> None:
    # Drop the column first
    op.drop_column('notifications', 'delivery_status')

    # Drop the enum type
    deliverystatus_enum = sa.Enum('pending', 'delivered', 'failed', name='deliverystatus')
    deliverystatus_enum.drop(op.get_bind(), checkfirst=True)
