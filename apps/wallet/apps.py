from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.db import transaction, IntegrityError
from django.utils.translation import gettext_lazy as _
from django.apps import apps
import logging

logger = logging.getLogger(__name__)

class WalletConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.wallet'
    verbose_name = _("Sistema de Billeteras Financieras (Wallet Module)")

    def ready(self):
        post_migrate.connect(self.ensure_mxn_currency, sender=self)

    def ensure_mxn_currency(self, sender, **kwargs):
        """
        Garantiza que la moneda MXN exista después de cada migración.
        Implementación robusta, segura, atómica y auditada.
        """
        try:
            Moneda = apps.get_model('wallet', 'Moneda')
            if not Moneda:
                logger.critical("❌ No se pudo localizar el modelo Moneda en apps.wallet", exc_info=True)
                return

            with transaction.atomic():
                obj, created = Moneda.objects.get_or_create(
                    codigo="MXN",
                    defaults={'nombre': "Peso Mexicano"}
                )

            if created:
                logger.info("Moneda MXN creada automáticamente tras migración.")
            else:
                logger.info("Moneda MXN ya existe. Validación pasada correctamente.")

        except IntegrityError as e:
            logger.error(f"Error de integridad al crear la moneda MXN: {e}", exc_info=True)
        except Exception as e:
            logger.critical(f"Error inesperado al validar la moneda MXN: {e}", exc_info=True)
