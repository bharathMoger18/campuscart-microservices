"""
WebSocket URL routing for chat.
Loaded by notification_service/asgi.py into the ProtocolTypeRouter.

URL pattern:
  ws://host/ws/chat/<conversation_id>/?token=<jwt>

The <conversation_id> is captured and available in consumer as:
  self.scope["url_route"]["kwargs"]["conversation_id"]
"""

from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(
        r"^ws/chat/(?P<conversation_id>\d+)/$",
        consumers.ChatConsumer.as_asgi(),
    ),
]
