from rest_framework.routers import DefaultRouter
from .views import OrderViewSet

# ─────────────────────────────────────────────────────────────
# WHY DefaultRouter here (unlike cart which used manual mapping)?
#
# OrderViewSet extends ReadOnlyModelViewSet which provides
# standard list() and retrieve() actions. DefaultRouter
# knows how to wire these up correctly:
#
#   GET  /api/v1/orders/           → OrderViewSet.list
#   GET  /api/v1/orders/<pk>/      → OrderViewSet.retrieve
#
# Custom @action methods are also auto-registered:
#   POST /api/v1/orders/create/         → create_from_cart
#   POST /api/v1/orders/<pk>/cancel/    → cancel
#   GET  /api/v1/orders/<pk>/track/     → track
#
# These paths are mounted under /api/v1/ in order_service/urls.py
# ─────────────────────────────────────────────────────────────

router = DefaultRouter()
router.register(r"orders", OrderViewSet, basename="order")

urlpatterns = router.urls
