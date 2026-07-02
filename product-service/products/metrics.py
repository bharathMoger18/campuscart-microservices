from prometheus_client import Counter, Histogram, Gauge

# ═══════════════════════════════════════════════════════════════
# PRODUCT CATALOG METRICS
# ═══════════════════════════════════════════════════════════════

# Product views — which products are being looked at
product_views_total = Counter(
    name="product_views_total",
    documentation="Total product detail page views",
    labelnames=["category"],    # "textbooks", "electronics", "clothing", "stationery"
    # Bounded cardinality — you define the categories
    # DO NOT use product_id as a label — unbounded cardinality
)
# PromQL: rate(product_views_total{category="textbooks"}[5m])
# Use for: "which category is trending right now?"

# Product listings (searches + filter results)
product_searches_total = Counter(
    name="product_searches_total",
    documentation="Total product search/filter queries",
    labelnames=["has_results"],  # "true" or "false"
    # Alert when has_results="false" rate spikes — catalog gap or search bug
)

search_duration_seconds = Histogram(
    name="product_search_duration_seconds",
    documentation="Duration of product search/filter operations in seconds",
    labelnames=["filter_type"],  # "category", "price_range", "keyword", "combined"
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0],
    # SLO: p99 search < 500ms. Alert when p99 > 1s.
)

# Product listings created by sellers
products_listed_total = Counter(
    name="product_listed_total",
    documentation="Total new products listed by sellers",
    labelnames=["category", "status"],
    # status: "active", "pending_review", "rejected"
)

# ═══════════════════════════════════════════════════════════════
# IMAGE UPLOAD METRICS (Pillow)
# ═══════════════════════════════════════════════════════════════

# Image upload attempts — includes resize, compression, format conversion
image_uploads_total = Counter(
    name="product_image_uploads_total",
    documentation="Total product image upload attempts",
    labelnames=["status"],       # "success", "failure", "too_large", "invalid_format"
)

image_upload_duration_seconds = Histogram(
    name="product_image_upload_duration_seconds",
    documentation="Duration of image upload and processing (Pillow) in seconds",
    labelnames=[],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
    # Image processing can be slow — Pillow resizing a 10MB image takes 2-3s
    # Alert when p99 > 5s — likely a very large image or CPU pressure
)

image_upload_size_bytes = Histogram(
    name="product_image_upload_size_bytes",
    documentation="Size of uploaded product images before processing",
    labelnames=[],
    buckets=[
        10_000,      # 10KB
        100_000,     # 100KB
        500_000,     # 500KB
        1_000_000,   # 1MB
        5_000_000,   # 5MB
        10_000_000,  # 10MB
    ],
    # Useful for capacity planning: what's the typical image size?
    # If p99 > 5MB, your Pillow processing will be slow — consider adding a CDN
)

# ═══════════════════════════════════════════════════════════════
# WISHLIST AND REVIEW METRICS
# ═══════════════════════════════════════════════════════════════

wishlist_additions_total = Counter(
    name="product_wishlist_additions_total",
    documentation="Total products added to wishlists",
    labelnames=["category"],
    # Leading indicator for future orders — high wishlist additions → future demand
)

reviews_submitted_total = Counter(
    name="product_reviews_submitted_total",
    documentation="Total product reviews submitted",
    labelnames=["rating"],  # "1", "2", "3", "4", "5"
    # Distribution of ratings tells you product quality trends
    # Alert: if rating "1" rate suddenly spikes — batch of bad products
)

# Current active products in catalog (gauge for capacity planning)
active_products_gauge = Gauge(
    name="product_active_listings_current",
    documentation="Current number of active product listings in catalog",
)