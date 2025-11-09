"""add_push_tokens_table

Revision ID: 14c802373b8e
Revises: 33187c03ccd5
Create Date: 2025-11-08 20:28:26.283984

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '14c802373b8e'
down_revision: Union[str, Sequence[str], None] = '33187c03ccd5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create push_tokens table
    op.create_table(
        'push_tokens',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('company_id', sa.UUID(), nullable=True),
        sa.Column('token', sa.String(length=255), nullable=False),
        sa.Column('platform', sa.String(length=20), nullable=False),
        sa.Column('device_name', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('last_used_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('token'),
        sa.CheckConstraint(
            '(user_id IS NOT NULL AND company_id IS NULL) OR (user_id IS NULL AND company_id IS NOT NULL)',
            name='check_recipient'
        )
    )

    # Create indexes
    op.create_index('ix_push_tokens_id', 'push_tokens', ['id'])
    op.create_index('ix_push_tokens_user_id', 'push_tokens', ['user_id'])
    op.create_index('ix_push_tokens_company_id', 'push_tokens', ['company_id'])
    op.create_index('ix_push_tokens_token', 'push_tokens', ['token'])
    op.create_index('ix_push_tokens_is_active', 'push_tokens', ['is_active'])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes
    op.drop_index('ix_push_tokens_is_active', 'push_tokens')
    op.drop_index('ix_push_tokens_token', 'push_tokens')
    op.drop_index('ix_push_tokens_company_id', 'push_tokens')
    op.drop_index('ix_push_tokens_user_id', 'push_tokens')
    op.drop_index('ix_push_tokens_id', 'push_tokens')

    # Drop table
    op.drop_table('push_tokens')
