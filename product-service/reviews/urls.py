from rest_framework.routers import DefaultRouter
from .views import ReviewViewSet

# DefaultRouter generates:
# GET    /reviews/         → list all reviews
# POST   /reviews/         → create review (JWT required)
# GET    /reviews/<pk>/    → get single review
# PUT    /reviews/<pk>/    → update review (JWT + author)
# DELETE /reviews/<pk>/    → delete review (JWT + author)

router = DefaultRouter()
router.register(r"reviews", ReviewViewSet, basename="review")

urlpatterns = router.urls
