from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.response import Response
from rest_framework.decorators import api_view
from rest_framework import permissions
from django.db import connection
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


@api_view(["GET"])
def health(request):
    """Liveness probe — is the process running?"""
    return Response({"status": "ok", "service": "product-service"})


@api_view(["GET"])
def ready(request):
    """Readiness probe — is the service ready to serve traffic?"""
    try:
        connection.ensure_connection()
        db_status = "ok"
    except Exception:
        db_status = "unavailable"

    status_code = 200 if db_status == "ok" else 503
    return Response(
        {"status": "ready" if db_status == "ok" else "not ready", "database": db_status},
        status=status_code,
    )


urlpatterns = [
    # Health probes (no auth required)
    path("health/", health),
    path("ready/", ready),

    # Prometheus metrics
    path("-/", include("django_prometheus.urls")),

    # API routes
    path("api/v1/", include("products.urls")),
    path("api/v1/", include("reviews.urls")),
    path("api/v1/", include("wishlist.urls")),

    # API documentation
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/schema/swagger/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
