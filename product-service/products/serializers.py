import time
import httpx
from PIL import Image, UnidentifiedImageError
from django.conf import settings
from rest_framework import serializers
from .models import Product

from products.metrics import (
    image_uploads_total,
    image_upload_duration_seconds,
    image_upload_size_bytes,
)

# Picked these since nothing in the codebase specified them anywhere —
# confirm/correct and I'll adjust both the values and the comments below.
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB — matches the top bucket in
                                          # metrics.py's image_upload_size_bytes


def get_user_info(user_id: int) -> dict:
    """
    Fetch user details from auth-service.
    Returns dict with id, name, email or fallback if call fails.

    This is synchronous inter-service communication.
    Called only when we need to display owner info in the response.
    """
    try:
        response = httpx.get(
            f"{settings.AUTH_SERVICE_URL}/api/v1/users/public/{user_id}/",
            timeout=3.0,  # Don't wait more than 3 seconds
        )
        if response.status_code == 200:
            return response.json()
    except httpx.RequestError:
        # Auth-service is down or unreachable — fail gracefully
        pass

    # Fallback: return minimal info so product API still works
    return {"id": user_id, "name": "Unknown", "email": ""}


class ProductImageField(serializers.ImageField):
    """
    Single field that does double duty as both the write input (accepts
    an uploaded file under the key "image") and the read output (returns
    a "/media/..." URL string under that same key "image").

    WHY: the original SerializerMethodField version of "image" could only
    output the URL — DRF treats SerializerMethodField as implicitly
    read-only, so any image a client sent under "image" was silently
    discarded before it ever reached the model. A first pass at fixing
    this split the field into image (read) + image_upload (write), which
    works but changes the API contract — clients would've had to start
    sending the upload under a new key. This version keeps the wire
    format identical to before: same key, now actually writable.
    """
    def to_representation(self, value):
        if not value:
            return None
        return "/media/" + str(value)


class ProductSerializer(serializers.ModelSerializer):
    # Read-only fields that come from auth-service
    owner_name = serializers.SerializerMethodField()
    owner_email = serializers.SerializerMethodField()

    # Read-only computed fields from model properties
    average_rating = serializers.FloatField(read_only=True)
    total_reviews = serializers.IntegerField(read_only=True)
    rating_breakdown = serializers.SerializerMethodField()

    # Reviews nested inside product detail
    reviews = serializers.SerializerMethodField()

    # Image: read (URL string) and write (file upload) through one field.
    # required=False/allow_null=True since Product.image is blank=True,
    # null=True — listing without a photo is allowed.
    image = ProductImageField(required=False, allow_null=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "owner_id",
            "owner_name",
            "owner_email",
            "title",
            "description",
            "category",
            "price",
            "image",
            "is_available",
            "average_rating",
            "total_reviews",
            "rating_breakdown",
            "reviews",
            "created_at",
            "updated_at",
        ]
        # owner_id is set from JWT in the view, not from request body
        read_only_fields = ["owner_id", "created_at", "updated_at"]

    def get_owner_name(self, obj):
        """Fetch owner name from auth-service."""
        user_info = get_user_info(obj.owner_id)
        return user_info.get("name", "Unknown")

    def get_owner_email(self, obj):
        """Fetch owner email from auth-service."""
        user_info = get_user_info(obj.owner_id)
        return user_info.get("email", "")

    def validate_image(self, value):
        """
        Pillow-based validation for incoming product images. Wires the
        three image_* metrics defined in metrics.py — image_uploads_total,
        image_upload_duration_seconds, image_upload_size_bytes.

        Only runs when a new file is actually present in the request
        (value is None on a PUT that doesn't touch the image — DRF skips
        calling validate_<field> for fields absent from partial/unchanged
        input only if required=False and not supplied; if the client
        sends image=null explicitly this still runs with value=None, so
        the guard below covers both).

        Note: this fires on BOTH create (POST) and update (PUT/PATCH) —
        unlike products_listed_total, this is intentional. An image
        upload is a real, metered event (Pillow work, storage, bandwidth)
        any time it happens, not just at product-creation time. This
        does NOT conflict with the perform_update decision in views.py —
        that decision was specifically about products_listed_total
        ("new products"), not about image upload activity.

        ASSUMPTIONS (none of this was specified anywhere I've seen):
          - Max size 10MB, rejected outright rather than resized down,
            since this service has no async/background processing — a
            synchronous Pillow resize inside the request cycle risks
            exactly the slow-request problem metrics.py's own comment
            warns about ("Pillow resizing a 10MB image takes 2-3s").
          - Allowed formats: JPEG, PNG, WEBP. Picked as the common
            web-safe set; widen/narrow as needed.
          - No resize/recompression happens here — Image.open()+.verify()
            only confirms the upload is a genuine, parseable image of an
            allowed format (not corrupted data or a disguised non-image
            file). Real resizing (capping max dimensions for storage/
            bandwidth) would be a separate follow-up.
          - DRF's built-in ImageField already runs Django's own image
            validators during to_internal_value, before this method is
            even called — a sufficiently malformed upload can get
            rejected there instead of here, in which case this method
            (and its metrics) never run for that request. That's a
            pre-existing DRF behavior, not something this validator
            controls.
        """
        if value is None:
            return value

        start = time.monotonic()
        size_bytes = value.size

        if size_bytes > MAX_IMAGE_SIZE_BYTES:
            image_uploads_total.labels(status="too_large").inc()
            raise serializers.ValidationError(
                f"Image must be smaller than {MAX_IMAGE_SIZE_BYTES // (1024 * 1024)}MB."
            )

        try:
            value.seek(0)
            img = Image.open(value)
            img.verify()  # raises if the data isn't a genuine image
            image_format = img.format
        except (UnidentifiedImageError, OSError):
            image_uploads_total.labels(status="invalid_format").inc()
            raise serializers.ValidationError("Upload is not a valid image file.")
        except Exception:
            # Genuinely unexpected — distinct from a known-bad upload,
            # matches the "failure" status value in metrics.py's comment.
            image_uploads_total.labels(status="failure").inc()
            raise
        finally:
            # Reset the pointer so Django's storage backend can still
            # read and save the file after Pillow consumed it above.
            value.seek(0)

        if image_format not in ALLOWED_IMAGE_FORMATS:
            image_uploads_total.labels(status="invalid_format").inc()
            raise serializers.ValidationError(
                f"Unsupported image format: {image_format}. "
                f"Allowed: {', '.join(sorted(ALLOWED_IMAGE_FORMATS))}."
            )

        image_upload_size_bytes.observe(size_bytes)
        image_upload_duration_seconds.observe(time.monotonic() - start)
        image_uploads_total.labels(status="success").inc()

        return value

    def get_rating_breakdown(self, obj):
        """Return star rating breakdown."""
        return obj.rating_breakdown()

    def get_reviews(self, obj):
        """Return reviews only on product detail, not list view."""
        from reviews.serializers import ReviewSerializer
        # Only include reviews when retrieving a single product
        request = self.context.get("request")
        if request and hasattr(request, "parser_context"):
            kwargs = request.parser_context.get("kwargs", {})
            if "pk" in kwargs:
                reviews = obj.reviews.all()
                return ReviewSerializer(reviews, many=True, context=self.context).data
        return []