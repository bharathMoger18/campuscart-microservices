import logging
import sys
import time
import stripe
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from orders.models import Order, Payment, OrderStatusHistory
from django.utils import timezone

from orders.metrics import (
    payment_attempts_total,
    payment_failures_total,
    stripe_webhook_events_total,
    stripe_api_duration_seconds,
    orders_status_transitions_total,
    checkout_total_duration_seconds,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Configure Stripe with secret key from settings
# settings.STRIPE_SECRET_KEY comes from .env file
# ─────────────────────────────────────────────────────────────
stripe.api_key = settings.STRIPE_SECRET_KEY

# NOTE on metrics.py operations NOT wired here:
# stripe_api_duration_seconds documents three operation labels —
# "create_payment_intent", "confirm_payment", "create_refund". Only
# create_payment_intent (and create_checkout_session, added below) map
# to a real stripe.* call in this file.
#   - "confirm_payment" would time a server-side stripe.PaymentIntent.confirm()
#     call. This service confirms client-side via Stripe.js, then learns the
#     outcome via webhook — there's no server-side confirm() to time.
#   - "create_refund" would time a real stripe.Refund.create() call.
#     orders/views.py's refund_decision only flips the local Payment row's
#     status — it never calls Stripe. Observing a duration for a call that
#     never happens would just be fake data.
# Wire these once the corresponding Stripe calls actually exist.

# ─────────────────────────────────────────────────────────────
# WEBHOOK IDEMPOTENCY
# ─────────────────────────────────────────────────────────────
# Stripe's delivery guarantee is "at least once" — the SAME event can
# legitimately arrive twice even without a retry being triggered by an
# error on our end. Without this guard, a redelivered payment_failed
# event would double-count payment_attempts_total and
# payment_failures_total for one real-world failure.
#
# We key on event["id"], not on order.payment_status, because two
# DIFFERENT failures on the same order (card declined, buyer retries
# with another card, that one declines too) are both real events that
# should both count — collapsing dedup onto order state would wrongly
# suppress the second one.
#
# TTL is set generously long enough to outlast Stripe's webhook
# redelivery window, which can span a few days for persistent failures.
STRIPE_EVENT_DEDUP_TTL_SECONDS = 60 * 60 * 24 * 3  # 3 days


def _is_duplicate_event(event_id: str) -> bool:
    """
    Returns True if this Stripe event ID has already been processed.

    cache.add() is atomic — it only sets the key if it doesn't already
    exist, returning False in that case. So this also works correctly
    if two redeliveries of the same event arrive nearly simultaneously.

    CAVEAT: Django's default cache backend (LocMemCache) is per-process.
    If this service ever runs with multiple worker processes, dedup
    only holds within a single worker — a redelivery routed to a
    different worker wouldn't be caught. Switching CACHES to a
    Redis-backed backend in settings fixes this with no code changes
    needed here.
    """
    claimed = cache.add(
        f"stripe_webhook_event:{event_id}",
        True,
        STRIPE_EVENT_DEDUP_TTL_SECONDS,
    )
    return not claimed


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_payment_intent(request):
    """
    POST /api/v1/payments/create-intent/
    Create a Stripe PaymentIntent for an order.
    Requires JWT authentication.

    WHY PaymentIntent instead of Checkout Session (monolith used sessions)?
    - PaymentIntent: payment happens ON your page (embedded Stripe.js)
    - Checkout Session: user is REDIRECTED to stripe.com (hosted page)
    PaymentIntent gives better UX — no page redirects.
    Frontend uses the returned client_secret with Stripe.js to show
    the payment form directly on the checkout page.

    Request body:
        {"order_id": 42}

    Response:
        {
            "client_secret": "pi_xxx_secret_xxx",
            "payment_intent_id": "pi_xxx",
            "amount": 50000,        ← in cents
            "currency": "usd"
        }

    Flow:
    1. Validate order exists and belongs to requesting buyer
    2. Create Stripe PaymentIntent with order amount
    3. Store PaymentIntent ID on the Order
    4. Return client_secret to frontend
    5. Frontend uses client_secret with Stripe.js to collect payment
    6. Stripe calls /webhooks/stripe/ when payment completes
    """

    order_id = request.data.get("order_id")

    # ── VALIDATION ────────────────────────────────────────────
    if not order_id:
        return Response(
            {"error": "order_id is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ── FETCH ORDER ───────────────────────────────────────────
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        return Response(
            {"error": "Order not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    # ── SECURITY: Only buyer can create payment intent ────────
    if order.buyer_id != request.user.id:
        return Response(
            {"error": "You can only pay for your own orders"},
            status=status.HTTP_403_FORBIDDEN,
        )

    # ── BUSINESS RULE: Only PENDING orders can be paid ────────
    if order.status != Order.STATUS_PENDING:
        return Response(
            {"error": f"Order is {order.status}. Only PENDING orders can be paid."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ── BUSINESS RULE: Don't create duplicate intents ─────────
    if order.stripe_payment_intent:
        return Response(
            {
                "message": "PaymentIntent already exists for this order",
                "payment_intent_id": order.stripe_payment_intent,
            },
            status=status.HTTP_200_OK,
        )

    # ── CREATE STRIPE PAYMENT INTENT ──────────────────────────
    try:
        amount_in_cents = int(order.total_price * 100)

        # Time only the Stripe round-trip, not the surrounding DB writes —
        # keeps stripe_api_duration_seconds isolated to Stripe's own
        # latency rather than blended with our own save() calls.
        _start = time.monotonic()
        intent = stripe.PaymentIntent.create(
            amount=amount_in_cents,
            currency="usd",
            # metadata ties the Stripe payment to our order
            # webhook handler reads order_id from here
            metadata={
                "order_id": str(order.id),
                "buyer_id": str(order.buyer_id),
                "seller_id": str(order.seller_id),
            },
            # optional: description for Stripe dashboard
            description=f"CampusCart Order #{order.id}",
        )
        stripe_api_duration_seconds.labels(operation="create_payment_intent").observe(
            time.monotonic() - _start
        )

        # ── STORE INTENT ID ON ORDER ──────────────────────────
        order.stripe_payment_intent = intent.id
        order.save(update_fields=["stripe_payment_intent", "updated_at"])

        # Also update the Payment record
        payment, _ = Payment.objects.get_or_create(
            order=order,
            defaults={"method": "CARD", "amount": order.total_price},
        )
        payment.stripe_payment_intent_id = intent.id
        payment.save(update_fields=["stripe_payment_intent_id"])

        # The intent exists and is now waiting on the buyer to enter card
        # details client-side — a payment "in flight". The eventual
        # success/failure outcome is recorded later in the webhook
        # handlers below, once Stripe tells us what actually happened.
        payment_attempts_total.labels(status="pending").inc()

        logger.info(
            f"PaymentIntent created: order={order.id}, "
            f"intent={intent.id}, amount={amount_in_cents} cents"
        )

        return Response({
            "client_secret": intent.client_secret,
            "payment_intent_id": intent.id,
            "amount": amount_in_cents,
            "currency": "usd",
            "order_id": order.id,
        })

    except stripe.error.StripeError as e:
        # Still record latency for the failed call — useful for spotting
        # Stripe-side slowness/timeouts even on errors. Deliberately NOT
        # touching payment_attempts_total here: this is a failure to even
        # create the intent (bad amount, API outage, key issue), not a
        # declined card. Counting it there would pollute
        # payment_failures_total's "why do cards get declined" signal
        # with unrelated integration failures.
        stripe_api_duration_seconds.labels(operation="create_payment_intent").observe(
            time.monotonic() - _start
        )
        logger.error(f"Stripe error creating intent for order {order_id}: {e}")
        return Response(
            {"error": f"Stripe error: {str(e)}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )


@csrf_exempt
@require_http_methods(["POST"])
def stripe_webhook(request):
    """
    POST /webhooks/stripe/
    Handle Stripe webhook events.

    WHY @csrf_exempt:
    Stripe's servers cannot send CSRF tokens — they don't
    have our session cookies. Without @csrf_exempt, Django
    would reject every webhook with 403 Forbidden.
    We compensate with Stripe signature verification — which
    is STRONGER than CSRF protection.

    WHY NO JWT auth:
    This endpoint is called by Stripe's servers, not by users.
    Stripe authenticates using HMAC signature, not JWT.

    SIGNATURE VERIFICATION:
    Stripe signs every webhook payload with STRIPE_WEBHOOK_SECRET.
    We verify this signature using stripe.Webhook.construct_event().
    If signature is invalid → reject immediately.
    This prevents anyone from sending fake webhook events.

    IDEMPOTENCY:
    Stripe may send the same event twice (network retries). We check
    event["id"] against a short-lived cache BEFORE routing to a
    handler — see _is_duplicate_event() above. This protects both
    handlers below from double-processing the same delivery.

    Events handled:
    - payment_intent.succeeded  → mark order CONFIRMED, payment SUCCESS
    - payment_intent.payment_failed → mark payment FAILED
    """

    # ── READ RAW PAYLOAD ──────────────────────────────────────
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

    if not sig_header:
        logger.warning("Webhook received without Stripe signature header")
        return JsonResponse({"error": "Missing signature"}, status=400)

    # ── VERIFY STRIPE SIGNATURE ───────────────────────────────
    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            settings.STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        # Invalid JSON payload — event_type is unknowable since the
        # payload never parsed. "invalid" is a fixed sentinel label
        # (same trick as categorize_refund_reason's "other") so malformed
        # requests collapse into one bounded series instead of exploding
        # cardinality.
        logger.error("Webhook: invalid JSON payload")
        stripe_webhook_events_total.labels(event_type="invalid", status="error").inc()
        return JsonResponse({"error": "Invalid payload"}, status=400)
    except stripe.error.SignatureVerificationError:
        # Signature mismatch — could be wrong secret, tampered payload,
        # or replay attack. Worth alerting on a spike of these.
        logger.error("Webhook: signature verification failed")
        stripe_webhook_events_total.labels(event_type="invalid", status="error").inc()
        return JsonResponse({"error": "Invalid signature"}, status=400)

    event_type = event["type"]
    event_id = event.get("id")

    # ── DEDUP CHECK ────────────────────────────────────────────
    # Must happen AFTER signature verification (don't waste cache slots
    # on unverified payloads) and BEFORE routing to a handler.
    if event_id and _is_duplicate_event(event_id):
        logger.info(f"Webhook: duplicate event {event_id} ({event_type}), skipping")
        # Reusing "ignored" rather than inventing a new status value —
        # metrics.py documents only "processed"/"ignored"/"error" for this
        # label, and a duplicate is, functionally, an event we don't act on.
        stripe_webhook_events_total.labels(event_type=event_type, status="ignored").inc()
        return JsonResponse({"status": "duplicate, skipped"})

    # ── ROUTE TO EVENT HANDLER ────────────────────────────────
    logger.info(f"Stripe webhook received: {event_type}")

    if event_type == "payment_intent.succeeded":
        _handle_payment_succeeded(event["data"]["object"])
        stripe_webhook_events_total.labels(event_type=event_type, status="processed").inc()
    elif event_type == "payment_intent.payment_failed":
        _handle_payment_failed(event["data"]["object"])
        stripe_webhook_events_total.labels(event_type=event_type, status="processed").inc()
    else:
        # Unknown event type — log and acknowledge.
        # IMPORTANT: always return 200 for unknown events.
        logger.info(f"Unhandled webhook event type: {event_type}")
        stripe_webhook_events_total.labels(event_type=event_type, status="ignored").inc()

    # ── ALWAYS RETURN 200 TO STRIPE ───────────────────────────
    return JsonResponse({"status": "received"})


def _handle_payment_succeeded(payment_intent: dict):
    """
    Handle payment_intent.succeeded event.

    Updates:
    - Order.payment_status → SUCCESS
    - Order.status → CONFIRMED (via state machine)
    - Payment.status → SUCCESS
    - Creates OrderStatusHistory entry

    IDEMPOTENCY:
    The event-ID-based dedup check in stripe_webhook() is now the
    primary guard against double-processing. This payment_status check
    is kept as a secondary safety net — e.g. covers the (unlikely) case
    of two genuinely different Stripe events both confirming the same
    intent, or manual reprocessing during debugging.
    """
    intent_id = payment_intent.get("id")
    metadata = payment_intent.get("metadata", {})
    order_id = metadata.get("order_id")

    if not order_id:
        logger.error(f"payment_intent.succeeded: no order_id in metadata. intent={intent_id}")
        return

    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        logger.error(f"payment_intent.succeeded: order {order_id} not found")
        return

    # ── SECONDARY IDEMPOTENCY CHECK ───────────────────────────
    if order.payment_status == Order.PAYMENT_SUCCESS:
        logger.info(f"payment_intent.succeeded: order {order_id} already processed")
        return

    # Update payment status
    order.payment_status = Order.PAYMENT_SUCCESS
    order.save(update_fields=["payment_status", "updated_at"])

    # Update Payment record
    Payment.objects.filter(order=order).update(
        status=Order.PAYMENT_SUCCESS,
        stripe_payment_intent_id=intent_id,
    )

    # This webhook firing is the real Stripe-confirmed outcome of the
    # attempt opened as "pending" back in create_payment_intent — the
    # card was genuinely charged, so this is real success data.
    payment_attempts_total.labels(status="success").inc()

    # Transition order status via state machine
    previous_status = order.status
    try:
        order.set_status(
            Order.STATUS_CONFIRMED,
            actor_id=None,          # Stripe triggered this, not a user
            note=f"Payment confirmed via Stripe. Intent: {intent_id}",
        )
        orders_status_transitions_total.labels(
            from_status=previous_status, to_status=Order.STATUS_CONFIRMED
        ).inc()
        # Same order-creation → payment-confirmation approximation used in
        # orders/views.py's simulate_payment (Order has no field tracking
        # when the item was first added to cart). Deliberately inside this
        # try block, not the except — so a stray ValueError on a genuinely
        # different second event doesn't suppress this observation.
        checkout_total_duration_seconds.observe(
            (timezone.now() - order.created_at).total_seconds()
        )
    except ValueError as e:
        # Might already be CONFIRMED from a previous event
        logger.warning(f"Status transition failed for order {order_id}: {e}")

    logger.info(
        f"Payment succeeded: order={order_id}, intent={intent_id}"
    )


def _handle_payment_failed(payment_intent: dict):
    """
    Handle payment_intent.payment_failed event.

    Updates:
    - Order.payment_status → FAILED
    - Payment.status → FAILED

    NOTE: We do NOT cancel the order on payment failure.
    The buyer might retry payment. Order stays PENDING.
    They can create a new PaymentIntent and try again.

    IDEMPOTENCY: handled upstream in stripe_webhook() via event-ID dedup.
    Deliberately NOT gated here on order.payment_status, unlike the
    succeeded handler — two genuinely different declines on the same
    order (retry with a different card, that one fails too) are both
    real failures and both should increment the metrics below.
    """
    intent_id = payment_intent.get("id")
    metadata = payment_intent.get("metadata", {})
    order_id = metadata.get("order_id")
    last_error = payment_intent.get("last_payment_error") or {}
    failure_message = last_error.get("message", "Unknown")

    if not order_id:
        logger.error(f"payment_intent.payment_failed: no order_id in metadata")
        return

    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        logger.error(f"payment_intent.payment_failed: order {order_id} not found")
        return

    # Update payment status — order status stays PENDING (buyer can retry)
    order.payment_status = Order.PAYMENT_FAILED
    order.save(update_fields=["payment_status", "updated_at"])

    Payment.objects.filter(order=order).update(status=Order.PAYMENT_FAILED)

    payment_attempts_total.labels(status="failure").inc()
    # error_code/decline_code come from Stripe's own bounded enum of card
    # error codes — not free text like refund reasons — so there's no
    # cardinality-explosion risk here. "unknown" covers the case where
    # Stripe sends a failure without one of these fields populated.
    payment_failures_total.labels(
        error_code=last_error.get("code", "unknown"),
        decline_code=last_error.get("decline_code", "unknown"),
    ).inc()

    logger.warning(
        f"Payment failed: order={order_id}, intent={intent_id}, "
        f"reason={failure_message}"
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_checkout_session(request):
    """
    POST /api/v1/payments/create-checkout-session/
    Create a Stripe Checkout Session and return the redirect URL.
    """
    import stripe
    from django.conf import settings
    stripe.api_key = settings.STRIPE_SECRET_KEY

    order_id = request.data.get("order_id")
    if not order_id:
        return Response({"error": "order_id is required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        order = Order.objects.get(id=order_id, buyer_id=request.user.id)
    except Order.DoesNotExist:
        return Response({"error": "Order not found"}, status=status.HTTP_404_NOT_FOUND)

    amount_in_paise = int(order.total_price * 100)

    # Not one of the three operation labels metrics.py's comment lists, but
    # it's a real stripe.* call in this file, so it gets its own operation
    # name rather than being silently skipped or mislabeled as
    # create_payment_intent.
    _start = time.monotonic()
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "inr",
                "product_data": {"name": f"CampusCart Order #{order.id}"},
                "unit_amount": amount_in_paise,
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=f"http://192.168.122.55:30080/orders/order_detail.html?id={order.id}&payment=success",
        cancel_url=f"http://192.168.122.55:30080/orders/checkout.html?cancel=true",
        metadata={"order_id": str(order.id), "buyer_id": str(order.buyer_id)},
    )
    stripe_api_duration_seconds.labels(operation="create_checkout_session").observe(
        time.monotonic() - _start
    )

    return Response({"url": session.url})