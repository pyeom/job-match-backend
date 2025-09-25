#!/usr/bin/env python3
"""
Wait for database to be ready script.
This script waits for PostgreSQL to be available and the database to be accessible.
"""

import asyncio
import asyncpg
import logging
import os
import sys
import time
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def wait_for_database(
    host: str = "db",
    port: int = 5432,
    user: str = "jobmatch",
    password: str = "jobmatch",
    database: str = "jobmatch",
    max_retries: int = 30,
    retry_interval: float = 2.0
) -> bool:
    """
    Wait for PostgreSQL database to be ready.

    Args:
        host: Database host
        port: Database port
        user: Database user
        password: Database password
        database: Database name
        max_retries: Maximum number of retry attempts
        retry_interval: Time to wait between retries in seconds

    Returns:
        True if database is ready, False if max retries exceeded
    """
    logger.info(f"Waiting for database at {host}:{port} (database: {database})")

    for attempt in range(max_retries):
        try:
            # Try to establish a connection
            conn = await asyncpg.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                timeout=5.0
            )

            # Test the connection with a simple query
            result = await conn.fetchval("SELECT 1")
            await conn.close()

            if result == 1:
                logger.info(f"Database is ready! (attempt {attempt + 1}/{max_retries})")
                return True

        except Exception as e:
            logger.info(f"Attempt {attempt + 1}/{max_retries} failed: {e}")

        if attempt < max_retries - 1:
            logger.info(f"Retrying in {retry_interval} seconds...")
            await asyncio.sleep(retry_interval)

    logger.error(f"Database not ready after {max_retries} attempts")
    return False


async def check_pgvector_extension(
    host: str = "db",
    port: int = 5432,
    user: str = "jobmatch",
    password: str = "jobmatch",
    database: str = "jobmatch"
) -> bool:
    """
    Check if pgvector extension is available.

    Returns:
        True if pgvector extension is available, False otherwise
    """
    try:
        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            timeout=5.0
        )

        # Check if vector extension exists
        result = await conn.fetchval(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
        )
        await conn.close()

        if result == 1:
            logger.info("pgvector extension is available")
            return True
        else:
            logger.warning("pgvector extension not found")
            return False

    except Exception as e:
        logger.error(f"Failed to check pgvector extension: {e}")
        return False


async def main():
    """Main function to wait for database and check extensions."""
    # Get database connection parameters from environment
    host = os.getenv("POSTGRES_HOST", "db")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    user = os.getenv("POSTGRES_USER", "jobmatch")
    password = os.getenv("POSTGRES_PASSWORD", "jobmatch")
    database = os.getenv("POSTGRES_DB", "jobmatch")

    # Wait for database to be ready
    if not await wait_for_database(host, port, user, password, database):
        logger.error("Database is not ready, exiting")
        sys.exit(1)

    # Check pgvector extension
    if not await check_pgvector_extension(host, port, user, password, database):
        logger.warning("pgvector extension not available, but continuing...")

    logger.info("Database setup complete")


if __name__ == "__main__":
    asyncio.run(main())