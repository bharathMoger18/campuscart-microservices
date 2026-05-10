"""
Push notification URL patterns.
Included at /api/v1/push/ from notification_service/urls.py
"""

from django.urls import path
from .views import (
    PushSubscribeView,
    VAPIDPublicKeyView,
    SendPushNotifyView,
    NotificationListView,
    NotificationMarkReadView,
    NotificationMarkAllReadView,
)

urlpatterns = [
    # Push subscription management
    path("subscribe/", PushSubscribeView.as_view(), name="push-subscribe"),
    path("public-key/", VAPIDPublicKeyView.as_view(), name="push-public-key"),

    # Inter-service: other services call this to send a push
    path("notify/", SendPushNotifyView.as_view(), name="push-notify"),

    # Notification inbox
    path("notifications/", NotificationListView.as_view(), name="push-notifications"),
    path(
        "notifications/mark-all-read/",
        NotificationMarkAllReadView.as_view(),
        name="push-notifications-mark-all-read",
    ),
    path(
        "notifications/<int:pk>/mark-read/",
        NotificationMarkReadView.as_view(),
        name="push-notification-mark-read",
    ),
]
