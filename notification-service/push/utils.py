"""
Push notification utilities for notification-service.

KEY DIFFERENCE from monolith:
  Monolith: send_push_to_user(user_obj, ...)  ← takes Django User object
  Microservice: send_push_to_user_id(user_id, ...)  ← takes integer user_id

WHY: No User model in this service. We query PushSubscription by user_id directly.

SEND FLOW:
  1. Query PushSubscription.objects.filter(user_id=user_id)
  2. For each subscription → call webpush() with pywebpush
  3. On 410 Gone → delete invalid subscription (cleanup)
  4. Log result in PushNotification model
  5. Return (sent_count, notification_log)
"""

import json
import logging
from django.conf import settings
from pywebpush import webpush, WebPushException

from .models import PushSubscription, PushNotification

logger = logging.getLogger(__name__)


def _send_single_push(subscription: PushSubscription, payload: dict) -> bool:
    """
    Send a Web Push to a single subscription.

    Returns True if sent successfully, False if subscription is invalid/expired.
    Raises WebPushException for unexpected errors.

    The VAPID flow:
      1. Encrypt payload with browser's p256dh public key
      2. Sign request with our VAPID_PRIVATE_KEY
      3. POST to subscription.endpoint (browser vendor's push server)
      4. Browser vendor delivers to user's browser asynchronously
    """
    try:
        webpush(
            subscription_info=subscription.as_subscription_info(),
            data=json.dumps(payload),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_EMAIL},
            timeout=10,
        )
        return True

    except WebPushException as exc:
        # HTTP 410 Gone = subscription expired or user revoked permission
        # Must delete it — keeping dead subscriptions wastes resources
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None) if response else None

        if status_code == 410:
            logger.info(
                "Subscription expired (410), deleting: user_id=%s endpoint=%s",
                subscription.user_id,
                subscription.endpoint[:60],
            )
            try:
                subscription.delete()
            except Exception:
                logger.exception("Failed to delete expired subscription")
            return False

        # Other errors (500, network issues) — log but don't delete subscription
        logger.warning(
            "WebPush failed for user_id=%s: %s (status=%s)",
            subscription.user_id,
            repr(exc),
            status_code,
        )
        return False


def send_push_to_user_id(
    user_id: int,
    title: str,
    body: str,
    url: str = "/",
    type_: str = "general",
    data: dict = None,
) -> tuple:
    """
    Send a Web Push notification to ALL devices of a user.

    KEY DIFFERENCE from monolith's send_push_to_user(user, ...):
      Monolith took a User ORM object and called user.push_subscriptions.all()
      We take user_id integer and query PushSubscription directly.

    Args:
        user_id: integer user ID (from JWT token or other service call)
        title:   notification title shown in browser
        body:    notification body text
        url:     URL to open when notification is clicked
        type_:   notification type (from NOTIF_TYPES choices)
        data:    extra JSON payload for frontend (e.g. order_id, conversation_id)

    Returns:
        (sent_count, PushNotification) tuple
        sent_count: number of subscriptions that accepted the push
    """
    # Build the payload the browser's service worker will receive
    payload = {
        "title": title,
        "body": body,
        "url": url,
        "type": type_,
        "icon": "/static/icon.png",  # default icon
    }
    if data:
        payload["data"] = data

    # Find all subscriptions for this user (could be multiple devices)
    subscriptions = PushSubscription.objects.filter(user_id=user_id)

    if not subscriptions.exists():
        # No subscriptions — log as undelivered, return
        notification = PushNotification.objects.create(
            user_id=user_id,
            title=title,
            body=body,
            url=url,
            type=type_,
            data=data or {},
            delivered=False,
        )
        logger.debug("No push subscriptions for user_id=%s", user_id)
        return 0, notification

    # Send to each subscription (each device)
    sent_count = 0
    for sub in subscriptions:
        success = _send_single_push(sub, payload)
        if success:
            sent_count += 1

    # Log notification result
    notification = PushNotification.objects.create(
        user_id=user_id,
        title=title,
        body=body,
        url=url,
        type=type_,
        data=data or {},
        delivered=(sent_count > 0),  # True if at least one device received it
    )

    logger.info(
        "Push sent to user_id=%s: %d/%d subscriptions delivered",
        user_id,
        sent_count,
        subscriptions.count(),
    )
    return sent_count, notification


def notify_chat_message(conversation_id: int, sender_id: int, sender_name: str, text: str, recipient_ids: list):
    """
    Send push notifications to all chat participants except the sender.
    Called from chat/consumers.py after a new message is saved.

    Args:
        conversation_id: ID of the conversation
        sender_id:       user_id of the message sender (excluded from recipients)
        sender_name:     display name of sender (from snapshot)
        text:            message text (truncated for notification)
        recipient_ids:   list of user_ids to notify
    """
    for user_id in recipient_ids:
        if user_id == sender_id:
            continue  # don't notify the sender about their own message
        send_push_to_user_id(
            user_id=user_id,
            title=f"💬 {sender_name}",
            body=text[:120],  # truncate long messages
            url=f"/chat/{conversation_id}/",
            type_="chat_message",
            data={
                "conversation_id": conversation_id,
                "sender_id": sender_id,
            },
        )


def notify_order_update(user_id: int, order_id: int, status: str, message: str = ""):
    """
    Send push notification for order status changes.
    Called by order-service via POST /api/v1/push/notify/ endpoint.
    """
    status_emojis = {
        "CONFIRMED": "✅",
        "SHIPPED": "🚚",
        "DELIVERED": "📦",
        "CANCELLED": "❌",
        "REFUNDED": "💰",
    }
    emoji = status_emojis.get(status, "🔔")

    send_push_to_user_id(
        user_id=user_id,
        title=f"{emoji} Order #{order_id} {status.title()}",
        body=message or f"Your order status has been updated to {status}.",
        url=f"/orders/{order_id}/",
        type_="order",
        data={"order_id": order_id, "status": status},
    )
