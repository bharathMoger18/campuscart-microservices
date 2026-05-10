from django.db import models


class Cart(models.Model):
    """
    A shopping cart belonging to one user.

    MICROSERVICE CHANGE:
    Monolith: user = ForeignKey(settings.AUTH_USER_MODEL)
    Microservice: user_id = PositiveIntegerField()

    WHY: The users table lives in auth-service's database.
    We cannot create a ForeignKey across two separate databases.
    We store only the integer ID. When we need user details,
    we call auth-service via HTTP.

    OneToOne equivalent: we enforce one cart per user via
    unique=True on user_id — same guarantee, no ForeignKey needed.
    """

    # ── KEY CHANGE ────────────────────────────────────────────
    # Monolith: user = ForeignKey(AUTH_USER_MODEL, on_delete=CASCADE)
    # Microservice: plain integer, unique=True enforces one cart per user
    # ──────────────────────────────────────────────────────────
    user_id = models.PositiveIntegerField(unique=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Cart(user_id={self.user_id})"

    @property
    def total_items(self):
        """Total number of distinct products in this cart."""
        return self.items.count()

    @property
    def total_price(self):
        """
        Sum of (price × quantity) for all items.

        Uses the SNAPSHOT price stored on CartItem — not the
        current live price from product-service.
        This is intentional: price is frozen when item is added.
        """
        return sum(item.total_price for item in self.items.all())


class CartItem(models.Model):
    """
    A single product line inside a cart.

    MICROSERVICE CHANGES vs monolith:

    1. product = ForeignKey(Product) → product_id = PositiveIntegerField()
       Product lives in product-service's DB. No FK possible.

    2. NEW: product_title = CharField()
       Snapshot of product name at time of adding.
       If product is deleted from product-service, we still
       know what was in the cart.

    3. NEW: price = DecimalField()
       Snapshot of product price at time of adding to cart.
       Monolith read product.price live — dangerous if price changes.
       We freeze the price at add time. Total is always predictable.

    4. total_price is now a property using snapshot price,
       not product.price from a ForeignKey.
    """

    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name="items",
    )

    # ── KEY CHANGE 1 ──────────────────────────────────────────
    # Monolith: product = ForeignKey(Product, on_delete=CASCADE)
    # Microservice: store only the product ID as a plain integer
    # ──────────────────────────────────────────────────────────
    product_id = models.PositiveIntegerField()

    # ── KEY CHANGE 2 ──────────────────────────────────────────
    # NEW FIELD: snapshot the product title at add time
    # Protects against product deletion from product-service
    # ──────────────────────────────────────────────────────────
    product_title = models.CharField(max_length=255, default="Unknown Product")

    # ── KEY CHANGE 3 ──────────────────────────────────────────
    # NEW FIELD: snapshot the price at add time
    # Monolith: total_price = self.product.price * self.quantity
    # Microservice: total_price = self.price * self.quantity
    # Price is FROZEN when item is added. Never changes after that.
    # ──────────────────────────────────────────────────────────
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # One entry per product per cart
        # Cannot add same product twice — we update quantity instead
        unique_together = ("cart", "product_id")
        ordering = ["added_at"]

    def __str__(self):
        return f"CartItem(product_id={self.product_id}, qty={self.quantity})"

    @property
    def total_price(self):
        """
        Line total = snapshot price × quantity.
        Uses self.price (frozen at add time), NOT live product price.
        """
        return self.price * self.quantity
