#!/bin/bash
set -e

echo "Starting job-match backend initialization..."

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Function to handle errors
error_exit() {
    log "ERROR: $1"
    exit 1
}

# Wait for database to be ready
log "Waiting for database to be ready..."
python scripts/wait-for-db.py || error_exit "Database is not available"

# Run database migrations
log "Running database migrations..."
alembic upgrade head || error_exit "Migration failed"

# Verify database setup
log "Verifying database setup..."
python -c "
import asyncio
import asyncpg
import os

async def verify():
    conn = await asyncpg.connect(
        host=os.getenv('POSTGRES_HOST', 'db'),
        port=int(os.getenv('POSTGRES_PORT', '5432')),
        user=os.getenv('POSTGRES_USER', 'jobmatch'),
        password=os.getenv('POSTGRES_PASSWORD', 'jobmatch'),
        database=os.getenv('POSTGRES_DB', 'jobmatch')
    )

    # Check if tables exist
    tables = await conn.fetch(\"\"\"
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_type = 'BASE TABLE'
    \"\"\")

    await conn.close()

    table_names = [row['table_name'] for row in tables]
    print(f'Found tables: {table_names}')

    if not table_names:
        raise Exception('No tables found after migration')

asyncio.run(verify())
" || error_exit "Database verification failed"

log "Database setup completed successfully"

# Pre-warm the embedding model
log "Loading embedding model..."
python -c "
from app.services.embedding_service import embedding_service
import sys

try:
    if embedding_service.is_available:
        print('Embedding model loaded successfully')
    else:
        print('Warning: Embedding model failed to load, will retry on first request')
        sys.exit(0)  # Don't fail startup, model loading is optional
except Exception as e:
    print(f'Warning: Could not pre-warm embedding model: {e}')
    sys.exit(0)  # Don't fail startup
" || log "Embedding model pre-warm skipped (non-critical)"

# Start the FastAPI application
log "Starting FastAPI server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload