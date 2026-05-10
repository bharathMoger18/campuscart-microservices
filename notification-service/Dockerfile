# ── Base image ────────────────────────────────────────────────────────────────
# Python 3.10-slim — matches host Python version, minimal size
FROM python:3.10-slim

# ── Environment variables ─────────────────────────────────────────────────────
# PYTHONDONTWRITEBYTECODE: don't write .pyc files (not needed in containers)
# PYTHONUNBUFFERED: print logs immediately (no buffering in Docker)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR /app

# ── System dependencies ───────────────────────────────────────────────────────
# libpq-dev: PostgreSQL client library (needed by psycopg2)
# gcc: C compiler (needed to build some Python packages)
# We clean apt cache after to keep image small
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ───────────────────────────────────────────────────────
# Copy requirements FIRST (before source code).
# Docker caches layers. If requirements.txt hasn't changed,
# this entire layer is reused — no reinstalling packages on every build.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Application source ────────────────────────────────────────────────────────
# Copy source code AFTER installing dependencies.
# Code changes frequently; dependencies change rarely.
# This order maximises Docker layer cache hits.
COPY . .

# ── Entrypoint permissions ────────────────────────────────────────────────────
RUN chmod +x entrypoint.sh

# ── Port ──────────────────────────────────────────────────────────────────────
# Daphne listens on 8000 inside the container.
# Docker Compose maps host:8004 → container:8000
EXPOSE 8000

# ── Start command ─────────────────────────────────────────────────────────────
# entrypoint.sh: waits for PostgreSQL + Redis → migrates → starts daphne
CMD ["sh", "entrypoint.sh"]
