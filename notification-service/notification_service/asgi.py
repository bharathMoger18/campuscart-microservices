"""
ASGI config for notification_service.
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "notification_service.settings")
django.setup()

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from urllib.parse import parse_qs
from django.contrib.auth.models import AnonymousUser

import chat.routing


class TokenAuthMiddleware:
    """
    WebSocket JWT authentication middleware.
    Extracts token from query string, validates it, sets scope["user"].
    Usage: ws://host/ws/chat/5/?token=<jwt>
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            scope["user"] = await self._get_user_from_token(scope)
        await self.app(scope, receive, send)

    async def _get_user_from_token(self, scope):
        from notification_service.authentication import (
            MicroserviceJWTAuthentication,
        )
        try:
            query_string = scope.get("query_string", b"").decode("utf-8")
            params = parse_qs(query_string)
            token_list = params.get("token", [])

            if not token_list:
                return AnonymousUser()

            raw_token = token_list[0]
            auth = MicroserviceJWTAuthentication()
            validated_token = auth.get_validated_token(raw_token)
            return auth.get_user(validated_token)

        except Exception:
            return AnonymousUser()


django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    # Removed AllowedHostsOriginValidator — handled by Nginx in production
    # For development: TokenAuthMiddleware directly
    "websocket": TokenAuthMiddleware(
        URLRouter(
            chat.routing.websocket_urlpatterns
        )
    ),
})
