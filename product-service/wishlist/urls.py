from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import WishlistViewSet

# WishlistViewSet uses ViewSet (not ModelViewSet).
# Router handles list automatically.
# Custom actions (add, remove, clear) are registered via @action
# decorator — router picks them up automatically.

router = DefaultRouter()
router.register(r"wishlist", WishlistViewSet, basename="wishlist")

urlpatterns = router.urls
