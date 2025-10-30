"""add swipes rejected index

Revision ID: b7c8d9e0f1g2
Revises: 1f84f9fa910c
Create Date: 2025-10-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c8d9e0f1g2'
down_revision: Union[str, Sequence[str], None] = '1f84f9fa910c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add optimized index for rejected jobs queries.

    This creates a partial index on swipes table specifically for LEFT swipes,
    optimized for the rejected jobs history endpoint which filters by:
    - user_id (for user-specific queries)
    - direction = 'LEFT' (only rejected jobs)
    - created_at (for ordering newest first)

    The partial index (WHERE direction = 'LEFT') is more efficient than a full index
    because it only indexes rejected swipes, reducing index size and improving query performance.
    """
    # Create partial index for rejected swipes queries
    # This index supports: WHERE user_id = X AND direction = 'LEFT' ORDER BY created_at DESC
    op.create_index(
        'idx_swipes_user_direction_created',
        'swipes',
        ['user_id', 'direction', 'created_at', 'id'],
        postgresql_where=sa.text("direction = 'LEFT'"),
        unique=False
    )


def downgrade() -> None:
    """Remove the rejected jobs index."""
    op.drop_index('idx_swipes_user_direction_created', table_name='swipes')
