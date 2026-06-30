# users/urls.py
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    RegisterView,
    MeView,
    LoginView,
    VerifyEmailView,
    RequestPasswordResetView,
    PasswordResetConfirmView,
    public_user_detail,
)

urlpatterns = [
    # Auth endpoints
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/token/", LoginView.as_view(), name="token_obtain_pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # Email verification
    path("auth/verify/<uidb64>/<token>/", VerifyEmailView.as_view(), name="verify-email"),

    # Password reset
    path("auth/password_reset/", RequestPasswordResetView.as_view(), name="password-reset"),
    path("auth/password_reset_confirm/<uidb64>/<token>/", PasswordResetConfirmView.as_view(), name="password-reset-confirm"),

    # User profile
    path("users/me/", MeView.as_view(), name="me"),

    # Internal — called by other microservices
    path("users/public/<int:user_id>/", public_user_detail, name="public_user_detail"),
]