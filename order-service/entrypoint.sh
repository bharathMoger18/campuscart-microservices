#!/bin/sh
# ─────────────────────────────────────────────────────────────
# ENTRYPOINT FOR ORDER-SERVICE
# Runs every time the container starts.
# ─────────────────────────────────────────────────────────────

set -e  # Exit immediately if any command fails

echo "🚀 Starting order-service..."

# ── STEP 1: Wait for database ─────────────────────────────────
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
echo "📦 Running migrations..."
python manage.py migrate --noinput
echo "✅ Migrations complete!"

# ── STEP 3: Collect static files ─────────────────────────────
echo "📁 Collecting static files..."
python manage.py collectstatic --noinput
echo "✅ Static files collected!"

# ── STEP 4: PROMETHEUS MULTIPROCESS MODE ─────────────────────
# gunicorn forks 3 worker processes. prometheus_client stores metric values
# in per-worker in-memory counters by default — when Prometheus scrapes
# /metrics it hits one worker and gets only that worker's counts, missing
# the other two. Setting PROMETHEUS_MULTIPROC_DIR switches prometheus_client
# to write metric values to shared files on disk instead. django_prometheus's
# ExportToDjangoView then aggregates ALL worker files when /metrics is scraped.
#
# rm -rf first: on container restart (without a fresh filesystem), stale .db
# files from the previous run's dead workers would still be here. Without
# cleanup, their Counter values persist and inflate every metric permanently.
# Each container start must get a clean directory.
export PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc
rm -rf $PROMETHEUS_MULTIPROC_DIR
mkdir -p $PROMETHEUS_MULTIPROC_DIR

# ── STEP 5: Start gunicorn ────────────────────────────────────
echo "🌐 Starting gunicorn on port 8000..."
exec gunicorn order_service.wsgi:application \
    --workers 3 \
    --bind 0.0.0.0:8000 \
    --access-logfile - \
    --error-logfile - \
    --log-level info