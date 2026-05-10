from django.db import models
from products.models import Product


class Wishlist(models.Model):
    """
    One wishlist per user.
    Created automatically when user first adds a product.
    """

    # ── KEY CHANGE ──────────────────────────────────────────────────
    # Monolith: user = OneToOneField(AUTH_USER_MODEL, ...)
    # Microservice: store only the user ID as a plain integer.
    # unique=True enforces one wishlist per user at DB level —
    # same guarantee as OneToOneField but without the FK constraint.
    user_id = models.PositiveIntegerField(unique=True)
    # ────────────────────────────────────────────────────────────────

    products = models.ManyToManyField(
        Product,
        related_name="wishlisted_by",
        through="WishlistItem"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Wishlist of user {self.user_id}"


class WishlistItem(models.Model):
    """
    Individual item in a wishlist.
    Through model for the Wishlist ↔ Product ManyToMany.
    """
    wishlist = models.ForeignKey(
        Wishlist,
        on_delete=models.CASCADE,
        related_name="items"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # One product can only appear once in a wishlist
        unique_together = ("wishlist", "product")

    def __str__(self):
        return f"{self.product.title} in wishlist {self.wishlist.id}"
