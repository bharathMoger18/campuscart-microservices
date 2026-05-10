"""
MicroserviceJWTAuthentication
─────────────────────────────
Custom JWT authentication for notification-service.

WHY THIS EXISTS:
  Standard JWTAuthentication (from simplejwt) does:
    1. Validate the JWT token        ← works fine
    2. Extract user_id from token    ← works fine
    3. User.objects.get(id=user_id)  ← CRASHES: no users table here!

  We have no users table. Users live in auth-service's database.
  This class skips step 3 and builds an in-memory user object instead.

CRITICAL FIX (learned from Soldier 2):
  JWT payload stores user_id as STRING "1", not integer 1.
  Any comparison like: obj.owner_id == request.user.id
  becomes: 1 == "1" → False → 403 Forbidden
  Fix: always int(user_id) when building MicroserviceUser.
"""

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework.exceptions import AuthenticationFailed


class MicroserviceUser:
    """
    Lightweight in-memory user object.
    Looks like a Django User to DRF — no database required.
    """

    def __init__(self, user_id: int):
        # CRITICAL: int() conversion — JWT stores user_id as string "1"
        self.id = int(user_id)
        self.pk = int(user_id)       # pk is Django's alias for id
        self.is_active = True
        self.is_anonymous = False
        self.is_authenticated = True  # DRF checks this for IsAuthenticated

    def __str__(self):
        return f"MicroserviceUser(id={self.id})"


class MicroserviceJWTAuthentication(JWTAuthentication):
    """
    Overrides get_user() to return MicroserviceUser instead of
    querying the database (which would crash — no users table here).

    How it works:
      1. JWTAuthentication.authenticate() validates the token     ← inherited
      2. JWTAuthentication calls self.get_user(validated_token)   ← we override this
      3. We extract user_id and return MicroserviceUser(user_id)  ← no DB call
    """

    def get_user(self, validated_token):
        """
        Extract user_id from the validated JWT payload and return
        a MicroserviceUser. No database lookup.
        """
        try:
            # JWT payload has "user_id" claim set by auth-service
            user_id = validated_token["user_id"]
        except KeyError:
            raise InvalidToken("Token contained no recognisable user identification")

        if not user_id:
            raise AuthenticationFailed("user_id claim is empty in token")

        return MicroserviceUser(user_id)
