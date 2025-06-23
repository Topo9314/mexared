# apps/ofertas/permissions.py

from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _

# --- ROLE CONSTANTS (scalable for future module expansion)
ROLE_ADMIN = 'admin'
ROLE_DISTRIBUTOR = 'distribuidor'
ROLE_VENDOR = 'vendedor'
ROLE_CLIENT = 'cliente'

# --- PERMISSION CHECKERS (international role validation)
def is_admin(user):
    """Check if user is authenticated and has the admin role."""
    return user.is_authenticated and user.rol == ROLE_ADMIN

def is_distributor(user):
    """Check if user is authenticated and has the distributor role."""
    return user.is_authenticated and user.rol == ROLE_DISTRIBUTOR

def is_vendor(user):
    """Check if user is authenticated and has the vendor role."""
    return user.is_authenticated and user.rol == ROLE_VENDOR

def is_client(user):
    """Check if user is authenticated and has the client role."""
    return user.is_authenticated and user.rol == ROLE_CLIENT

# --- PERMISSION VALIDATORS (for use in views, services, or APIs)
def require_admin(user):
    """Raise PermissionDenied if user is not an admin."""
    if not is_admin(user):
        raise PermissionDenied(_("You must be an admin to perform this action."))

def require_distributor(user):
    """Raise PermissionDenied if user is not a distributor."""
    if not is_distributor(user):
        raise PermissionDenied(_("You must be a distributor to perform this action."))

def require_vendor(user):
    """Raise PermissionDenied if user is not a vendor."""
    if not is_vendor(user):
        raise PermissionDenied(_("You must be a vendor to perform this action."))

def require_client(user):
    """Raise PermissionDenied if user is not a client."""
    if not is_client(user):
        raise PermissionDenied(_("You must be a client to perform this action."))