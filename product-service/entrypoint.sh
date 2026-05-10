#!/bin/bash

# Exit immediately if any command fails
set -e

echo "🚀 Starting product-service..."

# ── Wait for PostgreSQL to be ready ─────────────────────────────────
echo "⏳ Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT}..."

while ! nc -z ${DB_HOST} ${DB_PORT}; do
    echo "   PostgreSQL not ready yet — retrying in 1 second..."
    sleep 1
done

echo "✅ PostgreSQL is ready!"

# ── Run migrations ───────────────────────────────────────────────────
echo "📦 Running migrations..."
python manage.py migrate --noinput
echo "✅ Migrations complete!"

# ── Collect static files ─────────────────────────────────────────────
echo "📁 Collecting static files..."
python manage.py collectstatic --noinput
echo "✅ Static files collected!"

# ── Start Gunicorn ───────────────────────────────────────────────────
echo "🌐 Starting Gunicorn on port 8000..."
exec gunicorn product_service.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -

