from rest_framework import serializers
from .models import Wishlist, WishlistItem
from products.serializers import ProductSerializer


class WishlistItemSerializer(serializers.ModelSerializer):
    """
    Serializes a single item in the wishlist.
    Nests full product details inside each item.
    """
    # Nest full product details — ProductSerializer handles image,
    # ratings, owner info etc.
    product = ProductSerializer(read_only=True)

    class Meta:
        model = WishlistItem
        fields = ["id", "product", "added_at"]
        read_only_fields = ["id", "product", "added_at"]


class WishlistSerializer(serializers.ModelSerializer):
    """
    Serializes the entire wishlist with all items nested inside.
    """
    # Nested items — all wishlist items with full product details
    items = WishlistItemSerializer(many=True, read_only=True)

    class Meta:
        model = Wishlist
        fields = [
            "id",
            "user_id",
            "items",
            "created_at",
            "updated_at",
        ]
        # user_id is set from JWT in the view — client cannot send it
        read_only_fields = ["user_id", "items", "created_at", "updated_at"]
