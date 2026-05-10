"""
Chat views for notification-service.

Endpoints:
  GET  /api/v1/chat/conversations/        → list my conversations
  POST /api/v1/chat/conversations/        → create or get conversation
  GET  /api/v1/chat/conversations/<id>/   → conversation detail
  GET  /api/v1/chat/conversations/<id>/messages/ → message history

All endpoints require JWT authentication.
Users can only see conversations they participate in.
"""

import logging
import httpx
from django.conf import settings
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import Conversation, ConversationParticipant, Message
from .serializers import (
    ConversationReadSerializer,
    ConversationCreateSerializer,
    MessageSerializer,
)

logger = logging.getLogger(__name__)


def get_user_info_from_auth(user_id: int) -> dict:
    """
    Fetch user details from auth-service.
    Used to get sender_name when creating a message via HTTP (not WebSocket).
    WebSocket consumer fetches this too in its connect() method.

    Returns dict with keys: id, name, email
    Returns empty dict on failure (graceful fallback).
    """
    try:
        response = httpx.get(
            f"{settings.AUTH_SERVICE_URL}/api/v1/users/public/{user_id}/",
            timeout=3.0,
        )
        if response.status_code == 200:
            return response.json()
    except httpx.RequestError as e:
        logger.warning("auth-service unreachable for user_id=%s: %s", user_id, e)
    return {}


class ConversationListCreateView(APIView):
    """
    GET  → list all conversations the current user participates in
    POST → create a new conversation OR return existing one
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        List conversations for current user.
        Filter: only conversations where user_id is a participant.
        """
        # Find all conversation_ids this user participates in
        participant_rows = ConversationParticipant.objects.filter(
            user_id=request.user.id
        ).values_list("conversation_id", flat=True)

        conversations = Conversation.objects.filter(
            id__in=participant_rows
        ).prefetch_related("participants", "messages")
        # prefetch_related: fetches participants and messages in 2 extra queries
        # instead of N queries (one per conversation) — avoids N+1 problem

        serializer = ConversationReadSerializer(
            conversations,
            many=True,
            context={"request": request},  # needed for unread_count per user
        )
        return Response(serializer.data)

    def post(self, request):
        """
        Create or retrieve a conversation between current user and other_user_id.

        Logic:
          1. Validate input (other_user_id required, product_id optional)
          2. Find existing conversation with BOTH users as participants
             for the same product_id (or any conversation if no product)
          3. If found → return it (idempotent — don't create duplicates)
          4. If not found → create new conversation + add both participants
        """
        serializer = ConversationCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        other_user_id = serializer.validated_data["other_user_id"]
        product_id = serializer.validated_data.get("product_id")
        my_id = request.user.id

        # Cannot start a conversation with yourself
        if other_user_id == my_id:
            return Response(
                {"error": "Cannot start a conversation with yourself"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Find existing conversation with BOTH participants
        # Strategy: find conversations where I am a participant,
        # then filter to those where other_user is also a participant
        my_conv_ids = ConversationParticipant.objects.filter(
            user_id=my_id
        ).values_list("conversation_id", flat=True)

        other_conv_ids = ConversationParticipant.objects.filter(
            user_id=other_user_id
        ).values_list("conversation_id", flat=True)

        # Intersection: conversations both users are in
        shared_conv_ids = set(my_conv_ids) & set(other_conv_ids)

        existing = None
        if shared_conv_ids:
            # Find one that matches the product_id
            qs = Conversation.objects.filter(id__in=shared_conv_ids)
            if product_id:
                qs = qs.filter(product_id=product_id)
            existing = qs.first()

        if existing:
            # Return existing conversation — don't create duplicate
            return Response(
                ConversationReadSerializer(existing, context={"request": request}).data,
                status=status.HTTP_200_OK,
            )

        # Create new conversation
        conversation = Conversation.objects.create(product_id=product_id)
        ConversationParticipant.objects.create(
            conversation=conversation, user_id=my_id
        )
        ConversationParticipant.objects.create(
            conversation=conversation, user_id=other_user_id
        )

        return Response(
            ConversationReadSerializer(conversation, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class ConversationDetailView(APIView):
    """
    GET /api/v1/chat/conversations/<id>/
    Returns conversation detail. Only accessible to participants.
    """

    permission_classes = [IsAuthenticated]

    def get_object(self, conversation_id, user_id):
        """Get conversation if user is a participant, else None."""
        try:
            conv = Conversation.objects.prefetch_related(
                "participants", "messages"
            ).get(id=conversation_id)
            if not conv.has_participant(user_id):
                return None
            return conv
        except Conversation.DoesNotExist:
            return None

    def get(self, request, conversation_id):
        conv = self.get_object(conversation_id, request.user.id)
        if not conv:
            return Response(
                {"error": "Conversation not found or access denied"},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = ConversationReadSerializer(conv, context={"request": request})
        return Response(serializer.data)


class MessageListView(APIView):
    """
    GET /api/v1/chat/conversations/<id>/messages/
    Returns paginated message history. Only accessible to participants.
    Marks messages as read when fetched (all messages not sent by current user).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, conversation_id):
        # Verify user is participant
        try:
            conv = Conversation.objects.get(id=conversation_id)
        except Conversation.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        if not conv.has_participant(request.user.id):
            return Response(
                {"error": "Access denied"}, status=status.HTTP_403_FORBIDDEN
            )

        # Mark all unread messages (not sent by this user) as read
        Message.objects.filter(
            conversation=conv,
            read=False,
        ).exclude(sender_id=request.user.id).update(read=True)

        # Return messages (oldest first — chronological order)
        messages = conv.messages.all()
        serializer = MessageSerializer(messages, many=True)
        return Response(serializer.data)
