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

# Build ESCO skill index (only if not already cached in the volume)
ESCO_INDEX="app/data/esco/skills_index.pkl"
if [ ! -f "$ESCO_INDEX" ]; then
    log "Building ESCO skill index (first run or cache cleared)..."
    python scripts/build_esco_index.py || log "WARNING: ESCO index build failed. Skill matching will use fallback."
else
    log "ESCO skill index already cached, skipping build"
fi

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

# Production safety check: abort if source code is bind-mounted in production.
# docker-compose.yml mounts .:/app, so docker-compose.yml will be present at
# /app/docker-compose.yml when the dev volume is active.  In production we use
# docker-compose.prod.yml which does NOT mount the source tree.
if [ "$APP_ENV" = "production" ] && [ -f "/.dockerenv" ]; then
    if [ -f "/app/docker-compose.yml" ]; then
        error_exit "Source code bind-mount detected in production mode (docker-compose.yml found at /app). Use docker-compose.prod.yml, which uses a versioned image without source bind mounts."
    fi
fi

# Start the FastAPI application
log "Starting FastAPI server..."
if [ "$APP_ENV" = "production" ]; then
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
else
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
fi