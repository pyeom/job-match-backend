"""
File storage service for handling avatar uploads.
Supports local file storage with future S3 compatibility.
"""
from pathlib import Path
from typing import Optional, Tuple
import uuid
import os
import aiofiles
from fastapi import UploadFile
from app.core.config import settings


class StorageService:
    """Service for storing and managing uploaded files."""

    def __init__(self):
        # Base directory for media storage
        self.base_dir = Path("media")
        self.avatars_dir = self.base_dir / "avatars"
        self.documents_dir = self.base_dir / "documents"

        # Create directories if they don't exist
        self.avatars_dir.mkdir(parents=True, exist_ok=True)
        self.documents_dir.mkdir(parents=True, exist_ok=True)

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

    async def save_avatar(
        self,
        user_id: uuid.UUID,
        file_content: bytes,
        size_suffix: str = ""
    ) -> Tuple[str, Path]:
        """
        Save avatar file to disk.

        Args:
            user_id: The user's UUID
            file_content: The file content as bytes
            size_suffix: Optional suffix for different sizes (e.g., 'thumbnail', 'standard')

        Returns:
            Tuple of (public URL, file path)
        """
        user_dir = self._get_user_avatar_dir(user_id)
        filename = self._generate_filename("avatar", size_suffix)
        file_path = user_dir / filename

        # Write file asynchronously
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(file_content)

        # Generate public URL
        public_url = self._generate_public_url(user_id, filename)

        return public_url, file_path

    async def delete_avatar(self, user_id: uuid.UUID, filename: str) -> bool:
        """
        Delete an avatar file.

        Args:
            user_id: The user's UUID
            filename: The filename to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        user_dir = self._get_user_avatar_dir(user_id)
        file_path = user_dir / filename

        try:
            if file_path.exists():
                file_path.unlink()
                return True
        except Exception as e:
            print(f"Error deleting file {file_path}: {e}")
            return False

        return False

    async def delete_user_avatars(self, user_id: uuid.UUID) -> bool:
        """
        Delete all avatars for a user.

        Args:
            user_id: The user's UUID

        Returns:
            True if deleted successfully, False otherwise
        """
        user_dir = self._get_user_avatar_dir(user_id)

        try:
            if user_dir.exists():
                # Delete all files in the user's directory
                for file_path in user_dir.iterdir():
                    if file_path.is_file():
                        file_path.unlink()
                # Remove the directory
                user_dir.rmdir()
                return True
        except Exception as e:
            print(f"Error deleting user avatars for {user_id}: {e}")
            return False

        return False

    def _generate_public_url(self, user_id: uuid.UUID, filename: str) -> str:
        """
        Generate a public URL for accessing the file.

        In production, this would return an S3 URL or CDN URL.
        For local development, returns a path that can be served by FastAPI.
        """
        # For local storage, return a URL path
        return f"/api/v1/media/avatars/{user_id}/{filename}"

    def extract_filename_from_url(self, url: Optional[str]) -> Optional[str]:
        """
        Extract the filename from a public URL.

        Args:
            url: The public URL

        Returns:
            The filename or None if URL is invalid
        """
        if not url:
            return None

        try:
            # Extract filename from URL path
            parts = url.split('/')
            if len(parts) >= 2:
                return parts[-1]  # Get the last part (filename)
        except Exception:
            pass

        return None

    def get_file_path(self, user_id: uuid.UUID, filename: str) -> Path:
        """
        Get the full file path for a given user and filename.

        Args:
            user_id: The user's UUID
            filename: The filename

        Returns:
            The full file path
        """
        user_dir = self._get_user_avatar_dir(user_id)
        return user_dir / filename

    async def cleanup_orphaned_avatars(self) -> int:
        """
        Clean up orphaned avatar files (files without corresponding database records).
        This should be called periodically as a maintenance task.

        Returns:
            Number of orphaned files deleted
        """
        # This is a basic implementation
        # In production, you'd query the database to find orphaned files
        deleted_count = 0

        try:
            for user_dir in self.avatars_dir.iterdir():
                if user_dir.is_dir():
                    # Check if directory is empty
                    if not any(user_dir.iterdir()):
                        user_dir.rmdir()
                        deleted_count += 1
        except Exception as e:
            print(f"Error during cleanup: {e}")

        return deleted_count

    # Document storage methods

    def _get_user_document_dir(self, user_id: uuid.UUID) -> Path:
        """Get or create the document directory for a specific user."""
        user_dir = self.documents_dir / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    def _generate_document_filename(self, original_filename: str) -> str:
        """
        Generate a unique filename for the uploaded document.
        Uses UUID to ensure uniqueness while preserving the original extension.
        """
        unique_id = uuid.uuid4().hex
        # Extract extension from original filename
        extension = ""
        if '.' in original_filename:
            extension = original_filename.rsplit('.', 1)[1].lower()
            extension = f".{extension}"
        return f"{unique_id}{extension}"

    async def save_document(
        self,
        user_id: uuid.UUID,
        file_content: bytes,
        original_filename: str
    ) -> Tuple[str, Path]:
        """
        Save document file to disk.

        Args:
            user_id: The user's UUID
            file_content: The file content as bytes
            original_filename: Original filename to preserve extension

        Returns:
            Tuple of (storage path, full file path)
        """
        user_dir = self._get_user_document_dir(user_id)
        filename = self._generate_document_filename(original_filename)
        file_path = user_dir / filename

        # Write file asynchronously
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(file_content)

        # Generate storage path (relative path for database storage)
        storage_path = f"media/documents/{user_id}/{filename}"

        return storage_path, file_path

    async def delete_document(self, user_id: uuid.UUID, filename: str) -> bool:
        """
        Delete a document file.

        Args:
            user_id: The user's UUID
            filename: The filename to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        user_dir = self._get_user_document_dir(user_id)
        file_path = user_dir / filename

        try:
            if file_path.exists():
                file_path.unlink()
                return True
        except Exception as e:
            print(f"Error deleting file {file_path}: {e}")
            return False

        return False

    async def delete_user_documents(self, user_id: uuid.UUID) -> bool:
        """
        Delete all documents for a user.

        Args:
            user_id: The user's UUID

        Returns:
            True if deleted successfully, False otherwise
        """
        user_dir = self._get_user_document_dir(user_id)

        try:
            if user_dir.exists():
                # Delete all files in the user's directory
                for file_path in user_dir.iterdir():
                    if file_path.is_file():
                        file_path.unlink()
                # Remove the directory
                user_dir.rmdir()
                return True
        except Exception as e:
            print(f"Error deleting user documents for {user_id}: {e}")
            return False

        return False

    def get_document_path(self, user_id: uuid.UUID, filename: str) -> Path:
        """
        Get the full file path for a given user and filename.

        Args:
            user_id: The user's UUID
            filename: The filename

        Returns:
            The full file path
        """
        user_dir = self._get_user_document_dir(user_id)
        return user_dir / filename

    def extract_filename_from_storage_path(self, storage_path: str) -> Optional[str]:
        """
        Extract the filename from a storage path.

        Args:
            storage_path: The storage path (e.g., "media/documents/{user_id}/{filename}")

        Returns:
            The filename or None if path is invalid
        """
        if not storage_path:
            return None

        try:
            # Extract filename from path
            parts = storage_path.split('/')
            if len(parts) >= 3:
                return parts[-1]  # Get the last part (filename)
        except Exception:
            pass

        return None

    async def read_document(self, user_id: uuid.UUID, filename: str) -> Optional[bytes]:
        """
        Read a document file.

        Args:
            user_id: The user's UUID
            filename: The filename

        Returns:
            File content as bytes or None if file doesn't exist
        """
        file_path = self.get_document_path(user_id, filename)

        try:
            if file_path.exists():
                async with aiofiles.open(file_path, 'rb') as f:
                    return await f.read()
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
            return None

        return None

    async def read_file(self, storage_path: str) -> Optional[bytes]:
        """
        Read a file from storage path.

        Args:
            storage_path: The storage path (e.g., "media/documents/{user_id}/{filename}")

        Returns:
            File content as bytes or None if file doesn't exist
        """
        file_path = Path(storage_path)

        try:
            if file_path.exists():
                async with aiofiles.open(file_path, 'rb') as f:
                    return await f.read()
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
            return None

        return None


# Singleton instance
storage_service = StorageService()
