import django_filters
from .models import Product


class ProductFilter(django_filters.FilterSet):
    # Filter by minimum price: ?min_price=100
    min_price = django_filters.NumberFilter(
        field_name="price", lookup_expr="gte"
    )
    # Filter by maximum price: ?max_price=500
    max_price = django_filters.NumberFilter(
        field_name="price", lookup_expr="lte"
    )
    # Filter by category (case insensitive): ?category=books
    category = django_filters.CharFilter(
        field_name="category", lookup_expr="iexact"
    )
    # Filter by availability: ?is_available=true
    is_available = django_filters.BooleanFilter(
        field_name="is_available"
    )

    class Meta:
        model = Product
        fields = ["category", "is_available", "min_price", "max_price"]
