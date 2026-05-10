# ─────────────────────────────────────────────────────────────
# ORDER-SERVICE DOCKERFILE
# Base: python:3.10-slim — matches host Python version (3.10.12)
# ─────────────────────────────────────────────────────────────
FROM python:3.10-slim

# ── ENVIRONMENT VARIABLES ─────────────────────────────────────
# PYTHONDONTWRITEBYTECODE: don't create .pyc files in container
# PYTHONUNBUFFERED: print logs immediately, no buffering
#   Without this, logs appear delayed or not at all in Docker
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ── WORKING DIRECTORY ─────────────────────────────────────────
WORKDIR /app

# ── SYSTEM DEPENDENCIES ───────────────────────────────────────
# gcc, libpq-dev: needed to compile psycopg2 if binary fails
# curl: for health checks in Docker Compose
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ── PYTHON DEPENDENCIES ───────────────────────────────────────
# Copy requirements FIRST — Docker caches this layer.
# If requirements.txt doesn't change, pip install is skipped
# on next build even if source code changes.
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── APPLICATION CODE ──────────────────────────────────────────
# Copy code AFTER pip install — layer ordering for cache efficiency
COPY . .

# ── SECURITY: NON-ROOT USER ───────────────────────────────────
# Never run production containers as root.
# Create dedicated user with no home directory, no login shell.
RUN adduser \
    --disabled-password \
    --no-create-home \
    appuser \
    && chown -R appuser:appuser /app

USER appuser

# ── ENTRYPOINT ────────────────────────────────────────────────
# entrypoint.sh handles:
# 1. Wait for database to be ready
# 2. Run migrations
# 3. Start gunicorn
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["sh", "/entrypoint.sh"]

# ── PORT ──────────────────────────────────────────────────────
# Container listens on 8000 internally.
# Host maps 8003 → 8000 in docker-compose.yml
EXPOSE 8000
