import time
from rest_framework import viewsets, permissions, filters
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import Product
from .serializers import ProductSerializer
from .filters import ProductFilter

from products.metrics import (
    product_views_total,
    product_searches_total,
    search_duration_seconds,
    products_listed_total,
    active_products_gauge,
)


def _determine_filter_type(query_params):
    """
    Maps the query params on an incoming list() request to one of the
    filter_type label values: "category", "price_range", "keyword",
    "availability", "combined". Returns None if no recognized filter param
    is present (a plain unfiltered browse).

    Confirmed against the real ProductFilter (filters.py):
      - category      -> CharFilter(field_name="category", lookup_expr="iexact")
      - min_price/max_price -> NumberFilter(field_name="price", lookup_expr in {"gte","lte"})
      - is_available  -> BooleanFilter(field_name="is_available")
    "keyword" still assumes DRF's SearchFilter default param name "search",
    confirmed by search_fields=[...] on both viewsets below.

    "availability" bucket added 2026-06-30: ProductFilter.Meta.fields lists
    is_available as a real, distinct filter, but metrics.py's filter_type
    labelnames comment only documented category/price_range/keyword/combined.
    Without this, a request filtered only by ?is_available=true matched none
    of the checks below and silently skipped search_duration_seconds
    entirely. Added "availability" as a fifth label value here, with a
    matching comment update in metrics.py.
    """
    has_category = "category" in query_params
    has_price = any("price" in key.lower() for key in query_params)
    has_keyword = "search" in query_params
    has_availability = "is_available" in query_params

    matched = [name for name, present in [
        ("category", has_category),
        ("price_range", has_price),
        ("keyword", has_keyword),
        ("availability", has_availability),
    ] if present]

    if len(matched) >= 2:
        return "combined"
    if len(matched) == 1:
        return matched[0]
    return None


def _record_product_listed(instance):
    """
    Shared by ProductViewSet.perform_create and SellerProductViewSet.perform_create
    — both are live POST paths that create a product.

    status="active": no moderation/review workflow exists on Product (no
    pending/approved state, no review queue), so a product is live the
    instant it's created. metrics.py's labelnames comment lists
    "pending_review"/"rejected" as options, but no code path here ever
    produces those, so hardcoding "active" reflects current behavior.

    category fallback removed: Product.category is CharField(choices=...,
    default="Other"), never null/blank for an instance that passed through
    ProductSerializer validation, so instance.category is always one of the
    five real choices here.
    """
    products_listed_total.labels(
        category=instance.category,
        status="active",
    ).inc()
    active_products_gauge.inc()


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Custom permission:
    - Anyone can READ (GET) products
    - Only the owner can UPDATE or DELETE their product
    """
    def has_object_permission(self, request, view, obj):
        # SAFE_METHODS = GET, HEAD, OPTIONS — always allowed
        if request.method in permissions.SAFE_METHODS:
            return True
        # Write methods: only allowed if the requester owns this product
        return obj.owner_id == request.user.id


class ProductViewSet(viewsets.ModelViewSet):
    """
    Full CRUD for products.

    list:   GET  /api/v1/products/         — public
    create: POST /api/v1/products/         — JWT required
    retrieve: GET /api/v1/products/<id>/   — public
    update: PUT  /api/v1/products/<id>/    — JWT + owner only
    destroy: DELETE /api/v1/products/<id>/ — JWT + owner only
    """
    # Base queryset: exclude soft-deleted products, newest first
    queryset = Product.objects.filter(is_deleted=False).order_by("-created_at")
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly]

    # Filtering, searching, ordering
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ProductFilter
    search_fields = ["title", "description", "category"]
    ordering_fields = ["price", "created_at"]

    def list(self, request, *args, **kwargs):
        """
        GET /api/v1/products/
        Public catalog browse + search/filter. Wires product_searches_total
        and search_duration_seconds.

        product_searches_total fires on EVERY call here, filtered or not —
        an unfiltered "browse all" returning zero results is just as
        meaningful a signal (empty catalog) as a filtered search returning
        zero.

        search_duration_seconds + filter_type only fires when an actual
        filter/search param was present.

        Only wired here, not on SellerProductViewSet.list() below — that
        endpoint is a seller managing their own inventory, not a customer
        discovering the catalog, and mixing the two would muddy
        product_searches_total's documented purpose ("catalog gap or
        search bug" — i.e. customer-facing discovery).
        """
        filter_type = _determine_filter_type(request.query_params)
        start = time.monotonic() if filter_type is not None else None

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            has_results = len(page) > 0
            response = self.get_paginated_response(serializer.data)
        else:
            serializer = self.get_serializer(queryset, many=True)
            has_results = len(serializer.data) > 0
            response = Response(serializer.data)

        product_searches_total.labels(has_results=str(has_results).lower()).inc()

        if filter_type is not None:
            search_duration_seconds.labels(filter_type=filter_type).observe(
                time.monotonic() - start
            )

        return response

    def retrieve(self, request, *args, **kwargs):
        """
        GET /api/v1/products/<id>/
        Public product detail view. Tracks product_views_total by category
        — "which category is trending right now" per metrics.py.

        No fallback needed on category — see _record_product_listed comment.
        """
        instance = self.get_object()
        product_views_total.labels(category=instance.category).inc()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def perform_create(self, serializer):
        """
        Called when POST /api/v1/products/ is received.
        Sets owner_id from the verified JWT token.
        Client cannot fake this — JWT is verified by simplejwt.
        """
        instance = serializer.save(owner_id=self.request.user.id)
        _record_product_listed(instance)

    def perform_destroy(self, instance):
        """
        Called when DELETE /api/v1/products/<id>/ is received.
        Overrides default hard delete with our soft delete.
        """
        instance.delete()  # calls our custom delete() on the model
        active_products_gauge.dec()


class SellerProductViewSet(viewsets.ModelViewSet):
    """
    Products belonging to the currently logged-in seller only.

    list:   GET  /api/v1/seller/products/  — JWT required
    create: POST /api/v1/seller/products/  — JWT required
    """
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ProductFilter
    search_fields = ["title", "description", "category"]
    ordering_fields = ["price", "created_at"]

    def get_queryset(self):
        """
        Only return products owned by the logged-in seller.
        request.user.id comes from the verified JWT token.
        """
        return Product.objects.filter(
            owner_id=self.request.user.id,
            is_deleted=False
        ).order_by("-created_at")

    def perform_create(self, serializer):
        """
        Set owner_id from JWT token.

        Shares _record_product_listed with ProductViewSet.perform_create
        above — both are real creation paths, so both need the metric.
        """
        instance = serializer.save(owner_id=self.request.user.id)
        _record_product_listed(instance)

    def perform_destroy(self, instance):
        """
        Routes deletes through this viewset to also decrement
        active_products_gauge. DRF's default perform_destroy already
        calls instance.delete() (soft-delete happens regardless), this
        override just makes sure the gauge moves too.
        """
        instance.delete()
        active_products_gauge.dec()