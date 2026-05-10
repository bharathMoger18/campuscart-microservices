#!/bin/sh
# ─────────────────────────────────────────────────────────────
# ENTRYPOINT FOR ORDER-SERVICE
# Runs every time the container starts.
# ─────────────────────────────────────────────────────────────

set -e  # Exit immediately if any command fails

echo "🚀 Starting order-service..."

# ── STEP 1: Wait for database ─────────────────────────────────
# DB_HOST and DB_PORT come from environment variables
# set by docker-compose.yml
# We ping PostgreSQL until it accepts connections.
echo "⏳ Waiting for database at $DB_HOST:$DB_PORT..."

while ! python -c "
import psycopg2, os, sys
try:
    psycopg2.connect(
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
        host=os.environ['DB_HOST'],
        port=os.environ['DB_PORT'],
    )
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; do
    echo "   DB not ready — retrying in 2s..."
    sleep 2
done

echo "✅ Database is ready!"

# ── STEP 2: Run migrations ────────────────────────────────────
# Applies any pending migrations automatically on startup.
# Safe to run multiple times — Django skips already-applied migrations.
echo "📦 Running migrations..."
python manage.py migrate --noinput
echo "✅ Migrations complete!"

# ── STEP 3: Collect static files ─────────────────────────────
echo "📁 Collecting static files..."
python manage.py collectstatic --noinput
echo "✅ Static files collected!"

# ── STEP 4: Start gunicorn ────────────────────────────────────
# gunicorn: production WSGI server (replaces runserver)
# --workers 3: 3 worker processes (handles concurrent requests)
# --bind 0.0.0.0:8000: listen on all interfaces, port 8000
# --access-logfile -: print access logs to stdout (Docker captures them)
# --error-logfile -: print error logs to stdout
echo "🌐 Starting gunicorn on port 8000..."
exec gunicorn order_service.wsgi:application \
    --workers 3 \
    --bind 0.0.0.0:8000 \
    --access-logfile - \
    --error-logfile - \
    --log-level info
