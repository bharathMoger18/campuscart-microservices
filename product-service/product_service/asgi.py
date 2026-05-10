"""
ASGI config for product_service.

For future async support (Django Channels, etc.)
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "product_service.settings")

application = get_asgi_application()
