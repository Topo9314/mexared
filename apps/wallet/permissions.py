"""
Módulo de permisos financieros avanzados para el módulo Wallet de MexaRed.
Centraliza el control de acceso a operaciones financieras, garantizando granularidad, auditoría y cumplimiento.
Diseñado para entornos SaaS multinivel, compatible con PCI DSS Level 1, SOC2 Type 2, ISO 27001, y SAT.
"""

import logging
from django.utils.translation import gettext_lazy as _
from apps.users.models import User, ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR, ROLE_CLIENTE
from apps.wallet.exceptions import OperacionNoPermitidaException

# Configuración de logging para auditoría en producción
logger = logging.getLogger(__name__)

# Matriz de permisos que define roles autorizados por operación
PERMISSIONS_MATRIX = {
    "wallet.creditar": [ROLE_ADMIN],
    "wallet.debitar": [ROLE_ADMIN],
    "wallet.transferir": [ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR],
    "wallet.bloquear": [ROLE_ADMIN],
    "wallet.desbloquear": [ROLE_ADMIN],
    "wallet.ajuste_manual": [ROLE_ADMIN],
    "wallet.conciliar": [ROLE_ADMIN, ROLE_DISTRIBUIDOR],
    "wallet.ver_dashboard": [ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR],
    "wallet.exportar_movimientos": [ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR],
}

def has_permission(user: User, permission: str) -> bool:
    """
    Verifica si un usuario tiene el permiso especificado según su rol.

    Args:
        user: Instancia del usuario que realiza la operación.
        permission: Permiso solicitado (e.g., 'wallet.creditar').

    Returns:
        bool: True si el usuario tiene el permiso, False en caso contrario.

    Behavior:
        - Devuelve True si el usuario es superusuario.
        - Consulta PERMISSIONS_MATRIX para verificar si el rol del usuario está autorizado.
        - Registra el intento de acceso en logs para auditoría.
    """
    if not user.is_authenticated:
        logger.warning(f"Intento de acceso anónimo al permiso {permission}")
        return False

    if user.is_superuser:
        logger.debug(f"Permiso {permission} concedido a superusuario {user.username}")
        return True

    allowed_roles = PERMISSIONS_MATRIX.get(permission, [])
    has_perm = user.rol in allowed_roles

    if has_perm:
        logger.debug(f"Permiso {permission} concedido a {user.username} (rol: {user.rol})")
    else:
        logger.warning(f"Permiso {permission} denegado a {user.username} (rol: {user.rol})")

    return has_perm

def raise_if_not_allowed(user: User, permission: str) -> None:
    """
    Valida que el usuario tenga el permiso especificado, lanzando una excepción si no está autorizado.

    Args:
        user: Instancia del usuario que realiza la operación.
        permission: Permiso solicitado (e.g., 'wallet.creditar').

    Raises:
        OperacionNoPermitidaException: Si el usuario no tiene el permiso.
    """
    if not has_permission(user, permission):
        error_msg = _("No tienes permiso para realizar esta operación: %(permission)s.") % {'permission': permission}
        raise OperacionNoPermitidaException(error_msg)