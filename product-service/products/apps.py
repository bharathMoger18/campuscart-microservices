import logging
import sys

from django.apps import AppConfig
from django.db.utils import OperationalError, ProgrammingError

logger = logging.getLogger(__name__)


class ProductsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products"

    def ready(self):
        skip_commands = {"makemigrations", "migrate", "collectstatic", "shell"}
        if len(sys.argv) > 1 and sys.argv[1] in skip_commands:
            return

        self._reconcile_active_products_gauge()

    def _reconcile_active_products_gauge(self):
        """
        Same problem as active_carts_gauge in the order-service: this is an
        in-memory prometheus_client Gauge that resets to 0 on every process
        restart/redeploy. Without this, Prometheus reports 0 active
        listings right after a deploy even with a full catalog already
        sitting in Postgres, until enough create/delete traffic rebuilds it.
        """
        try:
            from products.models import Product
            from products.metrics import active_products_gauge

            count = Product.objects.filter(is_deleted=False).count()
            active_products_gauge.set(count)
            logger.info(f"active_products_gauge reconciled on startup: {count}")
        except (OperationalError, ProgrammingError) as e:
            logger.warning(f"Could not reconcile active_products_gauge on startup: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error reconciling active_products_gauge: {e}")