from rest_framework import serializers
from .models import Order, OrderItem, Payment, OrderStatusHistory


class PaymentSerializer(serializers.ModelSerializer):
    """
    Serializes Payment record for an order.
    Shows: method, amount, stripe_payment_intent_id, status.
    """

    class Meta:
        model = Payment
        fields = [
            "id",
            "method",
            "amount",
            "stripe_payment_intent_id",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class OrderItemSerializer(serializers.ModelSerializer):
    """
    Serializes a single line item in an order.

    MICROSERVICE NOTE:
    Monolith had: product = ProductSerializer(read_only=True)
    We have: product_id + product_title + price (all snapshots)

    These snapshot values are FROZEN at order creation time.
    They never change even if the product is updated or deleted.
    This is intentional — orders are historical records.

    total_price is a @property on the model: price × quantity.
    """

    total_price = serializers.ReadOnlyField()

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "product_id",       # ID in product-service
            "seller_id",        # ID of seller in auth-service
            "product_title",    # snapshot — frozen at order time
            "price",            # snapshot — frozen at order time
            "quantity",
            "total_price",      # price × quantity (computed property)
            "created_at",
        ]
        read_only_fields = fields


class OrderStatusHistorySerializer(serializers.ModelSerializer):
    """
    Serializes a single status change event.

    MICROSERVICE NOTE:
    Monolith had: actor = UserSerializer(read_only=True)
    We have: actor_id = integer

    If frontend needs actor's name/email, it calls auth-service
    with this actor_id. We don't make that call here — keeping
    serializers fast and focused.
    """

    class Meta:
        model = OrderStatusHistory
        fields = [
            "id",
            "from_status",
            "to_status",
            "actor_id",     # integer — who made the change
            "note",
            "timestamp",
        ]
        read_only_fields = fields


class OrderSerializer(serializers.ModelSerializer):
    """
    Full order serializer — used for list and detail responses.

    Nests:
    - items: all OrderItems with snapshot product data
    - payment: Payment record with Stripe info
    - status_history: full audit trail of status changes

    MICROSERVICE NOTE:
    buyer_id and seller_id are plain integers.
    Monolith had UserSerializer nested objects here.
    We return IDs — frontend enriches with auth-service if needed.
    """

    items = OrderItemSerializer(many=True, read_only=True)
    payment = PaymentSerializer(read_only=True)
    status_history = OrderStatusHistorySerializer(many=True, read_only=True)

    # Computed field — human readable status label
    status_display = serializers.SerializerMethodField()
    payment_status_display = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "buyer_id",
            "seller_id",
            "total_price",
            "status",
            "status_display",
            "payment_status",
            "payment_status_display",
            "stripe_payment_intent",
            "items",
            "payment",
            "status_history",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_status_display(self, obj: Order) -> str:
        """Return human-readable status label."""
        return dict(Order.STATUS_CHOICES).get(obj.status, obj.status)

    def get_payment_status_display(self, obj: Order) -> str:
        """Return human-readable payment status label."""
        return dict(Order.PAYMENT_CHOICES).get(obj.payment_status, obj.payment_status)


class CreateOrderSerializer(serializers.Serializer):
    """
    Serializer for validating the create order request.

    The user only needs to send payment_method.
    Everything else comes from their cart and product-service.

    WHY a separate serializer for create?
    OrderSerializer is read-only — it shows order data.
    CreateOrderSerializer validates write input — what user sends.
    Separating read and write serializers is a best practice.
    """

    PAYMENT_METHOD_CHOICES = ["CARD", "COD"]

    payment_method = serializers.ChoiceField(
        choices=PAYMENT_METHOD_CHOICES,
        default="CARD",
    )

    def validate_payment_method(self, value):
        """Normalize to uppercase."""
        return value.upper()


class OrderTrackingSerializer(serializers.Serializer):
    """
    Lightweight serializer for order tracking timeline.

    Not a ModelSerializer because it aggregates data
    from multiple sources: Order + OrderStatusHistory + Payment.

    Used by: GET /api/v1/orders/<id>/track/
    """

    order_id = serializers.IntegerField()
    current_status = serializers.CharField()
    status_display = serializers.CharField()
    timeline = OrderStatusHistorySerializer(many=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
