import logging
from decimal import Decimal
from django.db import models
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Order, OrderItem, Payment, OrderStatusHistory, RefundRequest
from .serializers import (
    RefundRequestSerializer,
    OrderSerializer,
    CreateOrderSerializer,
    OrderTrackingSerializer,
)
from cart.models import Cart, CartItem
from cart.serializers import fetch_product

logger = logging.getLogger(__name__)

import requests as http_requests


def notify_user(user_id, title, body, url, type_, data, jwt_token):
    try:
        http_requests.post(
            'http://notification-service:8000/api/v1/push/notify/',
            json={'user_id': user_id, 'title': title, 'body': body, 'url': url, 'type': type_, 'data': data},
            headers={'Authorization': f'Bearer {jwt_token}'},
            timeout=3,
        )
    except Exception as e:
        logger.error(f'Failed to send notification to user_id={user_id}: {e}')


class IsOrderParticipant(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.buyer_id == request.user.id or obj.seller_id == request.user.id


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, IsOrderParticipant]

    def get_queryset(self):
        user_id = self.request.user.id
        return (
            Order.objects
            .filter(models.Q(buyer_id=user_id) | models.Q(seller_id=user_id))
            .prefetch_related("items", "payment", "status_history")
            .order_by("-created_at")
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        data = dict(serializer.data)
        jwt_token = str(request.auth) if request.auth else ''
        try:
            res = http_requests.get(
                f'http://auth-service:8000/api/v1/users/public/{instance.buyer_id}/',
                headers={'Authorization': f'Bearer {jwt_token}'},
                timeout=3,
            )
            if res.ok:
                buyer_info = res.json()
                data['buyer'] = {'name': buyer_info.get('name', '-'), 'email': buyer_info.get('email', '-')}
        except Exception as e:
            logger.warning(f'Could not enrich buyer info: {e}')
            data['buyer'] = {'name': '-', 'email': '-'}
        return Response(data)

    @action(detail=False, methods=["post"], url_path="create")
    def create_from_cart(self, request):
        input_serializer = CreateOrderSerializer(data=request.data)
        if not input_serializer.is_valid():
            return Response(input_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        payment_method = input_serializer.validated_data["payment_method"]
        cart, _ = Cart.objects.get_or_create(user_id=request.user.id)
        cart_items = list(cart.items.all())
        if not cart_items:
            return Response({"error": "Cart is empty."}, status=status.HTTP_400_BAD_REQUEST)
        enriched_items = []
        invalid_products = []
        for cart_item in cart_items:
            product = fetch_product(cart_item.product_id)
            if not product:
                invalid_products.append({"product_id": cart_item.product_id, "error": "Product not found"})
                continue
            if not product.get("is_available", False) or product.get("is_deleted", False):
                invalid_products.append({"product_id": cart_item.product_id, "error": "Product unavailable"})
                continue
            seller_id = product.get("owner_id")
            if not seller_id:
                invalid_products.append({"product_id": cart_item.product_id, "error": "Could not determine seller"})
                continue
            enriched_items.append({"cart_item": cart_item, "product": product, "seller_id": int(seller_id)})
        if invalid_products:
            return Response({"error": "Some products unavailable", "invalid_products": invalid_products}, status=status.HTTP_400_BAD_REQUEST)
        seller_groups = {}
        for item in enriched_items:
            sid = item["seller_id"]
            if sid not in seller_groups:
                seller_groups[sid] = []
            seller_groups[sid].append(item)
        created_orders = []
        ordered_cart_item_ids = []
        for seller_id, items in seller_groups.items():
            total = Decimal("0.00")
            for item in items:
                total += item["cart_item"].price * item["cart_item"].quantity
            order = Order.objects.create(buyer_id=request.user.id, seller_id=seller_id, total_price=total, status=Order.STATUS_PENDING, payment_status=Order.PAYMENT_PENDING)
            for item in items:
                cart_item = item["cart_item"]
                OrderItem.objects.create(order=order, product_id=cart_item.product_id, seller_id=seller_id, product_title=cart_item.product_title, price=cart_item.price, quantity=cart_item.quantity)
                ordered_cart_item_ids.append(cart_item.id)
            Payment.objects.create(order=order, method=payment_method, amount=total, status=Order.PAYMENT_PENDING)
            OrderStatusHistory.objects.create(order=order, from_status="", to_status=Order.STATUS_PENDING, actor_id=request.user.id, note="Order placed by buyer", timestamp=timezone.now())
            created_orders.append(order)
            jwt_token = str(request.auth) if request.auth else ''
            notify_user(user_id=seller_id, title='New Order Received!', body=f'Order #{order.id} — ₹{total} — {len(items)} item(s)', url='/seller/orders.html', type_='order', data={'order_id': order.id}, jwt_token=jwt_token)
        CartItem.objects.filter(id__in=ordered_cart_item_ids).delete()
        serializer = OrderSerializer(created_orders, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        order = self.get_object()
        if order.buyer_id != request.user.id:
            return Response({"error": "Only the buyer can cancel this order."}, status=status.HTTP_403_FORBIDDEN)
        try:
            order.set_status(Order.STATUS_CANCELLED, actor_id=request.user.id, note="Cancelled by buyer")
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=["get"], url_path="track")
    def track(self, request, pk=None):
        order = self.get_object()
        payload = {"order_id": order.id, "current_status": order.status, "status_display": dict(Order.STATUS_CHOICES).get(order.status, order.status), "timeline": list(order.status_history.order_by("timestamp")), "created_at": order.created_at, "updated_at": order.updated_at}
        return Response(OrderTrackingSerializer(payload).data)

    @action(detail=True, methods=["patch"], url_path="update_status")
    def update_status(self, request, pk=None):
        order = self.get_object()
        if order.seller_id != request.user.id:
            return Response({"error": "Only seller may update status."}, status=status.HTTP_403_FORBIDDEN)
        new_status = (request.data.get("status") or "").upper()
        allowed = [s for s, _ in Order.STATUS_CHOICES]
        if not new_status or new_status not in allowed:
            return Response({"error": "Invalid status."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            order.set_status(new_status, actor_id=request.user.id, note=request.data.get("note"))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if new_status == Order.STATUS_PAID:
            order.payment_status = Order.PAYMENT_SUCCESS
            order.save(update_fields=["payment_status", "updated_at"])
            Payment.objects.filter(order=order).update(status=Order.PAYMENT_SUCCESS)
        jwt_token = str(request.auth) if request.auth else ""
        msg_map = {"PAID": "Your payment was received. ✅", "SHIPPED": "Your order has been shipped! 🚚", "DELIVERED": "Your order has been delivered. 🎁", "COMPLETED": "Order completed — thank you! 🎉", "CANCELLED": "Your order was cancelled. ❌"}
        notify_user(user_id=order.buyer_id, title=f"Order {new_status.title()}", body=msg_map.get(new_status, f"Order #{order.id} status: {new_status}"), url="/orders/my_orders.html", type_="order_status", data={"order_id": order.id, "status": new_status}, jwt_token=jwt_token)
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=["post"], url_path="confirm_delivery")
    def confirm_delivery(self, request, pk=None):
        order = self.get_object()
        if order.buyer_id != request.user.id:
            return Response({"error": "Only buyer can confirm delivery."}, status=status.HTTP_403_FORBIDDEN)
        if order.status not in [Order.STATUS_SHIPPED, Order.STATUS_DELIVERED]:
            return Response({"error": "Order must be shipped first."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            order.set_status(Order.STATUS_DELIVERED, actor_id=request.user.id, note="Delivery confirmed by buyer")
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        jwt_token = str(request.auth) if request.auth else ""
        notify_user(user_id=order.seller_id, title="📦 Delivery Confirmed", body=f"Buyer confirmed delivery for order #{order.id}.", url="/seller/orders.html", type_="order_delivered", data={"order_id": order.id}, jwt_token=jwt_token)
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=["post"], url_path="simulate_payment")
    def simulate_payment(self, request, pk=None):
        order = self.get_object()
        if order.buyer_id != request.user.id:
            return Response({"error": "Only buyer can confirm payment."}, status=status.HTTP_403_FORBIDDEN)
        payment, _ = Payment.objects.get_or_create(order=order, defaults={"method": "CARD", "amount": order.total_price})
        payment.status = Order.PAYMENT_SUCCESS
        payment.save(update_fields=["status"])
        order.payment_status = Order.PAYMENT_SUCCESS
        order.save(update_fields=["payment_status", "updated_at"])
        if order.status == Order.STATUS_PENDING:
            try:
                order.set_status(Order.STATUS_PAID, actor_id=request.user.id, note="Payment confirmed via Stripe")
            except ValueError:
                pass
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=["post"], url_path="refund_request")
    def refund_request(self, request, pk=None):
        order = self.get_object()
        if order.buyer_id != request.user.id:
            return Response({"error": "Only buyer can request a refund."}, status=403)
        if order.status not in [Order.STATUS_PAID, Order.STATUS_SHIPPED, Order.STATUS_DELIVERED]:
            return Response({"error": "Refund not allowed for this order status."}, status=400)
        if RefundRequest.objects.filter(order=order).exists():
            return Response({"error": "Refund already requested."}, status=400)
        reason = request.data.get("reason", "").strip()
        if not reason:
            return Response({"error": "Refund reason is required."}, status=400)
        refund = RefundRequest.objects.create(order=order, buyer_id=order.buyer_id, seller_id=order.seller_id, reason=reason)
        jwt_token = str(request.auth) if request.auth else ''
        notify_user(user_id=order.seller_id, title="Refund Requested", body=f"Buyer requested refund for order #{order.id}.", url=f"/seller/order_detail.html?id={order.id}", type_="refund", data={"order_id": order.id}, jwt_token=jwt_token)
        return Response(RefundRequestSerializer(refund).data, status=201)

    @action(detail=True, methods=["patch"], url_path="refund_decision")
    def refund_decision(self, request, pk=None):
        order = self.get_object()
        if order.seller_id != request.user.id:
            return Response({"error": "Only seller can decide on refunds."}, status=403)
        try:
            refund = order.refund_request
        except RefundRequest.DoesNotExist:
            return Response({"error": "No refund request found."}, status=404)
        if refund.status != RefundRequest.STATUS_PENDING:
            return Response({"error": f"Refund already {refund.status.lower()}."}, status=400)
        decision = (request.data.get("decision") or "").upper()
        note = request.data.get("note", "")
        if decision not in ["APPROVE", "REJECT"]:
            return Response({"error": "Decision must be APPROVE or REJECT."}, status=400)
        if decision == "APPROVE":
            refund.approve(note=note)
            Payment.objects.filter(order=order).update(status=Order.PAYMENT_REFUNDED)
        else:
            refund.reject(note=note)
        jwt_token = str(request.auth) if request.auth else ''
        notify_user(user_id=order.buyer_id, title=f"Refund {decision.title()}d", body=f"Your refund for order #{order.id} was {decision.lower()}d.", url=f"/orders/order_detail.html?id={order.id}", type_="refund_update", data={"order_id": order.id}, jwt_token=jwt_token)
        return Response(RefundRequestSerializer(refund).data)

    @action(detail=True, methods=["get"], url_path="refund_status")
    def refund_status(self, request, pk=None):
        order = self.get_object()
        try:
            refund = order.refund_request
            return Response(RefundRequestSerializer(refund).data)
        except RefundRequest.DoesNotExist:
            pass
        payment = Payment.objects.filter(order=order).first()
        if not payment or payment.status != Order.PAYMENT_REFUNDED:
            return Response(None)
        return Response({"status": "APPROVED", "refunded_amount": str(payment.amount)})
