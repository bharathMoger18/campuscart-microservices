from prometheus_client import Counter, Histogram, Gauge

# ═══════════════════════════════════════════════════════════════
# ORDER METRICS
# ═══════════════════════════════════════════════════════════════

# Total orders created and successfully persisted to the DB
# This is the MOST IMPORTANT business metric in CampusCart
# Alert when this drops to 0 during business hours (placement season)
orders_created_total = Counter(
    name="order_orders_created_total",
    documentation="Total orders successfully created and persisted to database",
    labelnames=["status"],      # "confirmed", "pending_payment"
)

# Order status transitions — track the full lifecycle
orders_status_transitions_total = Counter(
    name="order_status_transitions_total",
    documentation="Total order status change events",
    labelnames=["from_status", "to_status"],
    # from: "pending" → to: "confirmed", "cancelled", "refunded"
    # Alert: high rate of pending→cancelled may indicate payment issues
)

# Refund requests — revenue protection metric
refund_requests_total = Counter(
    name="order_refund_requests_total",
    documentation="Total refund requests submitted",
    labelnames=["reason", "status"],
    # reason: "item_not_received", "wrong_item", "changed_mind"
    # status: "approved", "rejected", "pending"
)

# ═══════════════════════════════════════════════════════════════
# CART METRICS
# ═══════════════════════════════════════════════════════════════

# Items added to cart — leading indicator of purchase intent
cart_items_added_total = Counter(
    name="order_cart_items_added_total",
    documentation="Total items added to shopping carts",
    labelnames=[],              # no labels — simple count is sufficient
)

# Cart abandonments — items added but never ordered
# Alert when abandonment rate > 70% for 30 min (checkout UX issue)
cart_abandonments_total = Counter(
    name="order_cart_abandonments_total",
    documentation="Total cart sessions that had items but no order was created",
    labelnames=[],
)

# Active carts right now — current purchase intent gauge
# Increase when item added, decrease when order created or cart cleared
active_carts_gauge = Gauge(
    name="order_active_carts_current",
    documentation="Current number of active shopping carts with items",
)

# ═══════════════════════════════════════════════════════════════
# PAYMENT METRICS (Stripe)
# ═══════════════════════════════════════════════════════════════

# Every payment attempt — success and failure
payment_attempts_total = Counter(
    name="order_payment_attempts_total",
    documentation="Total Stripe payment attempts",
    labelnames=["status"],      # "success", "failure", "pending"
)

# Payment failures by Stripe error code — tells you WHY payments fail
payment_failures_total = Counter(
    name="order_payment_failures_total",
    documentation="Total failed Stripe payment attempts by error code",
    labelnames=["error_code", "decline_code"],
    # error_code: "card_declined", "insufficient_funds", "expired_card"
    # decline_code: "generic_decline", "insufficient_funds", "lost_card"
    # Alert: if card_declined rate > 5/min, notify on-call immediately
)

# Stripe webhook events received
stripe_webhook_events_total = Counter(
    name="order_stripe_webhook_events_total",
    documentation="Total Stripe webhook events received and processed",
    labelnames=["event_type", "status"],
    # event_type: "payment_intent.succeeded", "payment_intent.failed"
    # status: "processed", "ignored", "error"
)

# Stripe API call duration — external dependency latency
stripe_api_duration_seconds = Histogram(
    name="order_stripe_api_duration_seconds",
    documentation="Duration of Stripe API calls in seconds",
    labelnames=["operation"],   # "create_payment_intent", "confirm_payment", "create_refund"
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0],
    # Stripe SLA is typically < 2s. Alert when p99 > 3s
)

# End-to-end checkout duration (add to cart → payment confirmed)
checkout_total_duration_seconds = Histogram(
    name="order_checkout_total_duration_seconds",
    documentation="End-to-end checkout completion time in seconds",
    labelnames=[],
    buckets=[0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 30.0],
    # SLO: p99 checkout < 10s. Alert when p99 > 5s.
)