# apps/ofertas/permissions.py

from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _

# --- ROLES (COINCIDENTES CON LOS QUE YA USAMOS EN USERS)
ROLE_ADMIN = 'admin'
ROLE_DISTRIBUTOR = 'distribuidor'
ROLE_VENDOR = 'vendedor'
ROLE_CLIENT = 'cliente'

# --- CHECKERS
def is_admin(user):
    return user.is_authenticated and user.rol == ROLE_ADMIN

def is_distributor(user):
    return user.is_authenticated and user.rol == ROLE_DISTRIBUTOR

def is_vendor(user):
    return user.is_authenticated and user.rol == ROLE_VENDOR

def is_client(user):
    return user.is_authenticated and user.rol == ROLE_CLIENT

# --- VALIDADORES OPCIONALES PARA USO EN SERVICES (si lo deseas)
def require_admin(user):
    if not is_admin(user):
        raise PermissionDenied(_("Solo los administradores pueden realizar esta acción."))

def require_distributor(user):
    if not is_distributor(user):
        raise PermissionDenied(_("Solo los distribuidores pueden realizar esta acción."))

def require_vendor(user):
    if not is_vendor(user):
        raise PermissionDenied(_("Solo los vendedores pueden realizar esta acción."))

def require_client(user):
    if not is_client(user):
        raise PermissionDenied(_("Solo los clientes pueden realizar esta acción."))
