"""
Base repository implementing common CRUD operations using SQLAlchemy 2.0.

This module provides a generic repository pattern that can be extended
by specific model repositories. It handles all basic database operations
with proper async/await patterns and error handling.
"""

from __future__ import annotations
from typing import Generic, TypeVar, Type, Optional
from uuid import UUID
from sqlalchemy import select, func, delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
import logging

logger = logging.getLogger(__name__)

# Generic type variable for the model
T = TypeVar("T")


class BaseRepository(Generic[T]):
    """
    Generic base repository for CRUD operations.

    This class provides standard database operations that can be inherited
    by model-specific repositories. It uses SQLAlchemy 2.0 async patterns
    and proper error handling.

    Type Parameters:
        T: The SQLAlchemy model type this repository manages

    Example:
        class UserRepository(BaseRepository[User]):
            def __init__(self):
                super().__init__(User)
    """

    def __init__(self, model: Type[T]):
        """
        Initialize the repository with a model class.

        Args:
            model: The SQLAlchemy model class to manage
        """
        self.model = model

    async def get(
        self,
        db: AsyncSession,
        id: UUID
    ) -> Optional[T]:
        """
        Retrieve a single record by ID.

        Args:
            db: Active database session
            id: UUID of the record to retrieve

        Returns:
            Model instance if found, None otherwise

        Example:
            user = await repo.get(db, user_id)
            if user:
                print(f"Found: {user.email}")
        """
        try:
            stmt = select(self.model).where(self.model.id == id)
            result = await db.execute(stmt)
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching {self.model.__name__} by id {id}: {e}")
            raise

    async def get_multi(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[list[T], int]:
        """
        Retrieve multiple records with pagination.

        Args:
            db: Active database session
            skip: Number of records to skip (offset)
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of model instances, total count)

        Example:
            items, total = await repo.get_multi(db, skip=20, limit=10)
            print(f"Retrieved {len(items)} of {total} total items")
        """
        try:
            # Query for items with pagination
            stmt = select(self.model).offset(skip).limit(limit)
            result = await db.execute(stmt)
            items = list(result.scalars().all())

            # Query for total count
            count_stmt = select(func.count()).select_from(self.model)
            count_result = await db.execute(count_stmt)
            total = count_result.scalar_one()

            return items, total
        except SQLAlchemyError as e:
            logger.error(f"Error fetching multiple {self.model.__name__}: {e}")
            raise

    async def create(
        self,
        db: AsyncSession,
        obj_in: dict
    ) -> T:
        """
        Create a new record.

        Args:
            db: Active database session
            obj_in: Dictionary of field values for the new record

        Returns:
            Created model instance

        Raises:
            IntegrityError: If constraints are violated (e.g., duplicate unique field)

        Example:
            new_user = await repo.create(db, {"email": "test@example.com", "name": "Test"})
            await db.commit()
        """
        try:
            db_obj = self.model(**obj_in)
            db.add(db_obj)
            await db.flush()
            await db.refresh(db_obj)
            return db_obj
        except IntegrityError as e:
            logger.warning(f"Integrity error creating {self.model.__name__}: {e}")
            await db.rollback()
            raise
        except SQLAlchemyError as e:
            logger.error(f"Error creating {self.model.__name__}: {e}")
            await db.rollback()
            raise

    async def update(
        self,
        db: AsyncSession,
        db_obj: T,
        obj_in: dict
    ) -> T:
        """
        Update an existing record.

        Args:
            db: Active database session
            db_obj: Existing model instance to update
            obj_in: Dictionary of field values to update

        Returns:
            Updated model instance

        Example:
            user.email = "newemail@example.com"
            updated_user = await repo.update(db, user, {"email": "newemail@example.com"})
            await db.commit()
        """
        try:
            # Update only provided fields
            for field, value in obj_in.items():
                if hasattr(db_obj, field):
                    setattr(db_obj, field, value)

            await db.flush()
            await db.refresh(db_obj)
            return db_obj
        except IntegrityError as e:
            logger.warning(f"Integrity error updating {self.model.__name__}: {e}")
            await db.rollback()
            raise
        except SQLAlchemyError as e:
            logger.error(f"Error updating {self.model.__name__}: {e}")
            await db.rollback()
            raise

    async def delete(
        self,
        db: AsyncSession,
        id: UUID
    ) -> bool:
        """
        Delete a record by ID.

        Args:
            db: Active database session
            id: UUID of the record to delete

        Returns:
            True if deleted, False if not found

        Example:
            deleted = await repo.delete(db, user_id)
            if deleted:
                await db.commit()
                print("User deleted")
        """
        try:
            stmt = sql_delete(self.model).where(self.model.id == id)
            result = await db.execute(stmt)
            await db.flush()
            return result.rowcount > 0
        except SQLAlchemyError as e:
            logger.error(f"Error deleting {self.model.__name__} with id {id}: {e}")
            await db.rollback()
            raise

    async def exists(
        self,
        db: AsyncSession,
        id: UUID
    ) -> bool:
        """
        Check if a record exists by ID.

        Args:
            db: Active database session
            id: UUID to check

        Returns:
            True if exists, False otherwise

        Example:
            if await repo.exists(db, user_id):
                print("User exists")
        """
        try:
            stmt = select(func.count()).select_from(self.model).where(self.model.id == id)
            result = await db.execute(stmt)
            count = result.scalar_one()
            return count > 0
        except SQLAlchemyError as e:
            logger.error(f"Error checking existence of {self.model.__name__} with id {id}: {e}")
            raise
