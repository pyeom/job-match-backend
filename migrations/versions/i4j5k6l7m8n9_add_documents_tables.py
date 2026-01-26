"""Add documents and document_versions tables

Revision ID: i4j5k6l7m8n9
Revises: h3i4j5k6l7m8
Create Date: 2026-01-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'i4j5k6l7m8n9'
down_revision: Union[str, Sequence[str], None] = 'h3i4j5k6l7m8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create documents and document_versions tables."""

    # Create documents table
    op.create_table(
        'documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('original_name', sa.String(length=255), nullable=False),
        sa.Column('file_type', sa.String(length=50), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('document_type', sa.String(length=50), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('label', sa.String(length=100), nullable=True),
        sa.Column('storage_path', sa.String(length=500), nullable=False),
        sa.Column('extracted_text', sa.Text(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('parent_document_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_document_id'], ['documents.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for documents
    op.create_index('ix_documents_id', 'documents', ['id'])
    op.create_index('ix_documents_user_id', 'documents', ['user_id'])
    op.create_index('ix_documents_document_type', 'documents', ['document_type'])
    op.create_index('ix_documents_is_default', 'documents', ['is_default'])
    op.create_index('ix_documents_created_at', 'documents', ['created_at'])

    # Create document_versions table
    op.create_table(
        'document_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('original_name', sa.String(length=255), nullable=False),
        sa.Column('file_type', sa.String(length=50), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('storage_path', sa.String(length=500), nullable=False),
        sa.Column('extracted_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for document_versions
    op.create_index('ix_document_versions_id', 'document_versions', ['id'])
    op.create_index('ix_document_versions_document_id', 'document_versions', ['document_id'])
    op.create_index('ix_document_versions_created_at', 'document_versions', ['created_at'])

    # Add document columns to applications table
    op.add_column('applications', sa.Column('resume_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('applications', sa.Column('cover_letter_id', postgresql.UUID(as_uuid=True), nullable=True))

    op.create_foreign_key(
        'fk_applications_resume_id',
        'applications', 'documents',
        ['resume_id'], ['id'],
        ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_applications_cover_letter_id',
        'applications', 'documents',
        ['cover_letter_id'], ['id'],
        ondelete='SET NULL'
    )

    op.create_index('ix_applications_resume_id', 'applications', ['resume_id'])
    op.create_index('ix_applications_cover_letter_id', 'applications', ['cover_letter_id'])


def downgrade() -> None:
    """Drop documents and document_versions tables."""

    # Drop indexes and foreign keys from applications
    op.drop_index('ix_applications_cover_letter_id', 'applications')
    op.drop_index('ix_applications_resume_id', 'applications')
    op.drop_constraint('fk_applications_cover_letter_id', 'applications', type_='foreignkey')
    op.drop_constraint('fk_applications_resume_id', 'applications', type_='foreignkey')
    op.drop_column('applications', 'cover_letter_id')
    op.drop_column('applications', 'resume_id')

    # Drop document_versions table and indexes
    op.drop_index('ix_document_versions_created_at', 'document_versions')
    op.drop_index('ix_document_versions_document_id', 'document_versions')
    op.drop_index('ix_document_versions_id', 'document_versions')
    op.drop_table('document_versions')

    # Drop documents table and indexes
    op.drop_index('ix_documents_created_at', 'documents')
    op.drop_index('ix_documents_is_default', 'documents')
    op.drop_index('ix_documents_document_type', 'documents')
    op.drop_index('ix_documents_user_id', 'documents')
    op.drop_index('ix_documents_id', 'documents')
    op.drop_table('documents')
