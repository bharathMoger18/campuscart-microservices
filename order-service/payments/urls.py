from django.urls import path
from .views import create_payment_intent, stripe_webhook, create_checkout_session

# ─────────────────────────────────────────────────────────────
# Payments URLs
#
# This file is included TWICE in order_service/urls.py:
#
# 1. Under /api/v1/:
#    /api/v1/payments/create-intent/ → create_payment_intent
#    Requires JWT authentication.
#    Buyer calls this to get client_secret for Stripe.js
#
# 2. Under /webhooks/stripe/:
#    /webhooks/stripe/               → stripe_webhook
#    NO JWT auth — called by Stripe's servers.
#    Uses Stripe signature verification instead.
#
# WHY function-based views here instead of ViewSet?
# These two endpoints have completely different:
#   - Authentication (JWT vs Stripe signature)
#   - Request source (frontend user vs Stripe servers)
#   - Response format (DRF Response vs JsonResponse)
# A ViewSet would force them into the same auth/permission class.
# Function-based views give us precise control per endpoint.
# ─────────────────────────────────────────────────────────────

urlpatterns = [
    # JWT protected — buyer creates payment intent for their order
    path(
        "payments/create-checkout-session/",
        create_checkout_session,
        name="create-checkout-session",
    ),
    path(
        "payments/create-intent/",
        create_payment_intent,
        name="create-payment-intent",
    ),

    # No JWT — Stripe webhook, signature verified inside the view
    # When mounted under /webhooks/stripe/ this becomes:
    # /webhooks/stripe/ (empty string matches root of that prefix)
    path(
        "",
        stripe_webhook,
        name="stripe-webhook",
    ),
]
