from django.apps import AppConfig


class CartConfig(AppConfig):
    """
    App configuration for the cart app.
    default_auto_field: all models in this app get BigAutoField
    as primary key by default (64-bit integer).
    name: must match exactly the app folder name.
    """
    default_auto_field = "django.db.models.BigAutoField"
    name = "cart"
