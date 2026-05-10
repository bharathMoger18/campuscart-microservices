"""
Push notification views for notification-service.

Endpoints:
  POST   /api/v1/push/subscribe/               → save push subscription (JWT)
  DELETE /api/v1/push/subscribe/               → remove push subscription (JWT)
  GET    /api/v1/push/public-key/              → VAPID public key (no auth)
  POST   /api/v1/push/notify/                  → send push (JWT, inter-service)
  GET    /api/v1/push/notifications/           → notification inbox (JWT)
  POST   /api/v1/push/notifications/<id>/mark-read/  → mark one read (JWT)
  POST   /api/v1/push/notifications/mark-all-read/   → mark all read (JWT)
"""

import logging
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status

from .models import PushSubscription, PushNotification
from .serializers import PushSubscriptionSerializer, PushNotificationSerializer
from .utils import send_push_to_user_id

logger = logging.getLogger(__name__)


class PushSubscribeView(APIView):
    """
    POST   → save or update a push subscription for the current user
    DELETE → remove a push subscription for the current user

    Both actions use the same endpoint — method determines action.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Save or update a push subscription.

        Expected payload (exactly what browser's PushSubscription.toJSON() returns):
        {
            "endpoint": "https://fcm.googleapis.com/fcm/send/...",
            "keys": {
                "p256dh": "BNcRd...",
                "auth":   "tBHI..."
            }
        }
        """
        endpoint = request.data.get("endpoint")
        keys = request.data.get("keys", {})
        p256dh = keys.get("p256dh")
        auth_key = keys.get("auth")

        if not endpoint or not p256dh or not auth_key:
            return Response(
                {"error": "endpoint, keys.p256dh and keys.auth are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # update_or_create: update if exists (same user + endpoint), create if new
        # This handles re-subscription gracefully — browser may refresh keys
        sub, created = PushSubscription.objects.update_or_create(
            user_id=request.user.id,
            endpoint=endpoint,
            defaults={"p256dh": p256dh, "auth": auth_key},
        )

        action = "created" if created else "updated"
        logger.info("Push subscription %s for user_id=%s", action, request.user.id)

        return Response(
            PushSubscriptionSerializer(sub).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request):
        """Remove a push subscription (user disabled push notifications)."""
        endpoint = request.data.get("endpoint")
        if not endpoint:
            return Response(
                {"error": "endpoint is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        deleted_count, _ = PushSubscription.objects.filter(
            user_id=request.user.id,
            endpoint=endpoint,
        ).delete()

        if deleted_count == 0:
            return Response(
                {"error": "Subscription not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({"detail": "Subscription removed"}, status=status.HTTP_200_OK)


class VAPIDPublicKeyView(APIView):
    """
    GET /api/v1/push/public-key/
    Returns the VAPID public key. No authentication required.

    WHY no auth: The frontend needs this key to call
    PushManager.subscribe({applicationServerKey: publicKey}).
    This happens BEFORE the user logs in (or without logging in).
    The public key is not secret — it's meant to be publicly shared.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"publicKey": settings.VAPID_PUBLIC_KEY})


class SendPushNotifyView(APIView):
    """
    POST /api/v1/push/notify/
    Send a push notification to a user_id.

    This endpoint is called by OTHER SERVICES (order-service, product-service)
    when they need to send a push notification.

    Example call from order-service:
      POST http://notification-service:8000/api/v1/push/notify/
      Authorization: Bearer <jwt>
      {
          "user_id": 5,
          "title": "Order Confirmed",
          "body": "Your order #42 has been confirmed!",
          "url": "/orders/42/",
          "type": "order",
          "data": {"order_id": 42}
      }

    The calling service must send a valid JWT (same SECRET_KEY).
    In production, use a service account token or internal API key instead.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_id = request.data.get("user_id")
        title = request.data.get("title", "CampusCart Notification")
        body = request.data.get("body", "")
        url = request.data.get("url", "/")
        type_ = request.data.get("type", "general")
        data = request.data.get("data", {})

        if not user_id:
            return Response(
                {"error": "user_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return Response(
                {"error": "user_id must be an integer"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sent_count, notification = send_push_to_user_id(
            user_id=user_id,
            title=title,
            body=body,
            url=url,
            type_=type_,
            data=data,
        )

        return Response({
            "detail": f"Push sent to {sent_count} subscription(s)",
            "notification_id": notification.id,
            "delivered": notification.delivered,
        })


class NotificationListView(APIView):
    """
    GET /api/v1/push/notifications/
    Returns the notification inbox for the current user (most recent first).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        notifications = PushNotification.objects.filter(
            user_id=request.user.id
        ).order_by("-created_at")[:50]  # last 50 notifications

        serializer = PushNotificationSerializer(notifications, many=True)
        return Response({
            "count": len(serializer.data),
            "unread_count": PushNotification.objects.filter(
                user_id=request.user.id, read=False
            ).count(),
            "results": serializer.data,
        })


class NotificationMarkReadView(APIView):
    """POST /api/v1/push/notifications/<pk>/mark-read/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            notification = PushNotification.objects.get(
                pk=pk, user_id=request.user.id
            )
        except PushNotification.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        notification.read = True
        notification.save(update_fields=["read"])
        return Response(PushNotificationSerializer(notification).data)


class NotificationMarkAllReadView(APIView):
    """POST /api/v1/push/notifications/mark-all-read/"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        updated = PushNotification.objects.filter(
            user_id=request.user.id,
            read=False,
        ).update(read=True)

        return Response({
            "detail": f"Marked {updated} notifications as read"
        })
