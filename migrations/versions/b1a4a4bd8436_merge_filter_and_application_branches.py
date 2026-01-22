"""merge_filter_and_application_branches

Revision ID: b1a4a4bd8436
Revises: e583491ed753, g2h3i4j5k6l7
Create Date: 2026-01-21 21:42:19.920943

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1a4a4bd8436'
down_revision: Union[str, Sequence[str], None] = ('e583491ed753', 'g2h3i4j5k6l7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
