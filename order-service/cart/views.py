import logging
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Cart, CartItem
from .serializers import CartSerializer, CartItemSerializer, fetch_product

logger = logging.getLogger(__name__)


class CartViewSet(viewsets.ViewSet):
    """
    Cart operations for the authenticated user.

    All endpoints require JWT authentication.
    request.user is a MicroserviceUser built from JWT payload.
    request.user.id is the integer user ID from auth-service.

    Endpoints:
        GET  /api/v1/cart/          → list (view cart)
        POST /api/v1/cart/add/      → add item
        POST /api/v1/cart/remove/   → remove item
        POST /api/v1/cart/clear/    → clear cart
        GET  /api/v1/cart/total/    → cart total
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_cart(self, user_id: int) -> Cart:
        """
        Get or create a cart for this user.

        WHY get_or_create:
        First request → creates a new empty cart.
        Subsequent requests → returns existing cart.
        Atomic operation — no race condition if two requests arrive simultaneously.
        """
        cart, created = Cart.objects.get_or_create(user_id=user_id)
        if created:
            logger.info(f"New cart created for user_id={user_id}")
        return cart

    def list(self, request):
        """
        GET /api/v1/cart/
        Return the current user's cart with all items and product details.
        Product details are fetched from product-service by the serializer.
        """
        cart = self.get_cart(request.user.id)
        serializer = CartSerializer(cart)
        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="add")
    def add(self, request):
        """
        POST /api/v1/cart/add/
        Add a product to cart, or increase quantity if already present.

        Request body:
            {
                "product_id": 42,
                "quantity": 1        (optional, default=1)
            }

        Flow:
        1. Validate product_id is provided
        2. Call product-service to verify product exists and is available
        3. Snapshot price and title from product-service response
        4. get_or_create CartItem (update quantity if exists)
        5. Return updated cart

        WHY we fetch from product-service:
        - Verify product actually exists (user might send fake product_id)
        - Get authoritative price (never trust frontend for price)
        - Get product title for snapshot
        - Check product is available (not deleted/out of stock)
        """
        product_id = request.data.get("product_id")
        quantity = int(request.data.get("quantity", 1))

        # ── VALIDATION ────────────────────────────────────────
        if not product_id:
            return Response(
                {"error": "product_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if quantity < 1:
            return Response(
                {"error": "quantity must be at least 1"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── FETCH FROM PRODUCT-SERVICE ────────────────────────
        # This is the inter-service call.
        # We get authoritative price and title here.
        # If product-service is down → 503 response
        # If product not found → 404 response
        # ──────────────────────────────────────────────────────
        product = fetch_product(int(product_id))

        if not product:
            return Response(
                {"error": "Product not found or product-service unavailable"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check product is available for purchase
        if not product.get("is_available", False):
            return Response(
                {"error": "Product is not available"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check product is not soft-deleted
        if product.get("is_deleted", False):
            return Response(
                {"error": "Product no longer exists"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── SNAPSHOT PRICE AND TITLE ──────────────────────────
        # These values are frozen at add time.
        # Even if seller changes price later, cart shows this price.
        # ──────────────────────────────────────────────────────
        snapshot_price = product.get("price", "0")
        snapshot_title = product.get("title", "Unknown Product")

        # ── GET OR CREATE CART ────────────────────────────────
        cart = self.get_cart(request.user.id)

        # ── GET OR CREATE CART ITEM ───────────────────────────
        item, created = CartItem.objects.get_or_create(
            cart=cart,
            product_id=int(product_id),
            defaults={
                "product_title": snapshot_title,
                "price": snapshot_price,
                "quantity": quantity,
            },
        )

        if not created:
            # Item already in cart — increase quantity
            # Price stays the ORIGINAL snapshot price, not current price
            item.quantity += quantity
            item.save(update_fields=["quantity"])
            logger.info(
                f"CartItem updated: user={request.user.id}, "
                f"product={product_id}, new_qty={item.quantity}"
            )
        else:
            logger.info(
                f"CartItem created: user={request.user.id}, "
                f"product={product_id}, qty={quantity}, price={snapshot_price}"
            )

        serializer = CartSerializer(cart)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="remove")
    def remove(self, request):
        """
        POST /api/v1/cart/remove/
        Remove a product completely from the cart.

        Request body:
            {"product_id": 42}

        Silently succeeds even if product not in cart —
        idempotent operation (removing twice = same result as removing once).
        """
        product_id = request.data.get("product_id")

        if not product_id:
            return Response(
                {"error": "product_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cart = self.get_cart(request.user.id)
        deleted_count, _ = CartItem.objects.filter(
            cart=cart,
            product_id=int(product_id),
        ).delete()

        if deleted_count:
            logger.info(f"CartItem removed: user={request.user.id}, product={product_id}")
        
        serializer = CartSerializer(cart)
        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="clear")
    def clear(self, request):
        """
        POST /api/v1/cart/clear/
        Remove ALL items from the cart. Cart itself remains (empty).

        Used when:
        - User manually clears cart
        - After order is placed (orders/views.py calls this logic)
        """
        cart = self.get_cart(request.user.id)
        deleted_count, _ = cart.items.all().delete()
        logger.info(f"Cart cleared: user={request.user.id}, items_removed={deleted_count}")
        return Response({"message": "Cart cleared successfully"})

    @action(detail=False, methods=["get"], url_path="total")
    def total(self, request):
        """
        GET /api/v1/cart/total/
        Return cart total price and item count.
        Quick endpoint for displaying cart badge in navbar.
        Uses snapshot prices — no HTTP call to product-service needed.
        """
        cart = self.get_cart(request.user.id)
        return Response({
            "total_items": cart.total_items,
            "total_price": str(cart.total_price),
        })
