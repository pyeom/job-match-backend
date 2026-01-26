"""
Document model for storing user resumes, cover letters, and other documents.
"""
from sqlalchemy import Column, DateTime, ForeignKey, String, Integer, Boolean, Text
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.core.database import Base


class Document(Base):
    """
    Stores user documents (resumes, cover letters, etc.)
    """
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # File metadata
    filename = Column(String(255), nullable=False)  # UUID-based unique filename
    original_name = Column(String(255), nullable=False)  # User's original filename
    file_type = Column(String(50), nullable=False)  # MIME type (application/pdf, etc.)
    file_size = Column(Integer, nullable=False)  # File size in bytes

    # Document classification
    document_type = Column(String(50), nullable=False, index=True)
    # Values: "resume", "cover_letter", "portfolio", "certificate", "other"

    is_default = Column(Boolean, default=False, nullable=False, index=True)
    # Whether this is the default document of its type for the user

    label = Column(String(100), nullable=True)
    # User-defined label (e.g., "Software Engineer Resume", "Generic Cover Letter")

    # Storage
    storage_path = Column(String(500), nullable=False)
    # Relative path: media/documents/{user_id}/{filename}

    # Optional extracted text for search/parsing
    extracted_text = Column(Text, nullable=True)

    # Version tracking
    version = Column(Integer, default=1, nullable=False)
    # Current version number

    parent_document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    # For tracking document replacements/updates

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="documents")
    versions = relationship("DocumentVersion", back_populates="document", cascade="all, delete-orphan")

    # Applications that use this document
    applications_as_resume = relationship("Application", foreign_keys="Application.resume_id", back_populates="resume_document")
    applications_as_cover_letter = relationship("Application", foreign_keys="Application.cover_letter_id", back_populates="cover_letter_document")

    def __repr__(self):
        return f"<Document(id={self.id}, user_id={self.user_id}, type={self.document_type}, label={self.label})>"


class DocumentVersion(Base):
    """
    Tracks version history of documents for rollback capability.
    """
    __tablename__ = "document_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)

    # Version metadata
    version_number = Column(Integer, nullable=False)
    # Version number of this snapshot

    # File metadata snapshot
    filename = Column(String(255), nullable=False)
    original_name = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)
    file_size = Column(Integer, nullable=False)
    storage_path = Column(String(500), nullable=False)

    # Optional extracted text
    extracted_text = Column(Text, nullable=True)

    # Timestamp
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationships
    document = relationship("Document", back_populates="versions")

    def __repr__(self):
        return f"<DocumentVersion(id={self.id}, document_id={self.document_id}, version={self.version_number})>"
