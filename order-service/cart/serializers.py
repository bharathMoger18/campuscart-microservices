import httpx
from django.conf import settings
from rest_framework import serializers
from .models import Cart, CartItem


def fetch_product(product_id: int) -> dict | None:
    """
    Fetch product details from product-service via HTTP.

    WHY A SEPARATE FUNCTION:
    Both CartItemSerializer and cart views need product details.
    Centralizing the HTTP call here means one place to update
    if the product-service URL or response format changes.

    GRACEFUL FALLBACK:
    If product-service is down or returns non-200,
    we return None. Callers handle None safely.

    TIMEOUT:
    5 seconds max. We never want a slow product-service
    to make our cart API slow. Fail fast, fail safely.
    """
    try:
        url = f"{settings.PRODUCT_SERVICE_URL}/api/v1/products/{product_id}/"
        response = httpx.get(url, timeout=5.0)
        if response.status_code == 200:
            return response.json()
        return None
    except httpx.RequestError:
        # Network error, DNS failure, connection refused, timeout
        return None


class CartItemSerializer(serializers.ModelSerializer):
    """
    Serializer for CartItem.

    SNAPSHOT FIELDS (from our DB — always available):
    - product_id: the product's ID in product-service
    - product_title: name frozen at add time
    - price: price frozen at add time
    - quantity: current quantity
    - total_price: price × quantity

    ENRICHED FIELD (from product-service HTTP call):
    - product_detail: full product object (image, description, category)
      Falls back to snapshot data if product-service is unavailable.
    """

    # ── ENRICHED FIELD ────────────────────────────────────────
    # SerializerMethodField calls get_product_detail(self, obj)
    # This is where the inter-service HTTP call happens
    # ──────────────────────────────────────────────────────────
    product_detail = serializers.SerializerMethodField()

    # total_price is a @property on the model — expose it read-only
    total_price = serializers.ReadOnlyField()

    class Meta:
        model = CartItem
        fields = [
            "id",
            "product_id",        # ID stored in our DB
            "product_title",     # snapshot name
            "price",             # snapshot price (frozen at add time)
            "quantity",
            "total_price",       # price × quantity
            "product_detail",    # enriched from product-service
            "added_at",
        ]
        read_only_fields = ["id", "product_title", "price", "total_price", "added_at"]

    def get_product_detail(self, obj: CartItem) -> dict:
        """
        Fetch live product details from product-service.

        WHY: We store product_id + snapshot fields (title, price).
        But the frontend also needs: image, description, category,
        current availability. These come from product-service.

        FALLBACK: If product-service is down, return snapshot data.
        Cart still works — user sees title and price at minimum.
        """
        product = fetch_product(obj.product_id)

        if product:
            return {
                "id": product.get("id"),
                "title": product.get("title"),
                "price": product.get("price"),
                "image": product.get("image"),
                "category": product.get("category"),
                "is_available": product.get("is_available"),
                "description": product.get("description", ""),
            }

        # ── GRACEFUL FALLBACK ─────────────────────────────────
        # product-service unavailable — use our snapshot data
        # Cart still renders correctly, just without live image/category
        # ──────────────────────────────────────────────────────
        return {
            "id": obj.product_id,
            "title": obj.product_title,
            "price": str(obj.price),
            "image": None,
            "category": None,
            "is_available": None,
            "description": "Product details temporarily unavailable",
        }


class CartSerializer(serializers.ModelSerializer):
    """
    Serializer for the full Cart with all items.

    Shows:
    - cart metadata (id, user_id, created_at)
    - all items with product details
    - cart totals (total_items, total_price)
    """

    items = CartItemSerializer(many=True, read_only=True)

    # These are @property on the Cart model
    total_items = serializers.ReadOnlyField()
    total_price = serializers.ReadOnlyField()

    class Meta:
        model = Cart
        fields = [
            "id",
            "user_id",
            "items",
            "total_items",
            "total_price",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
