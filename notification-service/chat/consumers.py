"""
WebSocket consumer for real-time chat.

Connection flow:
  1. Client connects: ws://host/ws/chat/5/?token=<jwt>
  2. TokenAuthMiddleware (asgi.py) validates token → scope["user"] = MicroserviceUser
  3. Consumer.connect() verifies user is conversation participant
  4. Consumer joins Redis group "chat_5"
  5. Client sends {"message": "Hello"} → saved to DB + broadcast to group
  6. All connected clients in group receive the message via chat_message()

KEY DIFFERENCES from monolith:
  - No User DB lookup (using MicroserviceUser from scope)
  - sender_name fetched from auth-service ONCE at connect, cached on self
  - Push notifications call push.utils with user_id integers (no User objects)

METRICS NOTE (added 2026-06-30): connection_type is hardcoded to "chat"
throughout this file. metrics.py documents "notifications" as a second
possible value, but asgi.py only ever routes chat.routing — there is no
second consumer in this codebase, so "notifications" is currently unused/
reserved for a future non-chat WS consumer, not something this file can
produce.
"""

import json
import logging
import time
import httpx
from urllib.parse import parse_qs

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from .models import Conversation, Message

from notification_service.metrics import (
    ws_connections_active,
    ws_connect_total,
    ws_disconnect_total,
    messages_sent_total,
    message_delivery_seconds,
    redis_channel_publish_total,
    redis_channel_receive_total,
)

logger = logging.getLogger(__name__)


async def fetch_user_name(user_id: int) -> str:
    """
    Fetch user's display name from auth-service.
    Called ONCE at WebSocket connect time — result cached on consumer.
    Uses httpx.AsyncClient because we're in async context.
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"{settings.AUTH_SERVICE_URL}/api/v1/users/public/{user_id}/"
            )
            if response.status_code == 200:
                data = response.json()
                # auth-service returns {id, name, email}
                return data.get("name") or data.get("email") or f"User {user_id}"
    except httpx.RequestError as e:
        logger.warning("Could not fetch user name for user_id=%s: %s", user_id, e)
    return f"User {user_id}"  # fallback if auth-service unreachable


class ChatConsumer(AsyncJsonWebsocketConsumer):
    """
    Async WebSocket consumer for chat conversations.
    One instance per connected WebSocket client.
    """

    # ─────────────────────────────────────────────────────────────────────────
    # LIFECYCLE METHODS
    # ─────────────────────────────────────────────────────────────────────────

    async def connect(self):
        """
        Called when WebSocket client connects.
        Validates auth, checks participation, joins Redis group.
        """
        # Tracks whether THIS consumer instance actually completed accept().
        # Used in disconnect() below so we never decrement
        # ws_connections_active / count a disconnect for a connection that
        # was rejected during connect() and never counted as connected in
        # the first place (Channels does not call disconnect() for
        # connections that were closed inside connect() before accept(),
        # but this flag is cheap insurance against double-counting if that
        # behavior ever changes across Channels versions).
        self._ws_connected = False

        # Get user from scope — set by TokenAuthMiddleware in asgi.py
        user = self.scope.get("user")

        # Reject anonymous users (invalid/expired/missing token)
        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            logger.warning("WebSocket rejected: unauthenticated connection attempt")
            await self.close(code=4001)  # 4001 = custom code for auth failure
            return

        self.user_id = user.id  # integer, guaranteed by MicroserviceUser.__init__

        # Get conversation_id from URL: ws/chat/<conversation_id>/
        self.conversation_id = self.scope["url_route"]["kwargs"]["conversation_id"]
        self.room_group_name = f"chat_{self.conversation_id}"

        # Verify user is a participant in this conversation
        is_participant = await self._is_participant()
        if not is_participant:
            logger.warning(
                "WebSocket rejected: user_id=%s not in conversation %s",
                self.user_id, self.conversation_id
            )
            await self.close(code=4003)  # 4003 = custom code for forbidden
            return

        # Fetch sender name ONCE — cache on self for all messages this session
        # This avoids calling auth-service for every message sent
        self.sender_name = await fetch_user_name(self.user_id)

        # Join Redis channel group — all consumers in this group share messages
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,  # unique name for THIS consumer instance
        )

        # Accept the WebSocket connection
        await self.accept()

        # Connection is now genuinely live — only past this point do we
        # count it. Rejected attempts above (4001/4003) never reach here,
        # consistent with ws_connections_active's purpose: "current number
        # of active WebSocket connections."
        ws_connections_active.labels(connection_type="chat").inc()
        ws_connect_total.labels(connection_type="chat").inc()
        self._ws_connected = True

        # Notify client they connected successfully
        await self.send_json({
            "type": "connection_established",
            "message": f"Connected to conversation {self.conversation_id}",
            "user_id": self.user_id,
        })

        logger.info(
            "WebSocket connected: user_id=%s conversation=%s",
            self.user_id, self.conversation_id
        )

    async def disconnect(self, code):
        """Called when WebSocket client disconnects."""
        # Leave the Redis group — stop receiving messages for this conversation
        if hasattr(self, "room_group_name"):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name,
            )

        # Only decrement/count if this instance actually completed connect()
        # — see _ws_connected comment above.
        if getattr(self, "_ws_connected", False):
            ws_connections_active.labels(connection_type="chat").dec()
            close_code_label = str(code) if code is not None else "unknown"
            ws_disconnect_total.labels(
                connection_type="chat", close_code=close_code_label
            ).inc()

        logger.info(
            "WebSocket disconnected: user_id=%s conversation=%s code=%s",
            getattr(self, "user_id", "?"), self.conversation_id, code
        )

    # ─────────────────────────────────────────────────────────────────────────
    # RECEIVE FROM CLIENT
    # ─────────────────────────────────────────────────────────────────────────

    async def receive_json(self, content, **kwargs):
        """
        Called when client sends a message over WebSocket.

        Expected formats:
          {"message": "Hello there!"}
          {"type": "read_receipt", "message_id": 42}
        """
        msg_type = content.get("type", "chat_message")

        if "message" in content:
            await self._handle_new_message(content["message"])
        elif msg_type == "read_receipt":
            await self._handle_read_receipt(content.get("message_id"))
        else:
            logger.debug("Unknown message type from user_id=%s: %s", self.user_id, content)

    # ─────────────────────────────────────────────────────────────────────────
    # MESSAGE HANDLING
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_new_message(self, text: str):
        """
        Save message to DB, broadcast to Redis group, trigger push notifications.

        message_delivery_seconds timing (added 2026-06-30): starts here,
        stops right after the group_send() broadcast below completes.
        Deliberately does NOT include _send_push_notifications — that makes
        blocking pywebpush HTTP calls per offline recipient, and folding
        that into "message delivery" would make slow push delivery look
        like a Redis/network problem, which is what this histogram's SLO
        comment in metrics.py is actually meant to catch. This is
        server-side processing + Redis publish latency, an approximation
        of true end-to-end delivery (no client-side delivery-confirmation
        handshake exists in this protocol today).
        """
        if not text or not text.strip():
            return

        delivery_start = time.monotonic()

        # Save to database (sync DB operation wrapped in async)
        msg = await self._save_message(text.strip())

        # messages_sent_total: only "text" is possible — Message has no
        # type field, so this is the only label value this counter will
        # ever record. ("image" would need a model + consumer change;
        # "order_update" is architecturally a different event entirely —
        # see file-level docstring.)
        messages_sent_total.labels(message_type="text").inc()

        # Build payload for broadcasting
        payload = {
            "type": "chat_message",  # matches event handler method name
            "id": msg.id,
            "conversation_id": int(self.conversation_id),
            "sender_id": self.user_id,
            "sender_name": self.sender_name,
            "text": msg.text,
            "timestamp": msg.timestamp.isoformat(),
            "read": False,
        }

        # Broadcast to ALL clients in this conversation group (via Redis)
        # This reaches users connected to OTHER Daphne workers too
        #
        # Wrapped in try/except (new 2026-06-30): previously an unreachable
        # Redis channel layer would raise here uncaught, propagating out of
        # receive_json entirely. The message is already saved to the DB at
        # this point, so a publish failure shouldn't be fatal — the
        # recipient will still see it on next load/reconnect. We log +
        # record the failure instead of crashing the consumer.
        try:
            await self.channel_layer.group_send(
                self.room_group_name,
                payload,
            )
            redis_channel_publish_total.labels(
                channel_type="chat", status="success"
            ).inc()
        except Exception as e:
            redis_channel_publish_total.labels(
                channel_type="chat", status="failure"
            ).inc()
            logger.warning(
                "Redis publish failed for conversation=%s: %s",
                self.conversation_id, e
            )

        message_delivery_seconds.observe(time.monotonic() - delivery_start)

        # Send push notifications to offline participants
        # (participants who are not currently connected via WebSocket)
        await self._send_push_notifications(payload)

    async def _handle_read_receipt(self, message_id: int):
        """Mark a message as read and broadcast receipt to the group."""
        if not message_id:
            return

        msg = await self._get_message(message_id)
        if not msg:
            return

        # Don't mark your own messages as read
        if msg.sender_id == self.user_id:
            return

        await self._mark_as_read(msg)

        # Broadcast read receipt so sender sees "read" indicator.
        # Same try/except pattern as _handle_new_message above — the read
        # state is already saved to DB, so a publish failure here just
        # means the sender's "read" indicator updates late, not never.
        try:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat_read_receipt",
                    "message_id": message_id,
                    "reader_id": self.user_id,
                    "reader_name": self.sender_name,
                },
            )
            redis_channel_publish_total.labels(
                channel_type="chat", status="success"
            ).inc()
        except Exception as e:
            redis_channel_publish_total.labels(
                channel_type="chat", status="failure"
            ).inc()
            logger.warning(
                "Redis publish failed (read receipt) for conversation=%s: %s",
                self.conversation_id, e
            )

    # ─────────────────────────────────────────────────────────────────────────
    # EVENT HANDLERS (receive from Redis group, send to WebSocket)
    # ─────────────────────────────────────────────────────────────────────────

    async def chat_message(self, event):
        """
        Receives a chat.message event from the Redis channel group.
        Forwards it to THIS client's WebSocket connection.

        NOTE: Method name uses underscore (chat_message) but Django Channels
        maps it from dot-notation type "chat.message" by replacing . with _.
        Here we use "chat_message" as both type and method name.

        redis_channel_receive_total increments here regardless of whether
        send_json below succeeds — reaching this handler at all means Redis
        successfully delivered the event to this consumer instance, which
        is what "received from the channel layer" means. Whether it then
        reaches the actual browser is a separate WS-level concern this
        counter isn't tracking.
        """
        redis_channel_receive_total.labels(channel_type="chat").inc()
        await self.send_json(event)

    async def chat_read_receipt(self, event):
        """Receives read receipt from Redis group, forwards to client."""
        redis_channel_receive_total.labels(channel_type="chat").inc()
        await self.send_json(event)

    # ─────────────────────────────────────────────────────────────────────────
    # DATABASE HELPERS (sync operations wrapped for async context)
    # ─────────────────────────────────────────────────────────────────────────

    @database_sync_to_async
    def _is_participant(self):
        """Check if user_id is in this conversation. Runs in thread pool."""
        try:
            conv = Conversation.objects.get(id=self.conversation_id)
            return conv.has_participant(self.user_id)
        except Conversation.DoesNotExist:
            return False

    @database_sync_to_async
    def _save_message(self, text: str):
        """Save message to database. Returns Message instance."""
        conversation = Conversation.objects.get(id=self.conversation_id)
        return Message.objects.create(
            conversation=conversation,
            sender_id=self.user_id,
            sender_name=self.sender_name,  # snapshot from connect time
            text=text,
        )

    @database_sync_to_async
    def _get_message(self, message_id: int):
        """Fetch a message by ID within this conversation."""
        return Message.objects.filter(
            id=message_id,
            conversation_id=self.conversation_id,
        ).first()

    @database_sync_to_async
    def _mark_as_read(self, msg):
        """Mark message as read in database."""
        msg.read = True
        msg.save(update_fields=["read"])

    # ─────────────────────────────────────────────────────────────────────────
    # PUSH NOTIFICATION HELPER
    # ─────────────────────────────────────────────────────────────────────────

    @database_sync_to_async
    def _send_push_notifications(self, payload: dict):
        """
        Send push notifications to participants who are not connected via WebSocket.
        Called after saving and broadcasting a new message.

        Note: We send push to ALL participants (including potentially connected ones).
        Push notification services (browsers) are smart enough to suppress
        notifications if the app is in focus.

        All push_* metrics are recorded inside push/utils.py itself (closer
        to the actual pywebpush calls), not here.
        """
        try:
            from push.utils import send_push_to_user_id
            from .models import ConversationParticipant

            # Get all participant user_ids except the sender
            participants = ConversationParticipant.objects.filter(
                conversation_id=self.conversation_id,
            ).exclude(user_id=self.user_id).values_list("user_id", flat=True)

            for recipient_user_id in participants:
                send_push_to_user_id(
                    user_id=recipient_user_id,
                    title=f"New message from {self.sender_name}",
                    body=payload["text"][:120],
                    url=f"/chat/{self.conversation_id}/",
                    type_="chat_message",
                    data={
                        "conversation_id": int(self.conversation_id),
                        "sender_id": self.user_id,
                    },
                )
        except Exception as e:
            # Push notification failure should NEVER crash the WebSocket
            logger.warning("Push notification failed: %s", e)