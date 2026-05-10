from django.db import models


class Product(models.Model):
    CATEGORY_CHOICES = [
        ("Books", "Books"),
        ("Electronics", "Electronics"),
        ("Clothing", "Clothing"),
        ("Accessories", "Accessories"),
        ("Other", "Other"),
    ]

    # ── KEY CHANGE ──────────────────────────────────────────────────
    # Monolith: owner = ForeignKey(settings.AUTH_USER_MODEL, ...)
    # Microservice: store only the ID as a plain integer.
    # User lives in auth-service's database. We cannot do a SQL JOIN
    # across two separate databases. When we need user details, we
    # call auth-service's HTTP API instead.
    owner_id = models.PositiveIntegerField()
    # ────────────────────────────────────────────────────────────────

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    category = models.CharField(
        max_length=50, choices=CATEGORY_CHOICES, default="Other"
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to="product_images/", blank=True, null=True)
    is_available = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def delete(self, *args, **kwargs):
        """Soft delete: mark unavailable instead of removing from DB."""
        from django.utils import timezone
        self.is_available = False
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save()

    @property
    def average_rating(self):
        """Calculate average rating from all reviews."""
        reviews = self.reviews.all()
        if not reviews.exists():
            return 0
        return round(sum(r.rating for r in reviews) / reviews.count(), 1)

    @property
    def total_reviews(self):
        """Total number of reviews for this product."""
        return self.reviews.count()

    def rating_breakdown(self):
        """Return {star: count} for stars 5 down to 1."""
        from collections import Counter
        ratings = list(self.reviews.values_list("rating", flat=True))
        counts = Counter(ratings)
        return {str(i): counts.get(i, 0) for i in range(5, 0, -1)}
