import logging
import sys

from django.apps import AppConfig
from django.db.utils import OperationalError, ProgrammingError

logger = logging.getLogger(__name__)


class CartConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cart"

    def ready(self):
        # Skip during management commands that shouldn't (or can't) touch
        # the DB yet — running a query against tables that don't exist
        # yet (fresh DB, pre-migrate) would crash startup for these.
        skip_commands = {"makemigrations", "migrate", "collectstatic", "shell"}
        if len(sys.argv) > 1 and sys.argv[1] in skip_commands:
            return

        self._reconcile_active_carts_gauge()

    def _reconcile_active_carts_gauge(self):
        """
        active_carts_gauge lives in prometheus_client's in-memory registry
        and resets to 0 on every process restart/redeploy. Without this,
        Prometheus would report 0 active carts right after a deploy even
        if dozens of real carts with items already exist in Postgres,
        until enough add/remove/clear traffic naturally rebuilds the count.

        We use .set(), not .inc() — set() is idempotent, so this stays
        correct even if ready() fires more than once (e.g. runserver's
        autoreloader invoking it twice on startup).
        """
        try:
            from cart.models import Cart
            from orders.metrics import active_carts_gauge

            count = Cart.objects.filter(items__isnull=False).distinct().count()
            active_carts_gauge.set(count)
            logger.info(f"active_carts_gauge reconciled on startup: {count}")
        except (OperationalError, ProgrammingError) as e:
            # DB not ready / table doesn't exist yet (e.g. fresh container
            # before first migrate). Safe to skip — gauge starts at 0 and
            # builds up correctly via normal add/remove/clear traffic.
            logger.warning(f"Could not reconcile active_carts_gauge on startup: {e}")
        except Exception as e:
            # A metrics reconciliation failure should never block app startup.
            logger.warning(f"Unexpected error reconciling active_carts_gauge: {e}")