"""
Chat HTTP URL patterns.
Included at /api/v1/chat/ from notification_service/urls.py

WebSocket URLs are in chat/routing.py — loaded by asgi.py.
"""

from django.urls import path
from .views import (
    ConversationListCreateView,
    ConversationDetailView,
    MessageListView,
)

urlpatterns = [
    # List conversations / create new conversation
    path(
        "conversations/",
        ConversationListCreateView.as_view(),
        name="conversation-list-create",
    ),
    # Single conversation detail
    path(
        "conversations/<int:conversation_id>/",
        ConversationDetailView.as_view(),
        name="conversation-detail",
    ),
    # Message history for a conversation
    path(
        "conversations/<int:conversation_id>/messages/",
        MessageListView.as_view(),
        name="conversation-messages",
    ),
]
