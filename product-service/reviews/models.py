from django.db import models
from products.models import Product


class Review(models.Model):
    """A user's review and rating for a product."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="reviews"
    )

    # ── KEY CHANGE ──────────────────────────────────────────────────
    # Monolith: user = ForeignKey(settings.AUTH_USER_MODEL, ...)
    # Microservice: store only the user ID as a plain integer.
    # User lives in auth-service's database — no shared DB possible.
    user_id = models.PositiveIntegerField()
    # ────────────────────────────────────────────────────────────────

    rating = models.PositiveSmallIntegerField(default=1)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # One review per user per product — enforced at DB level
        unique_together = ("product", "user_id")
        ordering = ["-created_at"]

    def __str__(self):
        return f"User {self.user_id} → {self.product.title} ({self.rating}/5)"
