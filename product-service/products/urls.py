from rest_framework.routers import DefaultRouter
from .views import ProductViewSet, SellerProductViewSet

# DefaultRouter automatically creates these URL patterns:
# GET    /products/           → ProductViewSet.list
# POST   /products/           → ProductViewSet.create
# GET    /products/<pk>/      → ProductViewSet.retrieve
# PUT    /products/<pk>/      → ProductViewSet.update
# PATCH  /products/<pk>/      → ProductViewSet.partial_update
# DELETE /products/<pk>/      → ProductViewSet.destroy
# (same pattern for seller/products/)

router = DefaultRouter()
router.register(r"products", ProductViewSet, basename="product")
router.register(r"seller/products", SellerProductViewSet, basename="seller-product")

urlpatterns = router.urls
