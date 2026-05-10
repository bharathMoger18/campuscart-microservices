from rest_framework import viewsets, permissions
from .models import Review
from .serializers import ReviewSerializer


class IsReviewOwnerOrReadOnly(permissions.BasePermission):
    """
    Custom permission:
    - Anyone can READ reviews
    - Only the review author can UPDATE or DELETE their review
    """
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        # Compare user_id integer with JWT user's id
        return obj.user_id == request.user.id


class ReviewViewSet(viewsets.ModelViewSet):
    """
    CRUD for reviews.

    list:     GET  /api/v1/reviews/         — public
    create:   POST /api/v1/reviews/         — JWT required
    retrieve: GET  /api/v1/reviews/<id>/    — public
    update:   PUT  /api/v1/reviews/<id>/    — JWT + author only
    destroy:  DELETE /api/v1/reviews/<id>/  — JWT + author only
    """
    queryset = Review.objects.select_related("product").all()
    serializer_class = ReviewSerializer
    permission_classes = [
        permissions.IsAuthenticatedOrReadOnly,
        IsReviewOwnerOrReadOnly
    ]

    def get_queryset(self):
        """
        Optionally filter reviews by product_id.
        GET /api/v1/reviews/?product=5  → reviews for product 5
        GET /api/v1/reviews/            → all reviews
        """
        queryset = Review.objects.select_related("product").all()
        product_id = self.request.query_params.get("product")
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        return queryset

    def perform_create(self, serializer):
        """
        Called when POST /api/v1/reviews/ is received.
        Injects user_id from the verified JWT token.
        Client cannot fake this.
        """
        serializer.save(user_id=self.request.user.id)
