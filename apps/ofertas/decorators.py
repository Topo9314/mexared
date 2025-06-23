# apps/ofertas/decorators.py

import logging
from functools import wraps
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

from apps.ofertas.permissions import (
    is_admin,
    is_distributor,
    is_vendor,
    is_client
)

logger = logging.getLogger(__name__)

def role_required(check_function, message=None):
    """
    Decorador robusto para validar roles con logs auditados.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            user = request.user
            if not check_function(user):
                error_message = message or _("No tienes permisos para acceder a este recurso.")
                logger.warning(
                    f"[SECURITY] Bloqueo de acceso: usuario '{user.username if user.is_authenticated else 'Anonymous'}' "
                    f"Fecha: {timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')} -> {error_message}"
                )
                raise PermissionDenied(error_message)
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator

# ✅ Decoradores ya armados para los roles
admin_required = role_required(is_admin, _("Solo administradores pueden acceder."))
distributor_required = role_required(is_distributor, _("Solo distribuidores pueden acceder."))
vendor_required = role_required(is_vendor, _("Solo vendedores pueden acceder."))
client_required = role_required(is_client, _("Solo clientes pueden acceder."))
