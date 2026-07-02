from rest_framework import viewsets, permissions
from .models import Review
from .serializers import ReviewSerializer

from products.metrics import reviews_submitted_total


def _safe_rating_label(rating):
    """
    Clamps an incoming rating value to a label-safe string for
    reviews_submitted_total.

    STATUS (confirmed 2026-06-30): ReviewSerializer.validate_rating()
    already enforces 1 <= rating <= 5 before save(), so this is no longer
    a load-bearing fix — it's a defensive backstop in case rating ever
    reaches this point through a path that skips that validator (admin,
    management command, future serializer change). Kept in place since
    it's free insurance on a metric that feeds external monitoring, but
    str(instance.rating) alone would now be safe too.
    """
    try:
        rating_int = int(rating)
    except (TypeError, ValueError):
        return "out_of_range"
    if 1 <= rating_int <= 5:
        return str(rating_int)
    return "out_of_range"


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

    CORRECTED NOTE: unique_together = ("product", "user_id") on Review is
    real, but ReviewSerializer.create() uses update_or_create(), which
    proactively avoids ever hitting that constraint — a second POST for
    the same (product, user_id) pair succeeds as a silent in-place update,
    it does NOT 400. So perform_create below DOES need created/updated
    dedup logic for the metric — see _was_created check.
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
        Injects user_id from the verified JWT token. Client cannot fake this.

        Only increments reviews_submitted_total when serializer.save()
        produced a genuinely new row (_was_created=True, set in
        ReviewSerializer.create()). A re-submission for the same
        (product, user_id) pair updates the existing review in place and
        is NOT counted — same "only count real new activity" pattern as
        wishlist_additions_total's `if created:` check in wishlist/views.py.

        getattr default of True is a safety net only: it means "if some
        other code path's serializer.create() forgets to set this flag,
        fail toward counting rather than silently dropping a real metric."
        Under normal operation this attribute is always set by
        ReviewSerializer.create() above.
        """
        instance = serializer.save(user_id=self.request.user.id)
        if getattr(instance, "_was_created", True):
            reviews_submitted_total.labels(rating=_safe_rating_label(instance.rating)).inc()