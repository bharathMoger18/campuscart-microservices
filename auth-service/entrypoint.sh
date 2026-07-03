#!/bin/sh
# entrypoint.sh — runs on every container start

set -e

echo "Waiting for database..."
sleep 2

echo "Running migrations..."
python manage.py migrate --noinput

# ── PROMETHEUS MULTIPROCESS MODE ──────────────────────────────────────────────
# gunicorn forks 3 worker processes. prometheus_client stores metric values
# in per-worker in-memory counters by default — when Prometheus scrapes
# /-/metrics it hits one worker and gets only that worker's counts, missing
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

echo "Starting gunicorn..."
exec gunicorn auth_service.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -