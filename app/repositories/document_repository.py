"""
Document repository for managing user document CRUD operations.
"""
from typing import Optional, List
from uuid import UUID
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload
import logging

from app.repositories.base import BaseRepository
from app.models.document import Document, DocumentVersion

logger = logging.getLogger(__name__)


class DocumentRepository(BaseRepository[Document]):
    """Repository for document operations with custom queries."""

    def __init__(self):
        super().__init__(Document)

    async def get_by_user(
        self,
        db: AsyncSession,
        user_id: UUID,
        document_type: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[List[Document], int]:
        """
        Get all documents for a specific user with optional filtering.

        Args:
            db: Database session
            user_id: User UUID
            document_type: Optional filter by document type
            skip: Pagination offset
            limit: Maximum results to return

        Returns:
            Tuple of (list of documents, total count)
        """
        try:
            # Build query
            query = select(self.model).where(self.model.user_id == user_id)

            if document_type:
                query = query.where(self.model.document_type == document_type)

            # Add ordering by creation date (newest first)
            query = query.order_by(self.model.created_at.desc())

            # Get total count
            count_query = select(func.count()).select_from(self.model).where(
                self.model.user_id == user_id
            )
            if document_type:
                count_query = count_query.where(self.model.document_type == document_type)

            count_result = await db.execute(count_query)
            total = count_result.scalar_one()

            # Apply pagination
            query = query.offset(skip).limit(limit)

            result = await db.execute(query)
            documents = list(result.scalars().all())

            return documents, total
        except SQLAlchemyError as e:
            logger.error(f"Error fetching documents for user {user_id}: {e}")
            raise

    async def get_default_document(
        self,
        db: AsyncSession,
        user_id: UUID,
        document_type: str
    ) -> Optional[Document]:
        """
        Get the default document of a specific type for a user.

        Args:
            db: Database session
            user_id: User UUID
            document_type: Type of document (resume, cover_letter, etc.)

        Returns:
            Document if found, None otherwise
        """
        try:
            stmt = select(self.model).where(
                and_(
                    self.model.user_id == user_id,
                    self.model.document_type == document_type,
                    self.model.is_default == True
                )
            )
            result = await db.execute(stmt)
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(
                f"Error fetching default {document_type} for user {user_id}: {e}"
            )
            raise

    async def set_default_document(
        self,
        db: AsyncSession,
        user_id: UUID,
        document_id: UUID,
        document_type: str
    ) -> Document:
        """
        Set a document as the default for its type.
        Unsets any other default documents of the same type for the user.

        Args:
            db: Database session
            user_id: User UUID
            document_id: Document UUID to set as default
            document_type: Type of document

        Returns:
            Updated document
        """
        try:
            # First, unset all other default documents of this type for the user
            other_defaults = await db.execute(
                select(self.model).where(
                    and_(
                        self.model.user_id == user_id,
                        self.model.document_type == document_type,
                        self.model.is_default == True,
                        self.model.id != document_id
                    )
                )
            )

            for doc in other_defaults.scalars().all():
                doc.is_default = False

            # Now set the target document as default
            document = await self.get(db, document_id)
            if document:
                document.is_default = True
                await db.flush()
                await db.refresh(document)

            return document
        except SQLAlchemyError as e:
            logger.error(
                f"Error setting default document {document_id} for user {user_id}: {e}"
            )
            await db.rollback()
            raise

    async def get_document_with_versions(
        self,
        db: AsyncSession,
        document_id: UUID
    ) -> Optional[Document]:
        """
        Get a document with all its versions loaded.

        Args:
            db: Database session
            document_id: Document UUID

        Returns:
            Document with versions if found, None otherwise
        """
        try:
            stmt = select(self.model).options(
                selectinload(self.model.versions)
            ).where(self.model.id == document_id)

            result = await db.execute(stmt)
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching document {document_id} with versions: {e}")
            raise

    async def create_version(
        self,
        db: AsyncSession,
        document: Document
    ) -> DocumentVersion:
        """
        Create a version snapshot of a document.

        Args:
            db: Database session
            document: Document to snapshot

        Returns:
            Created DocumentVersion
        """
        try:
            version = DocumentVersion(
                document_id=document.id,
                version_number=document.version,
                filename=document.filename,
                original_name=document.original_name,
                file_type=document.file_type,
                file_size=document.file_size,
                storage_path=document.storage_path,
                extracted_text=document.extracted_text
            )

            db.add(version)
            await db.flush()
            await db.refresh(version)

            return version
        except SQLAlchemyError as e:
            logger.error(f"Error creating version for document {document.id}: {e}")
            await db.rollback()
            raise

    async def get_versions(
        self,
        db: AsyncSession,
        document_id: UUID
    ) -> List[DocumentVersion]:
        """
        Get all versions of a document.

        Args:
            db: Database session
            document_id: Document UUID

        Returns:
            List of document versions, ordered by version number descending
        """
        try:
            stmt = select(DocumentVersion).where(
                DocumentVersion.document_id == document_id
            ).order_by(DocumentVersion.version_number.desc())

            result = await db.execute(stmt)
            return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Error fetching versions for document {document_id}: {e}")
            raise

    async def search_documents(
        self,
        db: AsyncSession,
        user_id: UUID,
        search_query: str,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[List[Document], int]:
        """
        Search documents by label or original filename.

        Args:
            db: Database session
            user_id: User UUID
            search_query: Search string
            skip: Pagination offset
            limit: Maximum results to return

        Returns:
            Tuple of (list of documents, total count)
        """
        try:
            search_pattern = f"%{search_query}%"

            # Build query
            query = select(self.model).where(
                and_(
                    self.model.user_id == user_id,
                    or_(
                        self.model.label.ilike(search_pattern),
                        self.model.original_name.ilike(search_pattern)
                    )
                )
            ).order_by(self.model.created_at.desc())

            # Get total count
            count_query = select(func.count()).select_from(self.model).where(
                and_(
                    self.model.user_id == user_id,
                    or_(
                        self.model.label.ilike(search_pattern),
                        self.model.original_name.ilike(search_pattern)
                    )
                )
            )

            count_result = await db.execute(count_query)
            total = count_result.scalar_one()

            # Apply pagination
            query = query.offset(skip).limit(limit)

            result = await db.execute(query)
            documents = list(result.scalars().all())

            return documents, total
        except SQLAlchemyError as e:
            logger.error(f"Error searching documents for user {user_id}: {e}")
            raise

    async def count_by_type(
        self,
        db: AsyncSession,
        user_id: UUID,
        document_type: str
    ) -> int:
        """
        Count documents of a specific type for a user.

        Args:
            db: Database session
            user_id: User UUID
            document_type: Type of document

        Returns:
            Count of documents
        """
        try:
            stmt = select(func.count()).select_from(self.model).where(
                and_(
                    self.model.user_id == user_id,
                    self.model.document_type == document_type
                )
            )
            result = await db.execute(stmt)
            return result.scalar_one()
        except SQLAlchemyError as e:
            logger.error(
                f"Error counting {document_type} documents for user {user_id}: {e}"
            )
            raise


# Singleton instance
document_repository = DocumentRepository()
