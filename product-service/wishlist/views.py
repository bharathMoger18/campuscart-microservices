from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from .models import Wishlist, WishlistItem
from .serializers import WishlistSerializer
from products.models import Product

from products.metrics import wishlist_additions_total


class WishlistViewSet(viewsets.ViewSet):
    """
    Manages the current user's wishlist.
    All actions require JWT authentication.

    list:   GET  /api/v1/wishlist/        — get my wishlist
    add:    POST /api/v1/wishlist/add/    — add product to wishlist
    remove: POST /api/v1/wishlist/remove/ — remove product from wishlist
    clear:  POST /api/v1/wishlist/clear/  — clear entire wishlist
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_wishlist(self, user_id):
        """
        Get or create wishlist for this user.
        Called on every action — ensures wishlist always exists.
        user_id comes from JWT token, never from client.
        """
        wishlist, created = Wishlist.objects.get_or_create(
            user_id=user_id
        )
        return wishlist

    def list(self, request):
        """
        GET /api/v1/wishlist/
        Returns the current user's wishlist with all items.
        """
        wishlist = self.get_wishlist(request.user.id)
        serializer = WishlistSerializer(wishlist)
        return Response(serializer.data)

    @action(detail=False, methods=["post"])
    def add(self, request):
        """
        POST /api/v1/wishlist/add/
        Body: {"product_id": 5}
        Adds a product to the wishlist.
        """
        product_id = request.data.get("product_id")

        # Validate product_id was provided
        if not product_id:
            return Response(
                {"error": "product_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check product exists and is not soft-deleted
        product = Product.objects.filter(
            id=product_id,
            is_deleted=False
        ).first()

        if not product:
            return Response(
                {"error": "Product not found or no longer available"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get or create wishlist, then add product
        wishlist = self.get_wishlist(request.user.id)
        item, created = WishlistItem.objects.get_or_create(
            wishlist=wishlist,
            product=product
        )

        if created:
            message = "Product added to wishlist."
            # Only on a genuinely NEW addition — re-adding a product
            # already in the wishlist (created=False) is a no-op for the
            # user, so it shouldn't inflate the "future demand" signal
            # metrics.py documents this counter as ("Leading indicator for
            # future orders").
            wishlist_additions_total.labels(
                category=product.category or "uncategorized"
            ).inc()
        else:
            message = "Product already in wishlist."

        return Response(
            {
                "message": message,
                "wishlist": WishlistSerializer(wishlist).data,
            },
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=["post"])
    def remove(self, request):
        """
        POST /api/v1/wishlist/remove/
        Body: {"product_id": 5}
        Removes a product from the wishlist.
        """
        product_id = request.data.get("product_id")

        if not product_id:
            return Response(
                {"error": "product_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        wishlist = self.get_wishlist(request.user.id)
        deleted_count, _ = WishlistItem.objects.filter(
            wishlist=wishlist,
            product_id=product_id
        ).delete()

        if deleted_count == 0:
            return Response(
                {"error": "Product not found in wishlist"},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(
            {
                "message": "Product removed from wishlist.",
                "wishlist": WishlistSerializer(wishlist).data,
            },
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=["post"])
    def clear(self, request):
        """
        POST /api/v1/wishlist/clear/
        Removes all products from the wishlist.
        """
        wishlist = self.get_wishlist(request.user.id)
        wishlist.items.all().delete()
        return Response(
            {"message": "Wishlist cleared successfully."},
            status=status.HTTP_200_OK
        )