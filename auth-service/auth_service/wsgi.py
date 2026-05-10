"""
WSGI config for auth_service project.

This is the entry point for production servers like gunicorn.
gunicorn auth_service.wsgi:application
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "auth_service.settings")

application = get_wsgi_application()
