import httpx
from django.conf import settings
from rest_framework import serializers
from .models import Review


def get_user_info(user_id: int) -> dict:
    """
    Fetch user details from auth-service.
    Same pattern as products/serializers.py.
    Returns fallback dict if auth-service is unreachable.
    """
    try:
        response = httpx.get(
            f"{settings.AUTH_SERVICE_URL}/api/v1/users/public/{user_id}/",
            timeout=3.0,
        )
        if response.status_code == 200:
            return response.json()
    except httpx.RequestError:
        pass
    return {"id": user_id, "name": "Unknown", "email": ""}


class ReviewSerializer(serializers.ModelSerializer):
    # Read-only fields fetched from auth-service
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()

    # Read-only field from related Product (same DB — direct access works)
    product_title = serializers.CharField(
        source="product.title", read_only=True
    )

    class Meta:
        model = Review
        fields = [
            "id",
            "product",
            "product_title",
            "user_id",
            "user_name",
            "user_email",
            "rating",
            "comment",
            "created_at",
            "updated_at",
        ]
        # user_id is set from JWT in the view — client cannot send it
        read_only_fields = ["user_id", "created_at", "updated_at"]

    def get_user_name(self, obj):
        """Fetch reviewer's name from auth-service."""
        user_info = get_user_info(obj.user_id)
        return user_info.get("name", "Unknown")

    def get_user_email(self, obj):
        """Fetch reviewer's email from auth-service."""
        user_info = get_user_info(obj.user_id)
        return user_info.get("email", "")

    def validate_rating(self, value):
        """Ensure rating is between 1 and 5."""
        if value < 1 or value > 5:
            raise serializers.ValidationError(
                "Rating must be between 1 and 5."
            )
        return value

    def create(self, validated_data):
        """
        Create or update a review.
        One review per user per product — if review exists, update it.
        user_id is injected by the view from the JWT token.

        _was_created stashed on the returned instance (not a model field —
        just an in-memory attribute) so the view can tell create vs. update
        apart. Without this, reviews_submitted_total in views.py.perform_create
        can't distinguish "brand new review" from "user re-submitted/edited
        their existing review via this same endpoint", and was previously
        counting both as new submissions.
        """
        user_id = validated_data["user_id"]
        product = validated_data["product"]

        review, created = Review.objects.update_or_create(
            user_id=user_id,
            product=product,
            defaults={
                "rating": validated_data["rating"],
                "comment": validated_data.get("comment", ""),
            }
        )
        review._was_created = created
        return review