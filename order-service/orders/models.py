from decimal import Decimal
from django.db import models
from django.utils import timezone


class Order(models.Model):
    """
    Represents a purchase order from one buyer to one seller.

    MICROSERVICE CHANGES vs monolith:

    1. buyer = ForeignKey(User) → buyer_id = PositiveIntegerField()
       seller = ForeignKey(User) → seller_id = PositiveIntegerField()
       User table lives in auth-service's DB. No FK possible.

    2. seller_id is fetched from product-service when order is created.
       Flow: cart item has product_id → call product-service →
       get product.owner_id → that is seller_id.
       Frontend NEVER provides seller_id (security rule from General).

    3. State machine pattern kept exactly from monolith.
       VALID_TRANSITIONS enforces which status changes are allowed.
       set_status() validates before applying.

    STATUS FLOW:
        PENDING → CONFIRMED → SHIPPED → DELIVERED → COMPLETED
                            ↘ CANCELLED
    """

    # ── ORDER STATUS ──────────────────────────────────────────
    STATUS_PENDING = "PENDING"
    STATUS_CONFIRMED = "CONFIRMED"
    STATUS_SHIPPED = "SHIPPED"
    STATUS_DELIVERED = "DELIVERED"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_SHIPPED, "Shipped"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    # ── PAYMENT STATUS ────────────────────────────────────────
    PAYMENT_PENDING = "PENDING"
    PAYMENT_SUCCESS = "SUCCESS"
    PAYMENT_FAILED = "FAILED"
    PAYMENT_REFUNDED = "REFUNDED"

    PAYMENT_CHOICES = [
        (PAYMENT_PENDING, "Pending"),
        (PAYMENT_SUCCESS, "Success"),
        (PAYMENT_FAILED, "Failed"),
        (PAYMENT_REFUNDED, "Refunded"),
    ]

    # ── KEY CHANGE ────────────────────────────────────────────
    # Monolith: buyer = ForeignKey(AUTH_USER_MODEL, ...)
    #           seller = ForeignKey(AUTH_USER_MODEL, ...)
    # Microservice: plain integers — no FK to users table
    # buyer_id comes from request.user.id (JWT token)
    # seller_id comes from product-service (product.owner_id)
    # ──────────────────────────────────────────────────────────
    buyer_id = models.PositiveIntegerField()
    seller_id = models.PositiveIntegerField()

    total_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    payment_status = models.CharField(
        max_length=30,
        choices=PAYMENT_CHOICES,
        default=PAYMENT_PENDING,
    )

    # Stripe PaymentIntent ID — stored when payment is initiated
    stripe_payment_intent = models.CharField(max_length=255, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"Order(id={self.id}, buyer={self.buyer_id}, "
            f"seller={self.seller_id}, status={self.status})"
        )

    # ── STATE MACHINE ─────────────────────────────────────────
    # Defines which status transitions are valid.
    # Key = current status, Value = list of allowed next statuses.
    #
    # WHY a state machine?
    # Without it, anyone could set an order from CANCELLED → DELIVERED.
    # The state machine enforces the real-world business rules:
    # you cannot deliver an order that was cancelled.
    # ──────────────────────────────────────────────────────────
    VALID_TRANSITIONS = {
        STATUS_PENDING: [STATUS_CONFIRMED, STATUS_CANCELLED],
        STATUS_CONFIRMED: [STATUS_SHIPPED, STATUS_CANCELLED],
        STATUS_SHIPPED: [STATUS_DELIVERED],
        STATUS_DELIVERED: [STATUS_COMPLETED],
        STATUS_COMPLETED: [],       # terminal state — no further transitions
        STATUS_CANCELLED: [],       # terminal state — no further transitions
    }

    def can_transition_to(self, new_status: str) -> bool:
        """
        Check if transition from current status to new_status is valid.
        Returns True if allowed, False if not.
        """
        allowed = self.VALID_TRANSITIONS.get(self.status, [])
        return new_status in allowed

    def set_status(self, new_status: str, actor_id: int = None, note: str = None):
        """
        Safely update order status with validation and history logging.

        WHY:
        Direct self.status = "CANCELLED" bypasses validation.
        This method enforces valid transitions and creates an audit trail.

        actor_id: integer ID of user who made the change (from JWT)
        note: optional description of why the change was made
        """
        new_status = (new_status or "").upper()

        if not self.can_transition_to(new_status):
            raise ValueError(
                f"Invalid status transition: {self.status} → {new_status}. "
                f"Allowed: {self.VALID_TRANSITIONS.get(self.status, [])}"
            )

        previous_status = self.status
        self.status = new_status
        self.save(update_fields=["status", "updated_at"])

        # Create audit trail entry
        OrderStatusHistory.objects.create(
            order=self,
            from_status=previous_status,
            to_status=new_status,
            actor_id=actor_id,
            note=note,
            timestamp=timezone.now(),
        )


class OrderItem(models.Model):
    """
    A single product line within an order.

    MICROSERVICE CHANGES vs monolith:

    1. product = ForeignKey(Product, SET_NULL) → product_id = PositiveIntegerField()
       Product table lives in product-service's DB. No FK possible.

    2. NEW: seller_id = PositiveIntegerField()
       Snapshot of who sold this item at order time.
       Even if product is deleted from product-service,
       we know which seller fulfilled this item.

    3. product_title and price are SNAPSHOTS — kept from monolith.
       These values are frozen at order creation time.
       They NEVER change, even if seller updates the product.

    WHY SNAPSHOT?
    This is called DENORMALIZATION — storing redundant data
    intentionally for independence and correctness.
    An order from 2023 must show the 2023 price, not today's price.
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )

    # ── KEY CHANGE ────────────────────────────────────────────
    # Monolith: product = ForeignKey(Product, on_delete=SET_NULL)
    # Microservice: plain integer — product lives in product-service
    # ──────────────────────────────────────────────────────────
    product_id = models.PositiveIntegerField()

    # NEW: snapshot seller at order time
    seller_id = models.PositiveIntegerField(default=0)

    # SNAPSHOT fields — frozen at order creation (kept from monolith)
    product_title = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"OrderItem(product_id={self.product_id}, qty={self.quantity})"

    @property
    def total_price(self):
        """Line total = snapshot price × quantity."""
        return self.price * self.quantity


class Payment(models.Model):
    """
    Records the payment for an order.

    One order → one payment record.
    Tracks: method, amount, Stripe payment intent ID, status.

    NOTE: This model lives in the orders app (not payments app)
    because it is tightly coupled to Order via OneToOneField.
    The payments app handles Stripe webhook logic only.
    """

    METHOD_CARD = "CARD"
    METHOD_COD = "COD"
    METHOD_CHOICES = [
        (METHOD_CARD, "Card"),
        (METHOD_COD, "Cash on Delivery"),
    ]

    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name="payment",
    )
    method = models.CharField(
        max_length=20,
        choices=METHOD_CHOICES,
        default=METHOD_CARD,
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(
        max_length=30,
        choices=Order.PAYMENT_CHOICES,
        default=Order.PAYMENT_PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payment(order={self.order_id}, status={self.status})"


class OrderStatusHistory(models.Model):
    """
    Audit trail for every order status change.

    WHY:
    Every time an order status changes, we record:
    - What it changed FROM
    - What it changed TO
    - WHO changed it (actor_id)
    - WHEN it changed (timestamp)
    - WHY it changed (note)

    This gives complete order tracking history.
    Frontend can show a timeline: "Order placed → Confirmed → Shipped"

    MICROSERVICE CHANGE:
    Monolith: actor = ForeignKey(AUTH_USER_MODEL)
    Microservice: actor_id = PositiveIntegerField(null=True)
    We store the integer ID only. If we need actor's name/email,
    we call auth-service via HTTP with this ID.
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="status_history",
    )
    from_status = models.CharField(max_length=30, blank=True, default="")
    to_status = models.CharField(max_length=30)

    # ── KEY CHANGE ────────────────────────────────────────────
    # Monolith: actor = ForeignKey(AUTH_USER_MODEL, null=True)
    # Microservice: actor_id = PositiveIntegerField(null=True)
    # ──────────────────────────────────────────────────────────
    actor_id = models.PositiveIntegerField(null=True, blank=True)

    note = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField()

    class Meta:
        ordering = ["timestamp"]

    def __str__(self):
        return (
            f"OrderStatusHistory(order={self.order_id}, "
            f"{self.from_status}→{self.to_status})"
        )
