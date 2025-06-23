"""
Routing utility functions for MexaRed.
Handles user-based dashboard redirection and internal route mapping with robust, secure, and scalable URL resolution.
"""

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

def get_dashboard_url_for_user(user):
    """
    Returns the appropriate dashboard URL based on the user's role.

    Args:
        user (User): Instance of the User model.

    Returns:
        str: URL for redirection based on the user's role.

    Raises:
        ValueError: If the user object is None or invalid.
    """
    if not user or not hasattr(user, 'rol'):
        return reverse('users:login')

    # Admin users are redirected to the Django admin panel
    if user.is_admin():
        return reverse('admin:index')

    # Role-based URL mapping using named URLs from users/urls.py
    role_url_map = {
        'cliente': 'users:panel_cliente',
        'vendedor': 'users:dashboard_vendedor',
        'distribuidor': 'users:panel_distribuidor',
    }

    # Get the URL for the user's role, default to login if role is unknown
    url_name = role_url_map.get(user.rol, 'users:login')
    return reverse(url_name)


def get_default_redirect_after_login():
    """
    Returns a default redirect URL when the user's role cannot be determined.

    Returns:
        str: Safe fallback URL.
    """
    return reverse('users:login')


def get_route_name_for_role(role):
    """
    Returns the view or URL name associated with a given role.

    Args:
        role (str): The user's role.

    Returns:
        str: Name of the URL pattern or view for the role.
    """
    route_map = {
        'admin': 'admin:index',
        'distribuidor': 'panel_distribuidor',
        'vendedor': 'dashboard_vendedor',
        'cliente': 'panel_cliente',
    }
    return route_map.get(role, 'login')