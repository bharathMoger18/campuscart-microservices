"""
WSGI config for notification_service.
Fallback for non-ASGI deployment tools.
Primary server is Daphne (ASGI) — see asgi.py.
"""

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "notification_service.settings")

application = get_wsgi_application()
