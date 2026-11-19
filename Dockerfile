# Production Dockerfile for HealthGuard AI FastAPI Backend
# Compatible with Render (Docker), Hugging Face Spaces (Docker SDK), Railway, and Fly.io.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence_transformers \
    EMBEDDING_MODEL=all-MiniLM-L6-v2 \
    EMBEDDING_LOCAL_FILES_ONLY=true \
    PORT=8000

WORKDIR /app

# Minimal OS dependencies for psycopg2, argon2, and health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install lean production dependencies (CPU-only PyTorch)
COPY requirements-prod.txt .
RUN pip install --upgrade pip && pip install -r requirements-prod.txt

# Pre-download all-MiniLM-L6-v2 during image build so it is never downloaded per request
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application code, migrations, experimental ML artifact, and approved clinical reference docs
COPY healthguard ./healthguard
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY models ./models
COPY scripts ./scripts
COPY Document ./Document

# Create default writable directories (override via VECTOR_DB_PATH / UPLOAD_DIR on persistent volume)
RUN mkdir -p /app/data/vector_db /app/storage/medical_reports

EXPOSE 8000

# Run migrations without overwriting existing data, then start Uvicorn on platform PORT
CMD ["sh", "-c", "python -m alembic upgrade head && exec uvicorn healthguard.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
