import httpx
from django.conf import settings
from rest_framework import serializers
from .models import Product


def get_user_info(user_id: int) -> dict:
    """
    Fetch user details from auth-service.
    Returns dict with id, name, email or fallback if call fails.

    This is synchronous inter-service communication.
    Called only when we need to display owner info in the response.
    """
    try:
        response = httpx.get(
            f"{settings.AUTH_SERVICE_URL}/api/v1/users/public/{user_id}/",
            timeout=3.0,  # Don't wait more than 3 seconds
        )
        if response.status_code == 200:
            return response.json()
    except httpx.RequestError:
        # Auth-service is down or unreachable — fail gracefully
        pass

    # Fallback: return minimal info so product API still works
    return {"id": user_id, "name": "Unknown", "email": ""}


class ProductSerializer(serializers.ModelSerializer):
    # Read-only fields that come from auth-service
    owner_name = serializers.SerializerMethodField()
    owner_email = serializers.SerializerMethodField()

    # Read-only computed fields from model properties
    average_rating = serializers.FloatField(read_only=True)
    total_reviews = serializers.IntegerField(read_only=True)
    rating_breakdown = serializers.SerializerMethodField()

    # Reviews nested inside product detail
    reviews = serializers.SerializerMethodField()

    # Custom image URL handler
    image = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "owner_id",
            "owner_name",
            "owner_email",
            "title",
            "description",
            "category",
            "price",
            "image",
            "is_available",
            "average_rating",
            "total_reviews",
            "rating_breakdown",
            "reviews",
            "created_at",
            "updated_at",
        ]
        # owner_id is set from JWT in the view, not from request body
        read_only_fields = ["owner_id", "created_at", "updated_at"]

    def get_owner_name(self, obj):
        """Fetch owner name from auth-service."""
        user_info = get_user_info(obj.owner_id)
        return user_info.get("name", "Unknown")

    def get_owner_email(self, obj):
        """Fetch owner email from auth-service."""
        user_info = get_user_info(obj.owner_id)
        return user_info.get("email", "")

    def get_image(self, obj):
        """Return full media URL for the image."""
        if obj.image:
            return "/media/" + str(obj.image)
        return None

    def get_rating_breakdown(self, obj):
        """Return star rating breakdown."""
        return obj.rating_breakdown()

    def get_reviews(self, obj):
        """Return reviews only on product detail, not list view."""
        from reviews.serializers import ReviewSerializer
        # Only include reviews when retrieving a single product
        request = self.context.get("request")
        if request and hasattr(request, "parser_context"):
            kwargs = request.parser_context.get("kwargs", {})
            if "pk" in kwargs:
                reviews = obj.reviews.all()
                return ReviewSerializer(reviews, many=True, context=self.context).data
        return []
