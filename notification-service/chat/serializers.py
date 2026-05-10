"""
Chat serializers for notification-service.

KEY DIFFERENCES from monolith:
  Monolith used UserSerializer to embed full user objects.
  Microservice stores user_id integers only.

  Message: sender_name is a snapshot stored at creation time.
           No auth-service call needed to display message history.

  Conversation: participant_ids is a list of integers.
                Frontend fetches user profiles if needed.
"""

from rest_framework import serializers
from .models import Conversation, ConversationParticipant, Message


class MessageSerializer(serializers.ModelSerializer):
    """
    Serializes a single chat message for API responses.

    MONOLITH:
      sender = UserSerializer(read_only=True)
      → embedded full user object: {"id": 1, "name": "John", "email": "..."}

    MICROSERVICE:
      sender_id and sender_name are plain fields — no HTTP call needed.
      sender_name was snapshotted at message creation time.
    """

    class Meta:
        model = Message
        fields = [
            "id",
            "conversation",
            "sender_id",
            "sender_name",
            "text",
            "timestamp",
            "read",
        ]
        read_only_fields = ["id", "timestamp", "sender_id", "sender_name", "read"]


class ConversationReadSerializer(serializers.ModelSerializer):
    """
    Read serializer — for GET /api/v1/chat/conversations/ responses.
    Shows participant_ids as a list of integers.
    Shows last_message for preview (like WhatsApp conversation list).
    """

    # SerializerMethodField — computes value by calling get_<field_name>()
    participant_ids = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id",
            "product_id",
            "participant_ids",
            "last_message",
            "unread_count",
            "created_at",
        ]

    def get_participant_ids(self, obj):
        """Return list of user_id integers for all participants."""
        return obj.get_participant_ids()

    def get_last_message(self, obj):
        """Return the most recent message preview for conversation list."""
        last = obj.messages.last()  # ordered by timestamp ascending, so last = newest
        if not last:
            return None
        return {
            "id": last.id,
            "sender_id": last.sender_id,
            "sender_name": last.sender_name,
            "text": last.text[:100],    # truncate for preview
            "timestamp": last.timestamp,
            "read": last.read,
        }

    def get_unread_count(self, obj):
        """
        Count unread messages for the requesting user.
        Unread = read=False AND sender is NOT the requesting user.
        """
        request = self.context.get("request")
        if not request:
            return 0
        user_id = request.user.id
        return obj.messages.filter(read=False).exclude(sender_id=user_id).count()


class ConversationCreateSerializer(serializers.Serializer):
    """
    Write serializer — for POST /api/v1/chat/conversations/ requests.

    MONOLITH:
      other_user was a ForeignKey — Django validated user exists in DB.

    MICROSERVICE:
      other_user_id is just an integer — we trust the client to send
      a valid user_id. In production, we could validate by calling
      auth-service GET /api/v1/users/public/<id>/ here.
      For now: trust the integer.

    product_id is optional — chat may not be about a product.
    """

    other_user_id = serializers.IntegerField(
        help_text="user_id of the other participant to start a conversation with"
    )
    product_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Optional product_id this conversation is about",
    )
