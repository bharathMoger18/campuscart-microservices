from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken


class JWTUser:
    """
    A lightweight user object populated from JWT claims.
    Does NOT query the database — user data comes from the token itself.
    This is the correct microservices pattern:
    - auth-service owns the User model and database
    - product-service trusts the JWT claims
    """
    def __init__(self, user_id):
        # Convert to int — JWT stores user_id as string "1" not integer 1
        # Without this: obj.owner_id == request.user.id becomes 1 == "1" → False → 403
        self.id = int(user_id)
        self.pk = int(user_id)
        self.is_authenticated = True
        self.is_active = True
        self.is_anonymous = False

    def __str__(self):
        return f"JWTUser(id={self.id})"


class MicroserviceJWTAuthentication(JWTAuthentication):
    """
    Custom JWT authentication for microservices.

    Standard JWTAuthentication fetches the user from the local database
    after verifying the token. This fails in product-service because
    we have no users table.

    This class overrides get_user() to return a lightweight JWTUser
    object built from JWT claims — no database lookup needed.
    """

    def get_user(self, validated_token):
        """
        Return a JWTUser built from token claims.
        No database query — just read user_id from the token payload.
        user_id comes as string from JWT — convert to int for comparison.
        """
        try:
            user_id = validated_token["user_id"]
        except KeyError:
            raise InvalidToken("Token contained no recognizable user identification")

        return JWTUser(user_id=user_id)
