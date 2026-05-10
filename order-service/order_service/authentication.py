from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework.exceptions import AuthenticationFailed


class MicroserviceUser:
    """
    A lightweight user object built from JWT token payload.

    WHY THIS EXISTS:
    order-service has no users table. Standard Django user objects
    require a database lookup (User.objects.get(id=...)). We cannot
    do that lookup because the users table lives in auth-service's
    separate database.

    This object mimics just enough of Django's User interface to
    satisfy DRF's permission checks and our own view logic.
    """

    def __init__(self, payload: dict):
        # ── CRITICAL: int() conversion ────────────────────────────────────
        # JWT payload stores user_id as a STRING e.g. {"user_id": "42"}
        # Our models store user_id as PositiveIntegerField (integer)
        # Without int() conversion:
        #   Cart.objects.filter(user_id="42") → type mismatch → wrong results
        # With int() conversion:
        #   Cart.objects.filter(user_id=42)   → correct
        # ──────────────────────────────────────────────────────────────────
        self.id = int(payload.get("user_id", 0))
        self.email = payload.get("email", "")
        self.name = payload.get("name", "")

        # These attributes are required by DRF's permission system
        self.is_authenticated = True
        self.is_active = True
        self.is_staff = payload.get("is_staff", False)
        self.is_superuser = payload.get("is_superuser", False)

        # Store full payload for any extra claims we might need
        self._payload = payload

    def __str__(self):
        return f"MicroserviceUser(id={self.id}, email={self.email})"


class MicroserviceJWTAuthentication(JWTAuthentication):
    """
    Custom JWT authentication for microservices.

    OVERRIDES get_user() to skip database lookup.
    Builds MicroserviceUser directly from token payload.

    KEY FIX:
    simplejwt's validated_token is a Token object.
    We must access claims directly via token[key] syntax,
    not by converting to dict — some claims are stored
    internally and may not appear in dict() conversion.
    """

    def get_user(self, validated_token):
        """
        Build a MicroserviceUser from the validated token payload.
        No database access. No User.objects.get(). Pure in-memory.
        """
        try:
            # ── KEY FIX ───────────────────────────────────────────────────
            # Access token claims directly using [] syntax on the token object
            # simplejwt Token objects support dict-like access
            # validated_token["user_id"] reads the claim directly
            # This is more reliable than dict(validated_token)
            # ──────────────────────────────────────────────────────────────
            user_id = validated_token["user_id"]

            if not user_id:
                raise AuthenticationFailed("Token has no user_id claim")

            # Build payload dict for MicroserviceUser
            payload = {
                "user_id": user_id,
                "email": validated_token.get("email", ""),
                "name": validated_token.get("name", ""),
                "is_staff": validated_token.get("is_staff", False),
                "is_superuser": validated_token.get("is_superuser", False),
            }

            return MicroserviceUser(payload)

        except KeyError:
            raise AuthenticationFailed("Token has no user_id claim")
        except (ValueError, TypeError) as e:
            raise AuthenticationFailed(f"Invalid token payload: {e}")
