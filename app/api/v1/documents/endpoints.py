"""
Document upload and management endpoints.
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from uuid import UUID

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User, UserRole
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
from app.core.arq import get_arq_pool
import uuid as uuid_lib
import logging

logger = logging.getLogger(__name__)


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

    # Extract text from document (offloaded to thread pool — pdfminer/PyPDF2 are synchronous)
    extracted_text = None
    try:
        extracted_text = await asyncio.to_thread(
            document_parser.extract_text, file_content, mime_type
        )
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

        # Enqueue resume auto-parse (SpaCy NLP, CPU-bound — runs in worker)
        if document_type == "resume" and extracted_text:
            try:
                arq = await get_arq_pool()
                await arq.enqueue_job(
                    "parse_resume_and_update_profile",
                    str(current_user.id),
                    extracted_text,
                    str(document.id),
                )
            except Exception as e:
                logger.warning(f"Failed to enqueue resume parsing for document {document.id}: {e}")

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

    For company users: if the document is a resume attached to an application
    that has not yet been revealed, the download is blocked with HTTP 403.
    This prevents companies from reading a candidate's name and contact details
    directly from the PDF before explicitly choosing to reveal identity.
    """
    from sqlalchemy import select as _select
    from app.models.application import Application, RevealedApplication

    try:
        document = await document_repository.get(db, document_id)

        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )

        is_company_user = current_user.role in (
            UserRole.COMPANY_RECRUITER,
            UserRole.COMPANY_ADMIN,
        )

        if is_company_user:
            # Company users can only download a document if it is a resume
            # attached to an application they have already revealed.
            app_result = await db.execute(
                _select(Application).where(Application.resume_id == document_id)
            )
            application = app_result.scalar_one_or_none()

            if application is not None:
                # There is an application referencing this resume — check reveal status
                reveal_result = await db.execute(
                    _select(RevealedApplication).where(
                        RevealedApplication.application_id == application.id
                    )
                )
                reveal = reveal_result.scalar_one_or_none()

                if reveal is None:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Reveal candidate identity before accessing their resume.",
                    )
            else:
                # Document is not linked to any application — company users
                # cannot download arbitrary candidate documents.
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied. You can only download documents associated with revealed applications."
                )
        else:
            # Job seekers (document owners) — verify ownership
            if document.user_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied. You can only download your own documents."
                )

        # Get file path
        file_path = storage_service.get_document_path(
            document.user_id,
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


# ---------------------------------------------------------------------------
# Pre-signed upload URL endpoints (S3/CDN direct upload flow)
# ---------------------------------------------------------------------------

from pydantic import BaseModel as _BaseModel


class PresignedUploadRequest(_BaseModel):
    document_type: str
    original_filename: str
    content_type: str


class PresignedUploadResponse(_BaseModel):
    upload_url: str
    object_key: str
    expires_in: int
    cdn_url: str


class ConfirmUploadRequest(_BaseModel):
    object_key: str
    document_type: str
    original_filename: str
    file_size: int
    content_type: str
    label: Optional[str] = None
    is_default: bool = False


@router.post("/upload-url", response_model=PresignedUploadResponse)
async def get_presigned_upload_url(
    body: PresignedUploadRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate a pre-signed S3 PUT URL for direct browser-to-storage upload.

    The client should:
    1. Call this endpoint to get a pre-signed URL and an object key.
    2. PUT the file directly to ``upload_url`` with ``Content-Type`` header set.
    3. Call ``POST /documents/confirm-upload`` with the returned ``object_key``
       to record the document in the database.

    Returns 503 if S3 is not configured (local-storage deployments should use
    the standard ``POST /documents`` multipart upload instead).
    """
    from app.core.config import settings as _settings

    if not _settings.use_s3:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Direct upload is only available when S3 object storage is configured. "
                   "Use POST /documents for multipart upload.",
        )

    allowed_types = {"resume", "cover_letter", "portfolio", "certificate", "other"}
    if body.document_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid document_type. Allowed: {', '.join(allowed_types)}",
        )

    import uuid as _uuid
    unique_id = _uuid.uuid4().hex
    # Preserve original extension
    ext = ""
    if "." in body.original_filename:
        ext = "." + body.original_filename.rsplit(".", 1)[1].lower()
    object_key = f"documents/{current_user.id}/{unique_id}{ext}"

    expires_in = 900  # 15 minutes

    upload_url = storage_service.generate_presigned_upload_url(
        object_key=object_key,
        content_type=body.content_type,
        expires_in=expires_in,
    )
    if not upload_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate upload URL. Check S3 configuration.",
        )

    cdn_url = storage_service.get_cdn_url_for_document_key(object_key)

    return PresignedUploadResponse(
        upload_url=upload_url,
        object_key=object_key,
        expires_in=expires_in,
        cdn_url=cdn_url,
    )


@router.post("/confirm-upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def confirm_direct_upload(
    body: ConfirmUploadRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Confirm a completed direct-to-S3 upload and record it in the database.

    Call this after a successful PUT to the pre-signed URL returned by
    ``GET /documents/upload-url``.  The backend verifies the object exists in
    S3, then creates the document database record and enqueues resume parsing
    if applicable.
    """
    from app.core.config import settings as _settings

    if not _settings.use_s3:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Direct upload confirmation is only available when S3 is configured.",
        )

    # Validate document type
    allowed_types = {"resume", "cover_letter", "portfolio", "certificate", "other"}
    if body.document_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid document_type. Allowed: {', '.join(allowed_types)}",
        )

    # Verify the object exists in S3
    if not storage_service.verify_s3_object_exists(body.object_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Object not found in storage. Ensure the file was uploaded to the pre-signed URL before confirming.",
        )

    # Ensure the object key belongs to this user
    expected_prefix = f"documents/{current_user.id}/"
    if not body.object_key.startswith(expected_prefix):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Object key does not belong to the current user.",
        )

    filename = storage_service.extract_filename_from_storage_path(body.object_key)

    try:
        document_data = {
            "user_id": current_user.id,
            "filename": filename,
            "original_name": body.original_filename,
            "file_type": body.content_type,
            "file_size": body.file_size,
            "document_type": body.document_type,
            "is_default": body.is_default,
            "label": body.label,
            "storage_path": body.object_key,
            "extracted_text": None,
            "version": 1,
        }

        document = await document_repository.create(db, document_data)

        if body.is_default:
            await document_repository.set_default_document(
                db, current_user.id, document.id, body.document_type
            )

        await db.commit()
        await db.refresh(document)

        # Enqueue resume parsing if applicable
        if body.document_type == "resume":
            try:
                # Read the file from S3 to extract text
                file_content = await asyncio.to_thread(
                    lambda: __import__("boto3").client(
                        "s3",
                        aws_access_key_id=_settings.s3_access_key_id,
                        aws_secret_access_key=_settings.s3_secret_access_key,
                        region_name=_settings.s3_region,
                        **({"endpoint_url": _settings.s3_endpoint_url} if _settings.s3_endpoint_url else {}),
                    ).get_object(
                        Bucket=_settings.s3_bucket_name,
                        Key=body.object_key,
                    )["Body"].read()
                )
                extracted_text = await asyncio.to_thread(
                    document_parser.extract_text, file_content, body.content_type
                )
                if extracted_text:
                    arq = await get_arq_pool()
                    await arq.enqueue_job(
                        "parse_resume_and_update_profile",
                        str(current_user.id),
                        extracted_text,
                        str(document.id),
                    )
            except Exception as e:
                logger.warning(f"Failed to enqueue resume parsing for confirmed upload {document.id}: {e}")

    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating document record for confirmed upload: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create document record: {str(e)}",
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
        message="Document confirmed and recorded successfully",
    )
