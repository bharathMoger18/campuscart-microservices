from django.urls import path, include, re_path
from django.http import JsonResponse
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
import redis
from django.conf import settings


def health_check(request):
    return JsonResponse({"status": "ok", "service": "notification-service"})


def ready_check(request):
    try:
        r = redis.from_url(settings.REDIS_URL)
        r.ping()
        return JsonResponse({"status": "ready", "redis": "ok", "service": "notification-service"})
    except Exception as e:
        return JsonResponse({"status": "not ready", "redis": "unavailable", "error": str(e)}, status=503)


urlpatterns = [
    # Health probes
    path("health/", health_check, name="health"),
    path("ready/", ready_check, name="ready"),

    # API v1
    path("api/v1/", include([
        path("chat/", include("chat.urls")),
        path("push/", include("push.urls")),
    ])),

    # Prometheus metrics
    # django_prometheus registers at /metrics
    # We include it at both / (native) and /-/ (convention used by other services)
    path("", include("django_prometheus.urls")),
    path("-/", include("django_prometheus.urls")),

    # OpenAPI docs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
