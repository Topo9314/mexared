from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class VendedoresConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.vendedores'
    verbose_name = _("Gestión de Vendedores")
