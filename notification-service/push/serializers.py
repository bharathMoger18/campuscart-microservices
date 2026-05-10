"""
Push notification serializers.
"""

from rest_framework import serializers
from .models import PushSubscription, PushNotification


class PushSubscriptionSerializer(serializers.ModelSerializer):
    """
    Serializes PushSubscription for API responses.
    user_id is read-only — set from JWT token in the view, never from client.
    """

    class Meta:
        model = PushSubscription
        fields = ["id", "user_id", "endpoint", "p256dh", "auth", "created_at"]
        read_only_fields = ["id", "user_id", "created_at"]


class PushNotificationSerializer(serializers.ModelSerializer):
    """
    Serializes PushNotification for the notification inbox.
    All fields are read-only — notifications are created by the server only.
    """

    class Meta:
        model = PushNotification
        fields = [
            "id",
            "user_id",
            "title",
            "body",
            "url",
            "type",
            "data",
            "delivered",
            "read",
            "created_at",
        ]
        read_only_fields = fields
