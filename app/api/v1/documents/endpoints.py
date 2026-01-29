"""
Document upload and management endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from uuid import UUID

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.document import Document
from app.schemas.document import (
    DocumentUploadResponse, DocumentResponse, DocumentListResponse,
    DocumentDeleteResponse, DocumentUpdate, DocumentVersionListResponse,
    DocumentVersionResponse, DocumentDownloadResponse
)
from app.repositories.document_repository import document_repository
from app.services.document_service import document_service
from app.services.storage_service import storage_service
from app.services.document_parser import document_parser
from app.services.resume_parser_service import resume_parser_service
from app.services.user_service import user_service
import uuid as uuid_lib
import logging

logger = logging.getLogger(__name__)


async def auto_parse_resume_and_update_profile(
    db: AsyncSession,
    user: User,
    extracted_text: str,
    document_id: UUID
):
    """
    Automatically parse a resume and update the user's profile.
    This runs in the background after a resume upload.
    """
    try:
        if not extracted_text:
            logger.warning(f"No extracted text for document {document_id}, skipping auto-parse")
            return

        # Parse the resume
        parsed_data = resume_parser_service.parse_resume(
            resume_text=extracted_text,
            document_id=str(document_id)
        )

        logger.info(
            f"Auto-parsed resume {document_id} for user {user.id}, "
            f"confidence: {parsed_data.confidence_score:.2f}, "
            f"skills found: {len(parsed_data.skills.all_skills)}"
        )

        # Only auto-update if we have reasonable confidence
        if parsed_data.confidence_score >= 0.3:
            updated_user, fields_updated = await user_service.update_profile_from_resume(
                db=db,
                user=user,
                parsed_data=parsed_data
            )

            if fields_updated:
                logger.info(
                    f"Auto-updated profile for user {user.id} from resume {document_id}. "
                    f"Fields updated: {fields_updated}"
                )
        else:
            logger.info(
                f"Skipping auto-update for user {user.id}, "
                f"confidence too low: {parsed_data.confidence_score:.2f}"
            )

    except Exception as e:
        logger.error(f"Error in auto_parse_resume_and_update_profile for document {document_id}: {e}")
        # Don't raise - this is a background task, shouldn't fail the upload

router = APIRouter()


@router.post("", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(..., description="Document file (PDF, DOC, or DOCX, max 10MB)"),
    document_type: str = Query(..., description="Type: resume, cover_letter, portfolio, certificate, other"),
    label: Optional[str] = Query(None, max_length=100, description="User-defined label"),
    is_default: bool = Query(False, description="Set as default document of this type"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload a new document (resume, cover letter, etc.).

    Accepts PDF, DOC, or DOCX files up to 10MB.
    Documents are:
    - Validated for MIME type and file size
    - Stored with UUID-based unique filenames
    - Optionally parsed for text extraction
    - Can be set as default document of its type
    """
    # Validate document type
    allowed_types = {"resume", "cover_letter", "portfolio", "certificate", "other"}
    if document_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid document_type. Allowed: {', '.join(allowed_types)}"
        )

    # Validate the uploaded file
    try:
        mime_type, extension = await document_service.validate_document(file)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating document: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate document: {str(e)}"
        )

    # Read file content
    try:
        await file.seek(0)
        file_content = await file.read()
    except Exception as e:
        logger.error(f"Error reading file content: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read file content"
        )

    # Save document to storage
    try:
        storage_path, file_path = await storage_service.save_document(
            user_id=current_user.id,
            file_content=file_content,
            original_filename=file.filename
        )
        filename = storage_service.extract_filename_from_storage_path(storage_path)
    except Exception as e:
        logger.error(f"Error saving document: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save document: {str(e)}"
        )

    # Extract text from document (optional, non-blocking)
    extracted_text = None
    try:
        extracted_text = document_parser.extract_text(file_content, mime_type)
    except Exception as e:
        logger.warning(f"Failed to extract text from document: {e}")
        # Continue even if text extraction fails

    # Create document record in database
    try:
        document_data = {
            "user_id": current_user.id,
            "filename": filename,
            "original_name": file.filename,
            "file_type": mime_type,
            "file_size": len(file_content),
            "document_type": document_type,
            "is_default": is_default,
            "label": label,
            "storage_path": storage_path,
            "extracted_text": extracted_text,
            "version": 1
        }

        document = await document_repository.create(db, document_data)

        # If set as default, unset other defaults of the same type
        if is_default:
            await document_repository.set_default_document(
                db, current_user.id, document.id, document_type
            )

        await db.commit()
        await db.refresh(document)

        # Auto-parse resume and update profile if this is a resume
        if document_type == "resume" and extracted_text:
            await auto_parse_resume_and_update_profile(
                db=db,
                user=current_user,
                extracted_text=extracted_text,
                document_id=document.id
            )

    except Exception as e:
        await db.rollback()
        # Clean up uploaded file
        if filename:
            await storage_service.delete_document(current_user.id, filename)

        logger.error(f"Error creating document record: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create document record: {str(e)}"
        )

    return DocumentUploadResponse(
        id=document.id,
        filename=document.filename,
        original_name=document.original_name,
        file_type=document.file_type,
        file_size=document.file_size,
        document_type=document.document_type,
        is_default=document.is_default,
        label=document.label,
        storage_path=document.storage_path,
        version=document.version,
        created_at=document.created_at,
        message="Document uploaded successfully"
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    document_type: Optional[str] = Query(None, description="Filter by document type"),
    skip: int = Query(0, ge=0, description="Number of documents to skip"),
    limit: int = Query(100, ge=1, le=100, description="Number of documents to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all documents for the current user.

    Supports filtering by document type and pagination.
    """
    try:
        documents, total = await document_repository.get_by_user(
            db, current_user.id, document_type, skip, limit
        )

        return DocumentListResponse(
            documents=[DocumentResponse.model_validate(doc) for doc in documents],
            total=total
        )
    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list documents"
        )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get document metadata by ID.

    Returns document information without downloading the file.
    """
    try:
        document = await document_repository.get(db, document_id)

        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )

        # Verify ownership
        if document.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. You can only access your own documents."
            )

        return DocumentResponse.model_validate(document)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching document {document_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch document"
        )


@router.get("/{document_id}/download", response_class=FileResponse)
async def download_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Download a document file.

    Returns the actual file for download.
    """
    try:
        document = await document_repository.get(db, document_id)

        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )

        # Verify ownership
        if document.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. You can only download your own documents."
            )

        # Get file path
        file_path = storage_service.get_document_path(
            current_user.id,
            document.filename
        )

        if not file_path.exists():
            logger.error(f"Document file not found: {file_path}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document file not found on server"
            )

        # Return file for download
        return FileResponse(
            path=str(file_path),
            filename=document.original_name,
            media_type=document.file_type
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading document {document_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to download document"
        )


@router.patch("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: UUID,
    update_data: DocumentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update document metadata (label, is_default).

    Does not update the actual file. To update the file, upload a new document.
    """
    try:
        document = await document_repository.get(db, document_id)

        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )

        # Verify ownership
        if document.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. You can only update your own documents."
            )

        # Prepare update data
        update_dict = update_data.model_dump(exclude_unset=True)

        # If setting as default, handle default logic
        if update_dict.get("is_default") is True:
            await document_repository.set_default_document(
                db, current_user.id, document_id, document.document_type
            )
            # Remove is_default from update_dict as it's handled by set_default_document
            update_dict.pop("is_default", None)

        # Update document
        if update_dict:
            document = await document_repository.update(db, document, update_dict)

        await db.commit()
        await db.refresh(document)

        return DocumentResponse.model_validate(document)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating document {document_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update document"
        )


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a document.

    Removes both the database record and the file from storage.
    """
    try:
        document = await document_repository.get(db, document_id)

        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )

        # Verify ownership
        if document.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. You can only delete your own documents."
            )

        # Delete file from storage
        deleted = await storage_service.delete_document(
            current_user.id,
            document.filename
        )

        if not deleted:
            logger.warning(f"Failed to delete file for document {document_id}")

        # Delete document record (this will cascade to versions)
        await document_repository.delete(db, document_id)
        await db.commit()

        return DocumentDeleteResponse(
            message="Document deleted successfully",
            document_id=document_id
        )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting document {document_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete document"
        )


@router.get("/{document_id}/versions", response_model=DocumentVersionListResponse)
async def list_document_versions(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all versions of a document.

    Returns version history for rollback capability.
    """
    try:
        document = await document_repository.get(db, document_id)

        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )

        # Verify ownership
        if document.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. You can only access your own documents."
            )

        # Get versions
        versions = await document_repository.get_versions(db, document_id)

        return DocumentVersionListResponse(
            versions=[DocumentVersionResponse.model_validate(v) for v in versions],
            total=len(versions)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing document versions for {document_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list document versions"
        )
