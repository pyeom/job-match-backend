"""enable_pgvector_extension

Revision ID: 69bfa9d0a9d2
Revises:
Create Date: 2025-09-23 00:32:32.143255

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '69bfa9d0a9d2'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable pgvector extension for vector similarity searches."""
    # Enable the pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Disable pgvector extension."""
    # Drop the pgvector extension (this will fail if any vector columns exist)
    # In practice, this should rarely be used in production
    op.execute("DROP EXTENSION IF EXISTS vector")
