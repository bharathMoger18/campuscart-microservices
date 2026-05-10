"""
Push notification models for notification-service.

KEY TRANSFORMATIONS from monolith:
  PushSubscription.user (ForeignKey → User) → user_id (PositiveIntegerField)
  PushNotification.user (ForeignKey → User) → user_id (PositiveIntegerField)

  WHY: No users table in this service.
       user_id is all we need to:
         - find subscriptions for a user
         - log notifications per user
         - query unread notification count
"""

from django.db import models


class PushSubscription(models.Model):
    """
    Stores a browser's Web Push subscription for a user.

    When a user enables push notifications in their browser, the browser
    returns a subscription object with 3 key fields:
      - endpoint: the push service URL (browser vendor's server)
      - p256dh:   encryption key (browser's public key)
      - auth:     authentication secret

    We store these so we can push to the user later even when they're offline.
    One user can have multiple subscriptions (phone + laptop + tablet).

    MONOLITH: user = ForeignKey(settings.AUTH_USER_MODEL, on_delete=CASCADE)
    MICROSERVICE: user_id = PositiveIntegerField()
    """

    # ── KEY CHANGE ────────────────────────────────────────────────────────────
    # Monolith: user = ForeignKey(settings.AUTH_USER_MODEL, on_delete=CASCADE)
    # Microservice: plain integer — no FK constraint to users table
    user_id = models.PositiveIntegerField()
    # ─────────────────────────────────────────────────────────────────────────

    endpoint = models.TextField()                    # browser push service URL
    p256dh = models.CharField(max_length=255)        # browser encryption public key
    auth = models.CharField(max_length=255)          # authentication secret
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # A user can have multiple subscriptions (devices)
        # but each endpoint is unique per user
        unique_together = ("user_id", "endpoint")

    def __str__(self):
        return f"PushSubscription(user_id={self.user_id}, endpoint={self.endpoint[:50]})"

    def as_subscription_info(self) -> dict:
        """
        Returns the dict format pywebpush expects.
        Keeps push sending code clean — no repeated dict construction.
        """
        return {
            "endpoint": self.endpoint,
            "keys": {
                "p256dh": self.p256dh,
                "auth": self.auth,
            },
        }


class PushNotification(models.Model):
    """
    Log of every push notification attempt.
    One record per notification (not per subscription).
    Used for: notification inbox, unread count, analytics.

    MONOLITH: user = ForeignKey(settings.AUTH_USER_MODEL, on_delete=CASCADE)
    MICROSERVICE: user_id = PositiveIntegerField()
    """

    NOTIF_TYPES = [
        ("general", "General"),
        ("chat_message", "Chat Message"),
        ("chat_read", "Chat Read Receipt"),
        ("wishlist_like", "Wishlist Like"),
        ("order", "Order Update"),
        ("product_new", "New Product"),
        ("refund_request", "Refund Request"),
        ("refund_update", "Refund Update"),
    ]

    # ── KEY CHANGE ────────────────────────────────────────────────────────────
    user_id = models.PositiveIntegerField()
    # ─────────────────────────────────────────────────────────────────────────

    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=512, default="/")
    type = models.CharField(max_length=50, choices=NOTIF_TYPES, default="general")
    data = models.JSONField(blank=True, null=True)   # extra payload for frontend
    delivered = models.BooleanField(default=False)   # True if at least one sub accepted
    read = models.BooleanField(default=False)        # True if user opened notification
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]   # newest first in notification inbox

    def __str__(self):
        return f"PushNotification(user_id={self.user_id}, title={self.title[:30]})"
