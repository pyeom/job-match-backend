# syntax=docker/dockerfile:1.6
FROM python:3.12-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install system dependencies (required for sentence-transformers and ML libraries)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libopenblas-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies separately to maximize layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations

# Create non-root user for security
RUN useradd -m runner && chown -R runner:runner /app
USER runner

# Expose port
EXPOSE 8000
ENV API_PORT=8000

# Health check (FastAPI endpoint at /healthz)
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Default command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]