# syntax=docker/dockerfile:1.6
FROM python:3.12-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install system dependencies (required for sentence-transformers, ML libraries, and file type detection)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libopenblas-dev \
    curl \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies separately to maximize layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download SpaCy models (trf for production, sm as fallback)
RUN python -m spacy download en_core_web_trf && \
    python -m spacy download es_core_news_lg && \
    python -m spacy download en_core_web_sm && \
    python -m spacy download es_core_news_sm

# Copy application code
COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations
COPY scripts ./scripts

# Create non-root user for security and set up cache directories
RUN useradd -m runner && \
    mkdir -p /home/runner/.cache/huggingface && \
    chown -R runner:runner /app /home/runner/.cache && \
    chmod +x /app/scripts/*.sh /app/scripts/*.py

# Set HuggingFace cache environment variables
ENV HF_HOME=/home/runner/.cache/huggingface
ENV TRANSFORMERS_CACHE=/home/runner/.cache/huggingface
ENV SENTENCE_TRANSFORMERS_HOME=/home/runner/.cache/huggingface

# Switch to runner user
USER runner

# Try to pre-download the embedding model (non-fatal if it fails)
# If this fails, copy the model manually to the hf_cache volume
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" \
    || echo "WARNING: Model download failed. Copy model files manually to hf_cache volume."

# Build ESCO skill index (non-fatal if it fails)
RUN python scripts/build_esco_index.py \
    || echo "WARNING: ESCO index build failed. Skill matching will use fallback."

# Expose port
EXPOSE 8000
ENV API_PORT=8000

# Health check (FastAPI endpoint at /healthz)
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Default command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]