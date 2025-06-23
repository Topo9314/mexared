from django.shortcuts import redirect
from django.core.exceptions import PermissionDenied
from functools import wraps

def role_required(allowed_roles):
    """
    Decorador para restringir el acceso según el rol del usuario.
    Acepta un solo rol (str) o varios roles (list o tuple).
    """
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    elif not isinstance(allowed_roles, (list, tuple)):
        raise TypeError("allowed_roles debe ser una lista, tupla o string válido.")

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('users:login')

            if not hasattr(request.user, 'rol'):
                raise PermissionDenied("El usuario no tiene atributo 'rol'.")

            if request.user.rol not in allowed_roles:
                raise PermissionDenied("Acceso denegado. Rol no autorizado.")

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
