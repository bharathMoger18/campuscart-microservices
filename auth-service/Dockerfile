# ─────────────────────────────────────────
# Stage 1: Builder — install dependencies
# ─────────────────────────────────────────
FROM python:3.10-slim AS builder

WORKDIR /app

# Copy requirements first for Docker layer cache optimization
COPY requirements.txt .

# Install packages to /install — copied to runtime stage later
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ─────────────────────────────────────────
# Stage 2: Runtime — lean production image
# ─────────────────────────────────────────
FROM python:3.10-slim AS runtime

# Python optimizations for containers
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy only compiled packages from builder — no compiler, no pip cache
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Security: create non-root user and group
RUN addgroup --system appgroup && \
    adduser --system --ingroup appgroup appuser

# Give appuser ownership of the app directory
RUN chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Document the port (informational)
EXPOSE 8000

# Docker health check — hits our liveness probe
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/')"

# Start the application
ENTRYPOINT ["sh", "entrypoint.sh"]
