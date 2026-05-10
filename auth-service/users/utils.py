# users/utils.py
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.core.mail import send_mail
from django.conf import settings


def send_verification_email(user, request):
    """
    Generates a one-time email verification link and sends it to the user.
    Token is cryptographically tied to user state — auto-invalidates on password change.
    """
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    verify_url = (
        f"{request.scheme}://{request.get_host()}"
        f"/api/v1/auth/verify/{uid}/{token}/"
    )
    subject = "Verify your email"
    message = (
        f"Hi {user.name or user.email},\n\n"
        f"Click the link below to verify your email:\n{verify_url}\n\n"
        f"Thank you!"
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email])


def send_password_reset_email(user, request):
    """
    Generates a one-time password reset link and sends it to the user.
    Token auto-invalidates after use (password changes) or after timeout.
    """
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    reset_url = (
        f"{request.scheme}://{request.get_host()}"
        f"/api/v1/auth/password_reset_confirm/{uid}/{token}/"
    )
    subject = "Reset your password"
    message = (
        f"Hi {user.name or user.email},\n\n"
        f"Click below to reset your password:\n{reset_url}\n\n"
        f"Thank you!"
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email])
