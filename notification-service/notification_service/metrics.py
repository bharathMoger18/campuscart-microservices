from prometheus_client import Counter, Histogram, Gauge

# ═══════════════════════════════════════════════════════════════
# WEBSOCKET CONNECTION METRICS
# ═══════════════════════════════════════════════════════════════

# Current active WebSocket connections — the most important WS metric
# This is a gauge because it goes up (connect) and down (disconnect)
ws_connections_active = Gauge(
    name="notification_ws_connections_active",
    documentation="Current number of active WebSocket connections",
    labelnames=["connection_type"],   # "chat", "notifications"
)
# Alert: if this stays at 0 for > 5 minutes while order-service has traffic,
# students can't receive order updates — critical UX failure

# Total WebSocket connection events
ws_connect_total = Counter(
    name="notification_ws_connect_total",
    documentation="Total WebSocket connections established",
    labelnames=["connection_type"],
)

ws_disconnect_total = Counter(
    name="notification_ws_disconnect_total",
    documentation="Total WebSocket disconnections",
    labelnames=["connection_type", "close_code"],
    # close_code: "1000" (normal), "1001" (going away), "1006" (abnormal)
    # Alert: high rate of 1006 (abnormal close) = connection instability
)

# ═══════════════════════════════════════════════════════════════
# MESSAGE METRICS
# ═══════════════════════════════════════════════════════════════

# Chat messages sent between buyers and sellers
messages_sent_total = Counter(
    name="notification_messages_sent_total",
    documentation="Total chat messages sent via WebSocket",
    labelnames=["message_type"],   # "text", "image", "order_update"
)

# Message delivery latency — how fast do messages arrive?
message_delivery_seconds = Histogram(
    name="notification_message_delivery_seconds",
    documentation="Time from message send to delivery confirmation in seconds",
    labelnames=[],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
    # SLO: p99 message delivery < 1s. Real-time chat should feel instant.
    # p99 > 2s means Redis or network is struggling
)

# Redis channel layer operations
redis_channel_publish_total = Counter(
    name="notification_redis_channel_publish_total",
    documentation="Total messages published to Redis channel layer",
    labelnames=["channel_type", "status"],  # status: "success", "failure"
)

redis_channel_receive_total = Counter(
    name="notification_redis_channel_receive_total",
    documentation="Total messages received from Redis channel layer",
    labelnames=["channel_type"],
)

# ═══════════════════════════════════════════════════════════════
# PUSH NOTIFICATION METRICS (pywebpush)
# ═══════════════════════════════════════════════════════════════

push_notifications_sent_total = Counter(
    name="notification_push_sent_total",
    documentation="Total Web Push notifications sent via pywebpush",
    labelnames=["status"],      # "success", "failure", "expired"
)

push_notification_failures_total = Counter(
    name="notification_push_failures_total",
    documentation="Total failed push notification deliveries",
    labelnames=["error_type"],  # "subscription_expired", "invalid_endpoint", "network_error"
    # expired = student revoked permission or browser deleted subscription
    # Alert: high expired rate means your subscriber base needs re-prompting
)

push_notification_duration_seconds = Histogram(
    name="notification_push_duration_seconds",
    documentation="Duration of pywebpush API calls",
    labelnames=[],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)