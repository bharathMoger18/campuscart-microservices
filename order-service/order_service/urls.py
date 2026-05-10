from django.urls import path, include
from django.http import JsonResponse
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)


# ─────────────────────────────────────────────────────────────
# HEALTH CHECK VIEWS
# ─────────────────────────────────────────────────────────────
# These are simple inline views — no need for a separate file.
# Kubernetes liveness probe calls /health/ every few seconds.
# Kubernetes readiness probe calls /ready/ before sending traffic.
# Both must:
#   - Require NO authentication
#   - Return quickly (no heavy DB queries)
#   - Return HTTP 200 when healthy
# ─────────────────────────────────────────────────────────────

def health(request):
    """
    Liveness probe — am I alive?
    Returns 200 if the Django process is running.
    No database check — just confirms the process is up.
    """
    return JsonResponse({"status": "ok", "service": "order-service"})


def ready(request):
    """
    Readiness probe — am I ready to serve traffic?
    Checks database connectivity before returning 200.
    Kubernetes will not send traffic until this returns 200.
    """
    from django.db import connection
    try:
        # Execute a trivial query to verify DB connection
        connection.ensure_connection()
        return JsonResponse({
            "status": "ready",
            "service": "order-service",
            "database": "connected",
        })
    except Exception as e:
        # Return 503 Service Unavailable — Kubernetes will not route traffic here
        return JsonResponse(
            {"status": "not ready", "error": str(e)},
            status=503,
        )


# ─────────────────────────────────────────────────────────────
# URL PATTERNS
# ─────────────────────────────────────────────────────────────
urlpatterns = [

    # ── HEALTH PROBES ─────────────────────────────────────────
    # No auth, no versioning, simple and fast
    path("health/", health, name="health"),
    path("ready/", ready, name="ready"),

    # ── PROMETHEUS METRICS ────────────────────────────────────
    # django-prometheus auto-creates /-/metrics endpoint
    # Prometheus scrapes this to collect request/DB metrics
    path("", include("django_prometheus.urls")),

    # ── API v1 ────────────────────────────────────────────────
    # All business endpoints live under /api/v1/
    path("api/v1/", include([
        path("", include("cart.urls")),      # /api/v1/cart/
        path("", include("orders.urls")),    # /api/v1/orders/
        path("", include("payments.urls")),  # /api/v1/payments/
    ])),

    # ── STRIPE WEBHOOK ────────────────────────────────────────
    # Outside /api/v1/ — Stripe calls this URL directly
    # URL configured in Stripe Dashboard — must never change
    # NO JWT auth — Stripe uses webhook signature verification
    path("webhooks/stripe/", include("payments.urls")),

    # ── API DOCS ──────────────────────────────────────────────
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
