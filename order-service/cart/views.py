import logging
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Cart, CartItem
from .serializers import CartSerializer, CartItemSerializer, fetch_product

from orders.metrics import (
    cart_items_added_total,
    cart_abandonments_total,
    active_carts_gauge,
)

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
        product = fetch_product(int(product_id))

        if not product:
            return Response(
                {"error": "Product not found or product-service unavailable"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not product.get("is_available", False):
            return Response(
                {"error": "Product is not available"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if product.get("is_deleted", False):
            return Response(
                {"error": "Product no longer exists"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── SNAPSHOT PRICE AND TITLE ──────────────────────────
        snapshot_price = product.get("price", "0")
        snapshot_title = product.get("title", "Unknown Product")

        # ── GET OR CREATE CART ────────────────────────────────
        cart = self.get_cart(request.user.id)

        # ── ACTIVE CART GAUGE: snapshot state BEFORE mutating ─
        # active_carts_gauge tracks carts with >=1 item, not raw item count.
        # We only want to .inc() when this add transitions the cart from
        # empty → non-empty, so the "was it empty" check has to happen
        # before the get_or_create below changes that state.
        was_empty = not cart.items.exists()

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

        # cart_items_added_total documents itself as "items added", not
        # "add requests received" — incrementing by `quantity` so adding
        # 3x the same product registers as 3 items, not 1 event.
        cart_items_added_total.inc(quantity)

        if was_empty:
            active_carts_gauge.inc()

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

            # If that was the last item, the cart is no longer "active".
            # NOTE: this does NOT also increment cart_abandonments_total.
            # Removing one product isn't the same signal as "buyer walked
            # away from the cart entirely" — they might add something else
            # in the next minute. That stronger signal is reserved for an
            # explicit clear() below. If this ever proves wrong in practice
            # (e.g. carts going empty via remove() rarely get refilled),
            # worth revisiting.
            if not cart.items.exists():
                active_carts_gauge.dec()

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
        had_items = cart.items.exists()
        deleted_count, _ = cart.items.all().delete()
        logger.info(f"Cart cleared: user={request.user.id}, items_removed={deleted_count}")

        if had_items:
            active_carts_gauge.dec()

            # cart_abandonments_total: "had items but no order was created."
            # An explicit clear-all with items present is the cleanest
            # signal of that in this codebase. Caveat — this only catches
            # EXPLICIT clears. It does NOT catch silent abandonment (a cart
            # with items the buyer just stops returning to). Catching that
            # would need a scheduled job comparing CartItem timestamps
            # against a TTL, which doesn't exist yet. So today this metric
            # is a lower bound on real abandonment, not the full picture.
            cart_abandonments_total.inc()

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