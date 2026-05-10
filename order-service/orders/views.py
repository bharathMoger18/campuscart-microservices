import logging
from decimal import Decimal
from django.db import models
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Order, OrderItem, Payment, OrderStatusHistory
from .serializers import (
    OrderSerializer,
    CreateOrderSerializer,
    OrderTrackingSerializer,
)
from cart.models import Cart, CartItem
from cart.serializers import fetch_product

logger = logging.getLogger(__name__)


class IsOrderParticipant(permissions.BasePermission):
    """
    Object-level permission.
    Only the buyer or seller of an order can access it.

    MICROSERVICE NOTE:
    Monolith: obj.buyer == request.user (ORM object comparison)
    Microservice: obj.buyer_id == request.user.id (integer comparison)

    No database lookup needed — we compare integers directly.
    request.user.id comes from JWT token (MicroserviceUser).
    obj.buyer_id comes from the Order row in our database.
    """

    def has_object_permission(self, request, view, obj):
        return (
            obj.buyer_id == request.user.id
            or obj.seller_id == request.user.id
        )


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Order management for authenticated users.

    ReadOnlyModelViewSet provides:
        GET /api/v1/orders/       → list()
        GET /api/v1/orders/<id>/  → retrieve()

    Custom actions add:
        POST /api/v1/orders/create/       → create_from_cart()
        POST /api/v1/orders/<id>/cancel/  → cancel()
        GET  /api/v1/orders/<id>/track/   → track()
    """

    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, IsOrderParticipant]

    def get_queryset(self):
        """
        Return orders where the user is buyer OR seller.

        WHY Q objects:
        We need OR condition — standard filter() only does AND.
        models.Q(buyer_id=X) | models.Q(seller_id=X) generates:
        WHERE buyer_id = X OR seller_id = X

        prefetch_related loads items, payment, status_history
        in 3 extra queries instead of N queries (avoids N+1 problem).
        """
        user_id = self.request.user.id
        return (
            Order.objects
            .filter(
                models.Q(buyer_id=user_id) | models.Q(seller_id=user_id)
            )
            .prefetch_related("items", "payment", "status_history")
            .order_by("-created_at")
        )

    @action(detail=False, methods=["post"], url_path="create")
    def create_from_cart(self, request):
        """
        POST /api/v1/orders/create/
        Convert the user's cart into one or more orders.

        WHY multiple orders?
        If cart has products from 3 sellers → 3 orders created.
        Each seller manages their own order independently.

        Flow:
        1. Validate request (payment_method)
        2. Get user's cart — fail if empty
        3. For each cart item:
           a. Call product-service to verify product exists
           b. Extract seller_id (owner_id) from product response
           c. Validate product is available
        4. Group cart items by seller_id
        5. For each seller group:
           a. Create Order
           b. Create OrderItems (snapshot price, title, seller_id)
           c. Create Payment record
           d. Create initial OrderStatusHistory entry
        6. Delete ordered cart items (not the cart itself)
        7. Return all created orders

        SECURITY: seller_id ALWAYS comes from product-service.
        Frontend cannot inject a fake seller_id.
        """

        # ── STEP 1: Validate input ────────────────────────────
        input_serializer = CreateOrderSerializer(data=request.data)
        if not input_serializer.is_valid():
            return Response(input_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        payment_method = input_serializer.validated_data["payment_method"]

        # ── STEP 2: Get cart ──────────────────────────────────
        cart, _ = Cart.objects.get_or_create(user_id=request.user.id)
        cart_items = list(cart.items.all())

        if not cart_items:
            return Response(
                {"error": "Cart is empty. Add items before creating an order."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── STEP 3: Fetch product details + validate ──────────
        # For each cart item, call product-service.
        # Collect: product data + seller_id
        # Reject entire order if ANY product is unavailable.
        enriched_items = []
        invalid_products = []

        for cart_item in cart_items:
            product = fetch_product(cart_item.product_id)

            if not product:
                invalid_products.append({
                    "product_id": cart_item.product_id,
                    "title": cart_item.product_title,
                    "error": "Product not found or product-service unavailable",
                })
                continue

            if not product.get("is_available", False) or product.get("is_deleted", False):
                invalid_products.append({
                    "product_id": cart_item.product_id,
                    "title": cart_item.product_title,
                    "error": "Product is no longer available",
                })
                continue

            # ── CRITICAL: seller_id from product-service ──────
            # owner_id in product-service = seller_id in our DB
            # This is the General's security rule:
            # NEVER trust frontend for seller_id
            # ──────────────────────────────────────────────────
            seller_id = product.get("owner_id")
            if not seller_id:
                invalid_products.append({
                    "product_id": cart_item.product_id,
                    "title": cart_item.product_title,
                    "error": "Could not determine seller",
                })
                continue

            enriched_items.append({
                "cart_item": cart_item,
                "product": product,
                "seller_id": int(seller_id),
            })

        # If any products are invalid, reject the entire order
        if invalid_products:
            return Response(
                {
                    "error": "Some products in your cart are unavailable",
                    "invalid_products": invalid_products,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── STEP 4: Group by seller_id ────────────────────────
        # One order per seller. {seller_id: [enriched_item, ...]}
        seller_groups = {}
        for item in enriched_items:
            sid = item["seller_id"]
            if sid not in seller_groups:
                seller_groups[sid] = []
            seller_groups[sid].append(item)

        # ── STEP 5: Create orders ─────────────────────────────
        created_orders = []
        ordered_cart_item_ids = []

        for seller_id, items in seller_groups.items():

            # Calculate total for this seller's items
            total = Decimal("0.00")
            for item in items:
                total += item["cart_item"].price * item["cart_item"].quantity

            # Create the Order
            order = Order.objects.create(
                buyer_id=request.user.id,
                seller_id=seller_id,
                total_price=total,
                status=Order.STATUS_PENDING,
                payment_status=Order.PAYMENT_PENDING,
            )

            # Create OrderItems — snapshot everything
            for item in items:
                cart_item = item["cart_item"]
                product = item["product"]

                OrderItem.objects.create(
                    order=order,
                    product_id=cart_item.product_id,
                    seller_id=seller_id,
                    # ── SNAPSHOT at order time ─────────────────
                    # These values are frozen forever.
                    # Even if product price changes tomorrow,
                    # this order shows today's price.
                    product_title=cart_item.product_title,
                    price=cart_item.price,
                    quantity=cart_item.quantity,
                )
                ordered_cart_item_ids.append(cart_item.id)

            # Create Payment record
            Payment.objects.create(
                order=order,
                method=payment_method,
                amount=total,
                status=Order.PAYMENT_PENDING,
            )

            # Create initial status history entry
            OrderStatusHistory.objects.create(
                order=order,
                from_status="",
                to_status=Order.STATUS_PENDING,
                actor_id=request.user.id,
                note="Order placed by buyer",
                timestamp=timezone.now(),
            )

            logger.info(
                f"Order created: id={order.id}, buyer={request.user.id}, "
                f"seller={seller_id}, total={total}, items={len(items)}"
            )
            created_orders.append(order)

        # ── STEP 6: Clear ordered cart items ──────────────────
        # Only delete items that were successfully ordered.
        # Cart itself remains (empty) for future use.
        CartItem.objects.filter(id__in=ordered_cart_item_ids).delete()
        logger.info(
            f"Cart items cleared after order: user={request.user.id}, "
            f"items_cleared={len(ordered_cart_item_ids)}"
        )

        # ── STEP 7: Return created orders ─────────────────────
        serializer = OrderSerializer(created_orders, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        """
        POST /api/v1/orders/<id>/cancel/
        Buyer cancels their order.

        Rules:
        - Only the buyer can cancel
        - Only PENDING or CONFIRMED orders can be cancelled
          (state machine enforces this via set_status)
        - SHIPPED orders cannot be cancelled
        """
        order = self.get_object()

        # Only buyer can cancel
        if order.buyer_id != request.user.id:
            return Response(
                {"error": "Only the buyer can cancel this order."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            order.set_status(
                Order.STATUS_CANCELLED,
                actor_id=request.user.id,
                note="Cancelled by buyer",
            )
        except ValueError as exc:
            # set_status raises ValueError for invalid transitions
            # e.g. trying to cancel a SHIPPED order
            return Response(
                {"error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info(f"Order cancelled: id={order.id}, buyer={request.user.id}")
        serializer = OrderSerializer(order)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="track")
    def track(self, request, pk=None):
        """
        GET /api/v1/orders/<id>/track/
        Return order tracking timeline.

        Shows full status history sorted by timestamp.
        Frontend uses this to display:
        "Order placed → Confirmed → Shipped → Delivered"
        """
        order = self.get_object()

        payload = {
            "order_id": order.id,
            "current_status": order.status,
            "status_display": dict(Order.STATUS_CHOICES).get(order.status, order.status),
            "timeline": list(order.status_history.order_by("timestamp")),
            "created_at": order.created_at,
            "updated_at": order.updated_at,
        }

        serializer = OrderTrackingSerializer(payload)
        return Response(serializer.data)
