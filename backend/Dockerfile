# syntax=docker/dockerfile:1.7

# ============================================================================
# Base image — Python 3.11 slim variant (~150MB vs ~1GB for full image)
# ============================================================================
FROM python:3.11-slim AS base

# Prevent Python from writing .pyc files and buffering stdout/stderr
# Critical for container logs to appear immediately
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install OS-level dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory — all subsequent commands run here
WORKDIR /app

# ============================================================================
# Dependency installation — copied FIRST for Docker layer caching
# ============================================================================
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install -e ".[dev]"

# ============================================================================
# Application code — copied LAST so code changes don't bust dependency cache
# ============================================================================
COPY ./app ./app
COPY ./alembic ./alembic
COPY ./alembic.ini ./alembic.ini

# Entrypoint runs migrations before starting uvicorn
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ============================================================================
# Runtime configuration
# ============================================================================
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]