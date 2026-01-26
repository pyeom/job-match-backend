"""
Pydantic schemas for document upload and management.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class DocumentBase(BaseModel):
    """Base schema for document data."""
    document_type: str = Field(..., description="Type: resume, cover_letter, portfolio, certificate, other")
    label: Optional[str] = Field(None, max_length=100, description="User-defined label")
    is_default: bool = Field(False, description="Whether this is the default document of its type")

    @field_validator('document_type')
    @classmethod
    def validate_document_type(cls, v: str) -> str:
        allowed_types = {"resume", "cover_letter", "portfolio", "certificate", "other"}
        if v not in allowed_types:
            raise ValueError(f"document_type must be one of: {', '.join(allowed_types)}")
        return v


class DocumentCreate(DocumentBase):
    """Schema for creating a new document (metadata only, file is uploaded separately)."""
    pass


class DocumentUpdate(BaseModel):
    """Schema for updating document metadata."""
    label: Optional[str] = Field(None, max_length=100)
    is_default: Optional[bool] = None


class DocumentUploadResponse(BaseModel):
    """Response after successful document upload."""
    id: UUID
    filename: str
    original_name: str
    file_type: str
    file_size: int
    document_type: str
    is_default: bool
    label: Optional[str]
    storage_path: str
    version: int
    created_at: datetime
    message: str = "Document uploaded successfully"

    class Config:
        from_attributes = True


class DocumentResponse(BaseModel):
    """Full document metadata response."""
    id: UUID
    user_id: UUID
    filename: str
    original_name: str
    file_type: str
    file_size: int
    document_type: str
    is_default: bool
    label: Optional[str]
    storage_path: str
    version: int
    parent_document_id: Optional[UUID]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """Response for listing multiple documents."""
    documents: List[DocumentResponse]
    total: int


class DocumentDeleteResponse(BaseModel):
    """Response after successful document deletion."""
    message: str
    document_id: UUID


class DocumentVersionResponse(BaseModel):
    """Response for document version information."""
    id: UUID
    document_id: UUID
    version_number: int
    filename: str
    original_name: str
    file_type: str
    file_size: int
    storage_path: str
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentVersionListResponse(BaseModel):
    """Response for listing document versions."""
    versions: List[DocumentVersionResponse]
    total: int


class DocumentDownloadResponse(BaseModel):
    """Response with document download URL or metadata."""
    document_id: UUID
    filename: str
    original_name: str
    file_type: str
    file_size: int
    download_url: str
    expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True
