"""
File storage service for handling avatar uploads.
Supports local file storage with optional S3/MinIO/R2 compatibility.
When S3 is configured (S3_BUCKET_NAME + S3_ACCESS_KEY_ID + S3_SECRET_ACCESS_KEY),
uploads go to S3 and URLs point to MEDIA_CDN_URL (if set) or S3 directly.
"""
from pathlib import Path
from typing import Optional, Tuple
import uuid
import os
import aiofiles
from fastapi import UploadFile
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


def _get_s3_client():
    """Create and return a boto3 S3 client. Returns None if S3 is not configured."""
    if not settings.use_s3:
        return None
    try:
        import boto3
        kwargs = {
            "aws_access_key_id": settings.s3_access_key_id,
            "aws_secret_access_key": settings.s3_secret_access_key,
            "region_name": settings.s3_region,
        }
        if settings.s3_endpoint_url:
            kwargs["endpoint_url"] = settings.s3_endpoint_url
        return boto3.client("s3", **kwargs)
    except ImportError:
        logger.warning("boto3 not installed — S3 upload unavailable, falling back to local storage")
        return None


class StorageService:
    """Service for storing and managing uploaded files.

    Supports two backends:
    - **Local filesystem** (default): files stored under ``uploads/`` directory.
    - **S3/MinIO/R2** (when S3_BUCKET_NAME, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY
      are set): files stored in the configured bucket. Media URLs point to
      MEDIA_CDN_URL if set, otherwise to the S3 object URL.

    Pre-signed upload URLs for direct browser-to-S3 uploads are available via
    ``generate_presigned_upload_url()`` only when S3 is configured.
    """

    def __init__(self):
        # Base directory for file uploads storage (used only in local mode)
        self.base_dir = Path("uploads")
        self.avatars_dir = self.base_dir / "avatars"
        self.documents_dir = self.base_dir / "documents"

        if not settings.use_s3:
            # Create directories if they don't exist (local mode only)
            self.avatars_dir.mkdir(parents=True, exist_ok=True)
            self.documents_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_user_avatar_dir(self, user_id: uuid.UUID) -> Path:
        """Get or create the avatar directory for a specific user."""
        user_dir = self.avatars_dir / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    def _generate_filename(self, original_filename: str, size_suffix: str = "") -> str:
        """Generate a unique filename for the uploaded file."""
        unique_id = uuid.uuid4().hex
        extension = ".webp"  # All images are converted to WebP
        suffix = f"_{size_suffix}" if size_suffix else ""
        return f"{unique_id}{suffix}{extension}"

    def _generate_public_url(self, user_id: uuid.UUID, filename: str) -> str:
        """Generate a public URL for accessing the file.

        - When MEDIA_CDN_URL is set: returns ``<cdn_url>/avatars/<user_id>/<filename>``
        - Otherwise: returns the API path served by FastAPI.
        """
        if settings.media_cdn_url:
            cdn = settings.media_cdn_url.rstrip("/")
            return f"{cdn}/avatars/{user_id}/{filename}"
        return f"/api/v1/media/avatars/{user_id}/{filename}"

    def _avatar_s3_key(self, user_id: uuid.UUID, filename: str) -> str:
        return f"avatars/{user_id}/{filename}"

    def _document_s3_key(self, user_id: uuid.UUID, filename: str) -> str:
        return f"documents/{user_id}/{filename}"

    # ------------------------------------------------------------------
    # Avatar methods
    # ------------------------------------------------------------------

    async def save_avatar(
        self,
        user_id: uuid.UUID,
        file_content: bytes,
        size_suffix: str = ""
    ) -> Tuple[str, Optional[Path]]:
        """Save avatar file to storage (S3 or local disk).

        Returns:
            Tuple of (public URL, local file path or None when using S3)
        """
        filename = self._generate_filename("avatar", size_suffix)

        if settings.use_s3:
            s3 = _get_s3_client()
            if s3:
                key = self._avatar_s3_key(user_id, filename)
                try:
                    import asyncio
                    await asyncio.to_thread(
                        s3.put_object,
                        Bucket=settings.s3_bucket_name,
                        Key=key,
                        Body=file_content,
                        ContentType="image/webp",
                        CacheControl="public, max-age=86400",
                    )
                    public_url = self._build_cdn_url_for_key(key)
                    return public_url, None
                except Exception as e:
                    logger.error(f"S3 avatar upload failed: {e}. Falling back to local storage.")

        # Local storage fallback
        user_dir = self._get_user_avatar_dir(user_id)
        file_path = user_dir / filename
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(file_content)
        public_url = self._generate_public_url(user_id, filename)
        return public_url, file_path

    async def delete_avatar(self, user_id: uuid.UUID, filename: str) -> bool:
        """Delete an avatar file from storage."""
        if settings.use_s3:
            s3 = _get_s3_client()
            if s3:
                key = self._avatar_s3_key(user_id, filename)
                try:
                    import asyncio
                    await asyncio.to_thread(
                        s3.delete_object,
                        Bucket=settings.s3_bucket_name,
                        Key=key,
                    )
                    return True
                except Exception as e:
                    logger.error(f"S3 avatar delete failed: {e}")
                    return False

        user_dir = self._get_user_avatar_dir(user_id)
        file_path = user_dir / filename
        try:
            if file_path.exists():
                file_path.unlink()
                return True
        except Exception as e:
            logger.error(f"Error deleting file {file_path}: {e}")
        return False

    async def delete_user_avatars(self, user_id: uuid.UUID) -> bool:
        """Delete all avatars for a user."""
        if settings.use_s3:
            s3 = _get_s3_client()
            if s3:
                prefix = f"avatars/{user_id}/"
                try:
                    import asyncio
                    response = await asyncio.to_thread(
                        s3.list_objects_v2,
                        Bucket=settings.s3_bucket_name,
                        Prefix=prefix,
                    )
                    objects = response.get("Contents", [])
                    if objects:
                        await asyncio.to_thread(
                            s3.delete_objects,
                            Bucket=settings.s3_bucket_name,
                            Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
                        )
                    return True
                except Exception as e:
                    logger.error(f"S3 delete_user_avatars failed: {e}")
                    return False

        user_dir = self._get_user_avatar_dir(user_id)
        try:
            if user_dir.exists():
                for file_path in user_dir.iterdir():
                    if file_path.is_file():
                        file_path.unlink()
                user_dir.rmdir()
                return True
        except Exception as e:
            logger.error(f"Error deleting user avatars for {user_id}: {e}")
        return False

    def extract_filename_from_url(self, url: Optional[str]) -> Optional[str]:
        """Extract the filename from a public URL."""
        if not url:
            return None
        try:
            parts = url.split("/")
            if len(parts) >= 2:
                return parts[-1]
        except Exception:
            pass
        return None

    def get_file_path(self, user_id: uuid.UUID, filename: str) -> Path:
        """Get the full local file path for a given user and filename."""
        user_dir = self._get_user_avatar_dir(user_id)
        return user_dir / filename

    async def cleanup_orphaned_avatars(self) -> int:
        """Clean up orphaned empty avatar directories (local storage only)."""
        if settings.use_s3:
            return 0  # S3 has no empty directory concept
        deleted_count = 0
        try:
            for user_dir in self.avatars_dir.iterdir():
                if user_dir.is_dir() and not any(user_dir.iterdir()):
                    user_dir.rmdir()
                    deleted_count += 1
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        return deleted_count

    # ------------------------------------------------------------------
    # Document methods
    # ------------------------------------------------------------------

    def _get_user_document_dir(self, user_id: uuid.UUID) -> Path:
        """Get or create the document directory for a specific user."""
        user_dir = self.documents_dir / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    def _generate_document_filename(self, original_filename: str) -> str:
        """Generate a unique filename for the uploaded document."""
        unique_id = uuid.uuid4().hex
        extension = ""
        if "." in original_filename:
            extension = original_filename.rsplit(".", 1)[1].lower()
            extension = f".{extension}"
        return f"{unique_id}{extension}"

    async def save_document(
        self,
        user_id: uuid.UUID,
        file_content: bytes,
        original_filename: str,
        content_type: str = "application/octet-stream",
    ) -> Tuple[str, Optional[Path]]:
        """Save document file to storage (S3 or local disk).

        Returns:
            Tuple of (storage path / S3 key, local file path or None when using S3)
        """
        filename = self._generate_document_filename(original_filename)

        if settings.use_s3:
            s3 = _get_s3_client()
            if s3:
                key = self._document_s3_key(user_id, filename)
                try:
                    import asyncio
                    await asyncio.to_thread(
                        s3.put_object,
                        Bucket=settings.s3_bucket_name,
                        Key=key,
                        Body=file_content,
                        ContentType=content_type,
                    )
                    return key, None
                except Exception as e:
                    logger.error(f"S3 document upload failed: {e}. Falling back to local storage.")

        # Local storage fallback
        user_dir = self._get_user_document_dir(user_id)
        file_path = user_dir / filename
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(file_content)
        storage_path = f"uploads/documents/{user_id}/{filename}"
        return storage_path, file_path

    async def delete_document(self, user_id: uuid.UUID, filename: str) -> bool:
        """Delete a document file from storage."""
        if settings.use_s3:
            s3 = _get_s3_client()
            if s3:
                key = self._document_s3_key(user_id, filename)
                try:
                    import asyncio
                    await asyncio.to_thread(
                        s3.delete_object,
                        Bucket=settings.s3_bucket_name,
                        Key=key,
                    )
                    return True
                except Exception as e:
                    logger.error(f"S3 document delete failed: {e}")
                    return False

        user_dir = self._get_user_document_dir(user_id)
        file_path = user_dir / filename
        try:
            if file_path.exists():
                file_path.unlink()
                return True
        except Exception as e:
            logger.error(f"Error deleting file {file_path}: {e}")
        return False

    async def delete_user_documents(self, user_id: uuid.UUID) -> bool:
        """Delete all documents for a user."""
        if settings.use_s3:
            s3 = _get_s3_client()
            if s3:
                prefix = f"documents/{user_id}/"
                try:
                    import asyncio
                    response = await asyncio.to_thread(
                        s3.list_objects_v2,
                        Bucket=settings.s3_bucket_name,
                        Prefix=prefix,
                    )
                    objects = response.get("Contents", [])
                    if objects:
                        await asyncio.to_thread(
                            s3.delete_objects,
                            Bucket=settings.s3_bucket_name,
                            Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
                        )
                    return True
                except Exception as e:
                    logger.error(f"S3 delete_user_documents failed: {e}")
                    return False

        user_dir = self._get_user_document_dir(user_id)
        try:
            if user_dir.exists():
                for file_path in user_dir.iterdir():
                    if file_path.is_file():
                        file_path.unlink()
                user_dir.rmdir()
                return True
        except Exception as e:
            logger.error(f"Error deleting user documents for {user_id}: {e}")
        return False

    def get_document_path(self, user_id: uuid.UUID, filename: str) -> Path:
        """Get the full local file path for a given user and document filename."""
        user_dir = self._get_user_document_dir(user_id)
        return user_dir / filename

    def extract_filename_from_storage_path(self, storage_path: str) -> Optional[str]:
        """Extract the filename from a storage path or S3 key."""
        if not storage_path:
            return None
        try:
            parts = storage_path.split("/")
            if len(parts) >= 1:
                return parts[-1]
        except Exception:
            pass
        return None

    async def read_document(self, user_id: uuid.UUID, filename: str) -> Optional[bytes]:
        """Read a document file."""
        if settings.use_s3:
            s3 = _get_s3_client()
            if s3:
                key = self._document_s3_key(user_id, filename)
                try:
                    import asyncio
                    response = await asyncio.to_thread(
                        s3.get_object,
                        Bucket=settings.s3_bucket_name,
                        Key=key,
                    )
                    return response["Body"].read()
                except Exception as e:
                    logger.error(f"S3 read_document failed: {e}")
                    return None

        file_path = self.get_document_path(user_id, filename)
        try:
            if file_path.exists():
                async with aiofiles.open(file_path, "rb") as f:
                    return await f.read()
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
        return None

    async def read_file(self, storage_path: str) -> Optional[bytes]:
        """Read a file from a local storage path."""
        file_path = Path(storage_path)
        try:
            if file_path.exists():
                async with aiofiles.open(file_path, "rb") as f:
                    return await f.read()
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
        return None

    # ------------------------------------------------------------------
    # Pre-signed URL support (S3 only)
    # ------------------------------------------------------------------

    def generate_presigned_upload_url(
        self,
        object_key: str,
        content_type: str,
        expires_in: int = 900,
    ) -> Optional[str]:
        """Generate a pre-signed PUT URL for direct browser-to-S3 upload.

        Returns the URL string, or None if S3 is not configured.

        Args:
            object_key: The S3 object key (path within the bucket).
            content_type: The MIME type the client must declare when uploading.
            expires_in: URL validity in seconds (default 15 minutes).
        """
        if not settings.use_s3:
            return None
        s3 = _get_s3_client()
        if not s3:
            return None
        try:
            url = s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": settings.s3_bucket_name,
                    "Key": object_key,
                    "ContentType": content_type,
                },
                ExpiresIn=expires_in,
                HttpMethod="PUT",
            )
            return url
        except Exception as e:
            logger.error(f"Failed to generate pre-signed URL: {e}")
            return None

    def verify_s3_object_exists(self, object_key: str) -> bool:
        """Check that an object exists in the S3 bucket (used after direct upload confirmation)."""
        if not settings.use_s3:
            return False
        s3 = _get_s3_client()
        if not s3:
            return False
        try:
            s3.head_object(Bucket=settings.s3_bucket_name, Key=object_key)
            return True
        except Exception:
            return False

    def _build_cdn_url_for_key(self, object_key: str) -> str:
        """Build a public URL for an S3 object key.

        Uses MEDIA_CDN_URL when configured, otherwise falls back to the
        S3 endpoint + bucket path.
        """
        if settings.media_cdn_url:
            cdn = settings.media_cdn_url.rstrip("/")
            return f"{cdn}/{object_key}"
        # Fallback: construct S3 URL
        if settings.s3_endpoint_url:
            base = settings.s3_endpoint_url.rstrip("/")
            return f"{base}/{settings.s3_bucket_name}/{object_key}"
        # AWS S3 default URL format
        return f"https://{settings.s3_bucket_name}.s3.{settings.s3_region}.amazonaws.com/{object_key}"

    def get_cdn_url_for_document_key(self, object_key: str) -> str:
        """Return the public CDN/S3 URL for a confirmed direct-upload document."""
        return self._build_cdn_url_for_key(object_key)


# Singleton instance
storage_service = StorageService()
