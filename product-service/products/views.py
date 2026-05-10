from rest_framework import viewsets, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import Product
from .serializers import ProductSerializer
from .filters import ProductFilter


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

    def perform_create(self, serializer):
        """
        Called when POST /api/v1/products/ is received.
        Sets owner_id from the verified JWT token.
        Client cannot fake this — JWT is verified by simplejwt.
        """
        serializer.save(owner_id=self.request.user.id)

    def perform_destroy(self, instance):
        """
        Called when DELETE /api/v1/products/<id>/ is received.
        Overrides default hard delete with our soft delete.
        """
        instance.delete()  # calls our custom delete() on the model


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
        """Set owner_id from JWT token."""
        serializer.save(owner_id=self.request.user.id)
