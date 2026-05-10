import logging
import stripe
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from orders.models import Order, Payment, OrderStatusHistory
from django.utils import timezone

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Configure Stripe with secret key from settings
# settings.STRIPE_SECRET_KEY comes from .env file
# ─────────────────────────────────────────────────────────────
stripe.api_key = settings.STRIPE_SECRET_KEY


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
    # Amount must be in CENTS (smallest currency unit)
    # $500.00 → 50000 cents
    # We use int() to avoid decimal precision issues
    try:
        amount_in_cents = int(order.total_price * 100)

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

        # ── STORE INTENT ID ON ORDER ──────────────────────────
        # We save the PaymentIntent ID so webhook handler can
        # find the order when Stripe calls back
        order.stripe_payment_intent = intent.id
        order.save(update_fields=["stripe_payment_intent", "updated_at"])

        # Also update the Payment record
        payment, _ = Payment.objects.get_or_create(
            order=order,
            defaults={"method": "CARD", "amount": order.total_price},
        )
        payment.stripe_payment_intent_id = intent.id
        payment.save(update_fields=["stripe_payment_intent_id"])

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
    Stripe may send the same event twice (network retries).
    We check current state before updating — safe to call multiple times.

    Events handled:
    - payment_intent.succeeded  → mark order CONFIRMED, payment SUCCESS
    - payment_intent.payment_failed → mark payment FAILED
    """

    # ── READ RAW PAYLOAD ──────────────────────────────────────
    # CRITICAL: use request.body (raw bytes), not request.data
    # Stripe signature is computed over the RAW bytes.
    # If Django parses the body first, signature verification fails.
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

    if not sig_header:
        logger.warning("Webhook received without Stripe signature header")
        return JsonResponse({"error": "Missing signature"}, status=400)

    # ── VERIFY STRIPE SIGNATURE ───────────────────────────────
    # construct_event() does three things:
    # 1. Decodes the payload JSON
    # 2. Verifies the HMAC-SHA256 signature
    # 3. Checks the timestamp to prevent replay attacks
    # If any check fails → raises stripe.error.SignatureVerificationError
    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            settings.STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        # Invalid JSON payload
        logger.error("Webhook: invalid JSON payload")
        return JsonResponse({"error": "Invalid payload"}, status=400)
    except stripe.error.SignatureVerificationError:
        # Signature mismatch — reject immediately
        # Could be: wrong secret, tampered payload, or replay attack
        logger.error("Webhook: signature verification failed")
        return JsonResponse({"error": "Invalid signature"}, status=400)

    # ── ROUTE TO EVENT HANDLER ────────────────────────────────
    event_type = event["type"]
    logger.info(f"Stripe webhook received: {event_type}")

    if event_type == "payment_intent.succeeded":
        _handle_payment_succeeded(event["data"]["object"])
    elif event_type == "payment_intent.payment_failed":
        _handle_payment_failed(event["data"]["object"])
    else:
        # Unknown event type — log and acknowledge
        # IMPORTANT: always return 200 for unknown events
        # Returning non-200 causes Stripe to retry → infinite loop
        logger.info(f"Unhandled webhook event type: {event_type}")

    # ── ALWAYS RETURN 200 TO STRIPE ───────────────────────────
    # Stripe considers non-200 as failed delivery and retries.
    # Even if our handler had an error, we return 200 to prevent
    # Stripe from retrying endlessly.
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
    If called twice with same event:
    - payment_status check prevents double-processing
    - set_status() would raise ValueError on second call
      (CONFIRMED → CONFIRMED is not a valid transition)
    - We catch that ValueError and log — no crash
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

    # ── IDEMPOTENCY CHECK ─────────────────────────────────────
    # If already processed, skip silently
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

    # Transition order status via state machine
    try:
        order.set_status(
            Order.STATUS_CONFIRMED,
            actor_id=None,          # Stripe triggered this, not a user
            note=f"Payment confirmed via Stripe. Intent: {intent_id}",
        )
    except ValueError as e:
        # Might already be CONFIRMED from a previous webhook
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
    """
    intent_id = payment_intent.get("id")
    metadata = payment_intent.get("metadata", {})
    order_id = metadata.get("order_id")
    failure_message = payment_intent.get("last_payment_error", {}).get("message", "Unknown")

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

    logger.warning(
        f"Payment failed: order={order_id}, intent={intent_id}, "
        f"reason={failure_message}"
    )
