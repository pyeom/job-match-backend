"""
Document validation and processing service.
Handles document validation, MIME type checking, file size limits, and basic security checks.
"""
import io
from typing import Optional, Tuple
from fastapi import UploadFile, HTTPException, status
import magic
import clamd
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class DocumentService:
    """Service for validating and processing uploaded documents."""

    # Allowed MIME types for documents
    ALLOWED_MIME_TYPES = {
        "application/pdf",
        "application/msword",  # .doc
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    }

    # File extensions mapping
    ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}

    # MIME type to extension mapping
    MIME_TO_EXTENSION = {
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    }

    # Size constraints
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB in bytes

    async def validate_document(self, file: UploadFile) -> Tuple[str, str]:
        """
        Validate uploaded document file.

        Args:
            file: The uploaded file

        Returns:
            Tuple of (detected MIME type, file extension)

        Raises:
            HTTPException: If validation fails
        """
        # Check if file was provided
        if not file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No file provided"
            )

        # Check filename
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filename is required"
            )

        # Check file extension
        extension = self._get_file_extension(file.filename)
        if extension not in self.ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file extension. Allowed: {', '.join(self.ALLOWED_EXTENSIONS)}"
            )

        # Read file content to check size and MIME type
        content = await file.read()

        # Check file size
        if len(content) > self.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File too large. Maximum size: {self.MAX_FILE_SIZE / (1024 * 1024)}MB"
            )

        # Check if file is empty
        if len(content) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File is empty"
            )

        # Detect actual MIME type using python-magic
        try:
            mime_type = self._detect_mime_type(content)
        except Exception as e:
            logger.warning(f"Failed to detect MIME type: {e}")
            # Fallback to content_type from upload
            mime_type = file.content_type

        # Validate MIME type
        if mime_type not in self.ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file type: {mime_type}. Allowed types: PDF, DOC, DOCX"
            )

        # Verify MIME type matches extension
        expected_mime = self._mime_from_extension(extension)
        if expected_mime and mime_type != expected_mime:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File content does not match extension {extension}"
            )

        # Perform basic security checks
        self._security_check(content, mime_type)

        # Scan for viruses using ClamAV
        await self._scan_for_viruses(content)

        # Seek back to beginning for later processing
        await file.seek(0)

        return mime_type, extension

    def _get_file_extension(self, filename: str) -> str:
        """
        Extract file extension from filename.

        Args:
            filename: Original filename

        Returns:
            Lowercase file extension including the dot (e.g., '.pdf')
        """
        if '.' not in filename:
            return ''
        return '.' + filename.rsplit('.', 1)[1].lower()

    def _mime_from_extension(self, extension: str) -> Optional[str]:
        """
        Get expected MIME type from file extension.

        Args:
            extension: File extension (e.g., '.pdf')

        Returns:
            Expected MIME type or None
        """
        for mime, ext in self.MIME_TO_EXTENSION.items():
            if ext == extension:
                return mime
        return None

    def _detect_mime_type(self, content: bytes) -> str:
        """
        Detect MIME type from file content using python-magic.

        Args:
            content: File content bytes

        Returns:
            Detected MIME type
        """
        try:
            # Try using python-magic
            mime = magic.Magic(mime=True)
            detected_type = mime.from_buffer(content)
            return detected_type
        except Exception as e:
            logger.error(f"Error detecting MIME type with python-magic: {e}")
            # Fallback detection based on file signatures
            return self._detect_mime_fallback(content)

    def _detect_mime_fallback(self, content: bytes) -> str:
        """
        Fallback MIME type detection based on file signatures.

        Args:
            content: File content bytes

        Returns:
            Detected MIME type
        """
        # Check for common file signatures
        if content.startswith(b'%PDF'):
            return "application/pdf"
        elif content.startswith(b'PK\x03\x04'):
            # Could be DOCX (ZIP-based format)
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif content.startswith(b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1'):
            # DOC file (OLE2 format)
            return "application/msword"
        else:
            return "application/octet-stream"

    def _security_check(self, content: bytes, mime_type: str) -> None:
        """
        Perform basic security checks on file content.

        Args:
            content: File content bytes
            mime_type: Detected MIME type

        Raises:
            HTTPException: If security check fails
        """
        # Basic security checks
        # 1. Check for suspicious file signatures
        suspicious_signatures = [
            b'\x4D\x5A',  # MZ header (executable)
            b'\x7F\x45\x4C\x46',  # ELF header (Linux executable)
        ]

        for signature in suspicious_signatures:
            if content.startswith(signature):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Suspicious file content detected. File rejected for security reasons."
                )

        # 2. For PDFs, block JavaScript content
        if mime_type == "application/pdf":
            if b'/JavaScript' in content or b'/JS ' in content:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Document contains JavaScript and was rejected for security reasons."
                )

    async def _scan_for_viruses(self, content: bytes) -> None:
        """
        Scan file content for viruses using ClamAV daemon.

        Args:
            content: File content bytes

        Raises:
            HTTPException 400: If a virus or threat is detected.
            HTTPException 503: If ClamAV is unreachable in production (fail-closed).
        """
        try:
            cd = clamd.ClamdNetworkSocket(host="clamav", port=3310, timeout=30)
            result = cd.instream(io.BytesIO(content))
            scan_status, threat = result.get("stream", ("OK", ""))
            if scan_status == "FOUND":
                logger.warning("Virus detected in upload: %s", threat)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Virus detected in uploaded file: {threat}"
                )
        except clamd.ConnectionError:
            if settings.app_env == "production":
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Virus scanning service unavailable; upload rejected."
                )
            logger.warning("ClamAV unavailable, skipping virus scan (non-production mode)")

    def validate_file_size(self, content_length: Optional[int]) -> None:
        """
        Validate file size from Content-Length header.

        Args:
            content_length: Content-Length value from request header

        Raises:
            HTTPException: If file is too large
        """
        if content_length and content_length > self.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File too large. Maximum size: {self.MAX_FILE_SIZE / (1024 * 1024)}MB"
            )


# Singleton instance
document_service = DocumentService()
