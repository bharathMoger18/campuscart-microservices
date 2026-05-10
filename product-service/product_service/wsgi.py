"""
WSGI config for product_service.

Gunicorn uses this file as the entry point.
Command: gunicorn product_service.wsgi:application
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "product_service.settings")

application = get_wsgi_application()
