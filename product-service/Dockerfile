# ── Base image ────────────────────────────────────────────────────────
# Python 3.10 slim — matches our host Python version
# slim = smaller image, no unnecessary packages
FROM python:3.10-slim

# ── Environment variables ─────────────────────────────────────────────
# Prevents Python from writing .pyc files to disk
ENV PYTHONDONTWRITEBYTECODE=1
# Prevents Python from buffering stdout/stderr
# Ensures logs appear immediately in docker logs
ENV PYTHONUNBUFFERED=1

# ── System dependencies ───────────────────────────────────────────────
# netcat → used in entrypoint.sh to wait for PostgreSQL
# gcc + libpq-dev → needed to compile psycopg2
# We install then clean up apt cache to keep image small
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        netcat-traditional \
        gcc \
        libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ─────────────────────────────────────────────────
WORKDIR /app

# ── Install Python dependencies ───────────────────────────────────────
# Copy requirements first (before copying code)
# Docker caches this layer — if requirements.txt hasn't changed,
# pip install is skipped on rebuild. Faster builds.
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Copy project code ─────────────────────────────────────────────────
COPY . .

# ── Create media directory ────────────────────────────────────────────
RUN mkdir -p /app/media/product_images

# ── Copy and prepare entrypoint ───────────────────────────────────────
RUN chmod +x /app/entrypoint.sh

# ── Expose port ───────────────────────────────────────────────────────
EXPOSE 8000

# ── Entry point ───────────────────────────────────────────────────────
ENTRYPOINT ["/app/entrypoint.sh"]
