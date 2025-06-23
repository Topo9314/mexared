"""
Vistas principales para la gestión de usuarios en MexaRed.
Proporciona autenticación, registro, cierre de sesión y redirección por rol,
con auditoría detallada, seguridad robusta y preparación para expansión financiera global.
Diseñado para ser modular, escalable y mantenible en entornos internacionales de alto volumen.
"""

import logging
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.contrib import messages
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import PermissionDenied

from .models import User, UserChangeLog
from .forms import ClientRegisterForm, LoginForm
from .services.auth_service import AuthService
from .utils.routing import get_dashboard_url_for_user
from apps.transacciones.services.saldo_service import SaldoService


# Configuración de logging para monitoreo en producción
logger = logging.getLogger(__name__)

# ============================
# 🔐 DECORADORES PERSONALIZADOS
# ============================

def anonymous_required(view_func):
    """
    Decorador que asegura que el usuario no esté autenticado.
    Redirige a dashboard_redirect si ya está logueado.
    """
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('users:dashboard_redirect')
        return view_func(request, *args, **kwargs)
    return wrapper

# ============================
# 🔐 VISTA DE LOGIN
# ============================

@require_http_methods(["GET", "POST"])
@csrf_protect
@anonymous_required
def login_view(request):
    """
    Vista para iniciar sesión de cualquier usuario.
    Autentica credenciales usando AuthService y redirige según el rol.
    """
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data.get("username").strip().lower()
        password = form.cleaned_data.get("password")
        result = AuthService.process_login(username, password, request)
        if result.success:
            messages.success(request, _("Bienvenido, ") + result.user.full_name)
            logger.info(f"Usuario {result.user.username} inició sesión exitosamente desde {request.META.get('REMOTE_ADDR')}")
            return redirect(result.redirect_url)
        messages.error(request, result.message)
        logger.warning(f"Intento de login fallido para {username} desde {request.META.get('REMOTE_ADDR')}")

    return render(request, 'users/login.html', {"form": form, "title": _("Iniciar Sesión")})

# ============================
# 🧾 VISTA DE REGISTRO DE CLIENTE
# ============================

@require_http_methods(["GET", "POST"])
@csrf_protect
@anonymous_required
def register_view(request):
    """
    Registro exclusivo para clientes finales.
    Crea un usuario con rol 'cliente' y registra la acción en UserChangeLog.
    """
    form = ClientRegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.rol = 'cliente'
        user.email = user.email.strip().lower()
        user.username = user.username.strip().lower()
        user.save()

        UserChangeLog.objects.create(
            user=user,
            change_type='create',
            change_description="Registro de nuevo cliente",
            details={
                "username": user.username,
                "email": user.email,
                "saldo_inicial": 0.0  # Asumimos saldo inicial 0, ya que User no tiene campo saldo
            }
        )
        messages.success(request, _("Registro exitoso. Inicia sesión."))
        logger.info(f"Nuevo cliente registrado: {user.username}")
        return redirect('users:login')

    return render(request, 'users/register.html', {
        "form": form,
        "title": _("Registrarse")
    })

# ============================
# 🚪 CERRAR SESIÓN
# ============================

@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def logout_view(request):
    """
    Cierra la sesión del usuario y registra la acción en UserChangeLog.
    """
    user = request.user
    logout(request)
    UserChangeLog.objects.create(
        user=user,
        change_type='update',
        change_description="Cierre de sesión",
        details={"username": user.username}
    )
    messages.info(request, _("Sesión cerrada correctamente."))
    logger.info(f"Usuario {user.username} cerró sesión")
    return redirect('users:login')

# ============================
# 🧭 REDIRECCIÓN POR ROL
# ============================

@login_required
@require_http_methods(["GET"])
def dashboard_redirect(request):
    """
    Redirecciona al dashboard correspondiente según el rol del usuario.
    Registra la acción en UserChangeLog para auditoría.
    """
    user = request.user
    UserChangeLog.objects.create(
        user=user,
        change_type='update',
        change_description="Acceso al dashboard",
        details={"rol": user.rol}
    )
    url = get_dashboard_url_for_user(user)
    if url == reverse_lazy('users:login'):
        messages.error(request, _("Rol desconocido. Contacte a soporte."))
        UserChangeLog.objects.create(
            user=user,
            change_type='update',
            change_description="Intento de acceso con rol desconocido",
            details={"rol": user.rol}
        )
        logout(request)
        logger.warning(f"Usuario {user.username} intentó acceder con rol desconocido: {user.rol}")
        return redirect('users:login')
    logger.info(f"Usuario {user.username} redirigido a dashboard: {url}")
    return redirect(url)

# ============================
# 🔒 VISTA DE CAMBIO DE CONTRASEÑA (FUTURA EXPANSIÓN)
# ============================

@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def change_password_view(request):
    """
    Vista para que los usuarios cambien su contraseña (implementación futura).
    """
    messages.info(request, _("Funcionalidad de cambio de contraseña en desarrollo."))
    return redirect('users:dashboard_redirect')

# ============================
# 📊 PANELES DE USUARIO
# ============================

@login_required
def panel_cliente(request):
    """
    Panel para clientes finales, muestra resumen de saldo y transacciones recientes.
    """
    resumen = SaldoService.obtener_resumen_saldo(request.user)

    return render(request, 'users/panel_cliente.html', {
        "saldo": resumen["saldo_actual"],
        "transacciones": resumen["ultimas_transacciones"],
        "title": _("Panel de Cliente")
    })

@login_required
def panel_vendedor(request):
    """
    Panel para vendedores, muestra resumen de saldo y transacciones recientes.
    """
    resumen = SaldoService.obtener_resumen_saldo(request.user)

    return render(request, 'users/panel_vendedor.html', {
        "saldo": resumen["saldo_actual"],
        "transacciones": resumen["ultimas_transacciones"],
        "title": _("Panel de Vendedor")
    })

@login_required
def panel_distribuidor(request):
    """
    Panel para distribuidores, muestra resumen de saldo y transacciones recientes.
    """
    resumen = SaldoService.obtener_resumen_saldo(request.user)

    return render(request, 'users/panel_distribuidor.html', {
        "saldo": resumen["saldo_actual"],
        "transacciones": resumen["ultimas_transacciones"],
        "title": _("Panel de Distribuidor")
    })