from django.contrib import admin
from django.urls import path, include
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db import connection
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


@api_view(["GET"])
def health(request):
    """Liveness probe — always returns 200 if the process is running."""
    return Response({"status": "ok"})


@api_view(["GET"])
def ready(request):
    """Readiness probe — returns 200 only if DB is reachable."""
    try:
        connection.ensure_connection()
        return Response({"status": "ready"})
    except Exception:
        return Response({"status": "unavailable"}, status=503)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("users.urls")),
    path("health/", health, name="health"),
    path("ready/", ready, name="ready"),
    path("-/", include("django_prometheus.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
