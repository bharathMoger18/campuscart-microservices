# ── Base image ────────────────────────────────────────────────────────
# Python 3.10 slim — matches our host Python version
# slim = smaller image, no unnecessary packages
# FROM python:3.10-slim  

# ── Environment variables ─────────────────────────────────────────────
# Prevents Python from writing .pyc files to disk
# ENV PYTHONDONTWRITEBYTECODE=1
# Prevents Python from buffering stdout/stderr
# Ensures logs appear immediately in docker logs
# ENV PYTHONUNBUFFERED=1

# ── System dependencies ───────────────────────────────────────────────
# netcat → used in entrypoint.sh to wait for PostgreSQL
# gcc + libpq-dev → needed to compile psycopg2
# We install then clean up apt cache to keep image small
# RUN apt-get update \
# && apt-get install -y --no-install-recommends \
#     netcat-traditional \
#     gcc \
#     libpq-dev \
# && apt-get clean \
# && rm -rf /var/lib/apt/lists/*

# ── Working directory ─────────────────────────────────────────────────
# WORKDIR /app

# ── Install Python dependencies ───────────────────────────────────────
# Copy requirements first (before copying code)
# Docker caches this layer — if requirements.txt hasn't changed,
# pip install is skipped on rebuild. Faster builds.
# COPY requirements.txt .
# RUN pip install --upgrade pip \
#     && pip install --no-cache-dir -r requirements.txt

# ── Copy project code ─────────────────────────────────────────────────
# COPY . .

# ── Create media directory ────────────────────────────────────────────
# RUN mkdir -p /app/media/product_images

# ── Copy and prepare entrypoint ───────────────────────────────────────
# RUN chmod +x /app/entrypoint.sh

# ── Expose port ───────────────────────────────────────────────────────
# EXPOSE 8000

# ── Entry point ───────────────────────────────────────────────────────
# ENTRYPOINT ["/app/entrypoint.sh"]


# ── Stage 1: Builder ──
FROM python:3.10-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime ──
FROM python:3.10-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .
RUN mkdir -p /app/media/product_images
RUN chmod +x /app/entrypoint.sh
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
RUN chown -R appuser:appgroup /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/')"
ENTRYPOINT ["/app/entrypoint.sh"]