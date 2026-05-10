# users/views.py
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_decode
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.hashers import make_password

from .serializers import RegisterSerializer, UserSerializer
from .utils import send_verification_email, send_password_reset_email

User = get_user_model()


# ---------------------------
# Registration & User Profile
# ---------------------------

class RegisterView(generics.CreateAPIView):
    """
    POST /api/v1/auth/register/
    Creates user as inactive, sends verification email.
    No authentication required.
    """
    queryset = User.objects.all()
    permission_classes = (permissions.AllowAny,)
    serializer_class = RegisterSerializer

    def perform_create(self, serializer):
        user = serializer.save(is_active=False)
        send_verification_email(user, self.request)
        return user


class MeView(APIView):
    """
    GET  /api/v1/users/me/ — returns authenticated user profile
    PUT  /api/v1/users/me/ — updates authenticated user profile
    Requires valid JWT token.
    """
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def put(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# ---------------------------
# Email Verification
# ---------------------------

class VerifyEmailView(APIView):
    """
    GET /api/v1/auth/verify/<uidb64>/<token>/
    Activates user account when clicking email link.
    Token auto-expires and invalidates after password change.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, uidb64, token):
        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)
        except (ObjectDoesNotExist, ValueError, TypeError, OverflowError):
            return Response(
                {"detail": "Invalid link."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if default_token_generator.check_token(user, token):
            user.is_active = True
            user.save(update_fields=["is_active"])
            return Response({"detail": "Email verified successfully!"})

        return Response(
            {"detail": "Invalid or expired token."},
            status=status.HTTP_400_BAD_REQUEST
        )


# ---------------------------
# Password Reset
# ---------------------------

class RequestPasswordResetView(APIView):
    """
    POST /api/v1/auth/password_reset/
    Sends reset email if account exists.
    Always returns same response (prevents user enumeration).
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get("email")
        try:
            user = User.objects.get(email=email)
            send_password_reset_email(user, request)
        except User.DoesNotExist:
            pass  # Intentional — do not reveal if email exists
        return Response(
            {"detail": "If your email exists, you'll receive a reset link."}
        )


class PasswordResetConfirmView(APIView):
    """
    POST /api/v1/auth/password_reset_confirm/<uidb64>/<token>/
    Validates token and sets new password.
    Token becomes invalid after use (password hash changes).
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, uidb64, token):
        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)
        except (ObjectDoesNotExist, ValueError, TypeError, OverflowError):
            return Response(
                {"detail": "Invalid link."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not default_token_generator.check_token(user, token):
            return Response(
                {"detail": "Invalid or expired token."},
                status=status.HTTP_400_BAD_REQUEST
            )

        new_password = request.data.get("password")
        if not new_password:
            return Response(
                {"detail": "Password required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.password = make_password(new_password)
        user.save(update_fields=["password"])
        return Response({"detail": "Password reset successful."})


# ---------------------------
# Internal — Called by other microservices
# ---------------------------

@api_view(["GET"])
@permission_classes([AllowAny])
def public_user_detail(request, user_id):
    """
    GET /api/v1/users/public/<user_id>/
    Returns minimal public user info.
    Called by product-service, order-service etc. — no auth required.
    """
    try:
        user = User.objects.get(id=user_id)
        return Response({
            "id": user.id,
            "name": user.name,
            "email": user.email,
        })
    except User.DoesNotExist:
        return Response(
            {"detail": "User not found"},
            status=status.HTTP_404_NOT_FOUND
        )
