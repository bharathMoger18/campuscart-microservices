from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    """
    App configuration for the payments app.
    """
    default_auto_field = "django.db.models.BigAutoField"
    name = "payments"
