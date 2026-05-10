"""
Chat models for notification-service.

KEY TRANSFORMATIONS from monolith:
  1. Conversation.product (ForeignKey → Product)
     → product_id (PositiveIntegerField)
     Reason: Product lives in product-service, no shared DB

  2. Conversation.participants (ManyToManyField → User)
     → ConversationParticipant model with user_id (PositiveIntegerField)
     Reason: M2M to User requires users table — we have none.
     Solution: manual join table with plain integer user_id

  3. Message.sender (ForeignKey → User)
     → sender_id (PositiveIntegerField) + sender_name (CharField snapshot)
     Reason: No users table. We snapshot sender_name at creation
     so we don't need to call auth-service for every message read.
"""

from django.db import models
from django.utils import timezone


class Conversation(models.Model):
    """
    A conversation between two or more users, optionally about a product.

    MONOLITH: product = ForeignKey("products.Product", ...)
    MICROSERVICE: product_id = PositiveIntegerField()
    WHY: Product lives in product-service DB. We store only the ID.
         When we need product details, we call product-service HTTP API.
    """

    # ── KEY CHANGE 1 ──────────────────────────────────────────────────────────
    # Monolith: product = ForeignKey("products.Product", null=True, blank=True)
    # Microservice: store product_id as plain integer (nullable — chat may not
    # be about a specific product)
    product_id = models.PositiveIntegerField(null=True, blank=True)
    # ─────────────────────────────────────────────────────────────────────────

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Conversation {self.id} (product_id={self.product_id})"

    def get_participant_ids(self):
        """Return list of user_ids who are in this conversation."""
        return list(
            self.participants.values_list("user_id", flat=True)
        )

    def has_participant(self, user_id: int) -> bool:
        """Check if a user_id is a participant in this conversation."""
        return self.participants.filter(user_id=user_id).exists()


class ConversationParticipant(models.Model):
    """
    Manual join table replacing ManyToManyField(User).

    MONOLITH:
      participants = models.ManyToManyField(settings.AUTH_USER_MODEL, ...)
      Django auto-creates: chat_conversation_participants(conversation_id, user_id)
      BUT: user_id has a FOREIGN KEY constraint to users_user table

    MICROSERVICE:
      We create this table manually with user_id as plain PositiveIntegerField.
      No FK constraint = no users table needed.
      Same logical meaning: one row per (conversation, participant).

    unique_together ensures a user can only be added once per conversation.
    """

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="participants",
    )

    # ── KEY CHANGE 2 ──────────────────────────────────────────────────────────
    # Monolith: user = ForeignKey(settings.AUTH_USER_MODEL, ...)
    # Microservice: store user_id as plain integer
    user_id = models.PositiveIntegerField()
    # ─────────────────────────────────────────────────────────────────────────

    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("conversation", "user_id")  # no duplicate participants

    def __str__(self):
        return f"Participant user_id={self.user_id} in Conversation {self.conversation_id}"


class Message(models.Model):
    """
    A single message in a conversation.

    MONOLITH:
      sender = ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    MICROSERVICE:
      sender_id = PositiveIntegerField()    — store ID only, no FK
      sender_name = CharField()             — SNAPSHOT at send time

    WHY SNAPSHOT sender_name?
      Option A (no snapshot): To display "John: Hello", we call auth-service
        for every message. If conversation has 100 messages = 100 HTTP calls.
        This is called the N+1 problem across services. Terrible for performance.
      Option B (snapshot): Store sender_name when message is created.
        Display uses local data. Zero extra HTTP calls.
        Tradeoff: if user changes their name, old messages show old name.
        For chat history, this is acceptable (like WhatsApp).
    """

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )

    # ── KEY CHANGE 3 ──────────────────────────────────────────────────────────
    # Monolith: sender = ForeignKey(settings.AUTH_USER_MODEL, ...)
    # Microservice: sender_id as integer + sender_name as snapshot
    sender_id = models.PositiveIntegerField()
    sender_name = models.CharField(max_length=255, default="")  # snapshot at send time
    # ─────────────────────────────────────────────────────────────────────────

    text = models.TextField()
    timestamp = models.DateTimeField(default=timezone.now)
    read = models.BooleanField(default=False)

    class Meta:
        ordering = ("timestamp",)  # oldest first — chronological chat order

    def __str__(self):
        return f"Message {self.id} by user_id={self.sender_id} in conv={self.conversation_id}"
