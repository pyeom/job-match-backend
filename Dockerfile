# syntax=docker/dockerfile:1.6

# ─── Stage 1: Builder ────────────────────────────────────────────────────────
# Installs all Python packages and downloads SpaCy models.
# Build tools (gcc, etc.) stay in this stage and are NOT copied to runtime.
FROM python:3.12-slim AS builder

# Build-time args: override for production to use larger/more accurate models
#   Production: SPACY_MODEL_EN=en_core_web_trf  SPACY_MODEL_ES=es_core_news_lg
#   Default (dev/CI): small models ~50 MB total vs ~800 MB for trf+lg
ARG SPACY_MODEL_EN=en_core_web_sm
ARG SPACY_MODEL_ES=es_core_news_sm

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment — easy to copy between stages
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies.
# torch is installed first from the CPU-only index to avoid pulling in ~2 GB of CUDA libraries.
# The app only performs CPU inference; CUDA is never used at runtime.
COPY requirements.txt .
RUN pip install --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        torch && \
    pip install --no-cache-dir -r requirements.txt

# Download SpaCy models into the venv.
# spacy-transformers (and its torch dependency) is only required when a TRF model is selected.
# For the default sm models, install spacy-transformers conditionally.
RUN if echo "${SPACY_MODEL_EN} ${SPACY_MODEL_ES}" | grep -qE "trf|lg"; then \
        pip install --no-cache-dir spacy-transformers; \
    fi && \
    python -m spacy download ${SPACY_MODEL_EN} && \
    python -m spacy download ${SPACY_MODEL_ES}

# ─── Stage 2: Runtime ────────────────────────────────────────────────────────
# Minimal image: no build tools, no compiler, no git.
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Runtime-only system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopenblas0 \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy application code
COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations
COPY scripts ./scripts

# Create non-root user and set up cache directories
# /app/app/data/esco is created here so the named volume mount works correctly
RUN useradd -m runner && \
    mkdir -p /home/runner/.cache/huggingface /app/app/data/esco && \
    chown -R runner:runner /app /home/runner/.cache && \
    chmod +x /app/scripts/*.sh /app/scripts/*.py

# HuggingFace cache env vars (model files live in a named volume, not baked in)
ENV HF_HOME=/home/runner/.cache/huggingface \
    TRANSFORMERS_CACHE=/home/runner/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/home/runner/.cache/huggingface

USER runner

EXPOSE 8000
ENV API_PORT=8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
