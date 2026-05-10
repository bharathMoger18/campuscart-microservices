#!/bin/sh
set -e

echo "=== Notification Service Starting ==="
echo "Waiting for PostgreSQL..."

# Wait for PostgreSQL to be ready
until python -c "
import psycopg2, os, sys
try:
    psycopg2.connect(
        dbname=os.environ.get('DB_NAME', 'notification_db'),
        user=os.environ.get('DB_USER', 'notification_user'),
        password=os.environ.get('DB_PASSWORD', 'notification_pass'),
        host=os.environ.get('DB_HOST', 'db'),
        port=os.environ.get('DB_PORT', '5432'),
    )
    sys.exit(0)
except Exception:
    sys.exit(1)
"; do
    echo "PostgreSQL not ready — waiting..."
    sleep 2
done
echo "PostgreSQL ready!"

echo "Waiting for Redis..."
# Wait for Redis to be ready
until python -c "
import redis, os, sys
try:
    r = redis.from_url(os.environ.get('REDIS_URL', 'redis://redis:6379/0'))
    r.ping()
    sys.exit(0)
except Exception:
    sys.exit(1)
"; do
    echo "Redis not ready — waiting..."
    sleep 2
done
echo "Redis ready!"

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Daphne ASGI server..."
# Daphne handles both HTTP and WebSocket connections
# -b 0.0.0.0 → listen on all interfaces (required for Docker)
# -p 8000    → internal container port
exec daphne -b 0.0.0.0 -p 8000 notification_service.asgi:application
