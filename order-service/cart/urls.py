from django.urls import path
from .views import CartViewSet

# ─────────────────────────────────────────────────────────────
# WHY manual mapping instead of DefaultRouter?
#
# DefaultRouter is for ModelViewSet (list, create, retrieve,
# update, destroy). Our CartViewSet has custom actions only:
# list, add, remove, clear, total.
#
# Manual mapping is more explicit — you can see exactly which
# HTTP method calls which view method. No magic, no surprises.
#
# These paths are mounted under /api/v1/ in order_service/urls.py
# Final URLs:
#   GET  /api/v1/cart/         → CartViewSet.list
#   POST /api/v1/cart/add/     → CartViewSet.add
#   POST /api/v1/cart/remove/  → CartViewSet.remove
#   POST /api/v1/cart/clear/   → CartViewSet.clear
#   GET  /api/v1/cart/total/   → CartViewSet.total
# ─────────────────────────────────────────────────────────────

urlpatterns = [
    path(
        "cart/",
        CartViewSet.as_view({"get": "list"}),
        name="cart-detail",
    ),
    path(
        "cart/add/",
        CartViewSet.as_view({"post": "add"}),
        name="cart-add",
    ),
    path(
        "cart/remove/",
        CartViewSet.as_view({"post": "remove"}),
        name="cart-remove",
    ),
    path(
        "cart/clear/",
        CartViewSet.as_view({"post": "clear"}),
        name="cart-clear",
    ),
    path(
        "cart/total/",
        CartViewSet.as_view({"get": "total"}),
        name="cart-total",
    ),
]
