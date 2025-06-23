"""
Vistas específicas para clientes en MexaRed.
Maneja registro, panel principal, y actualización de perfil para usuarios con rol 'cliente'.
Diseñado para ser seguro, escalable y compatible con internacionalización.
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.contrib import messages
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import PermissionDenied

from apps.users.models import User, UserChangeLog
from apps.users.forms import ClientRegisterForm, UserUpdateForm
from apps.users.decorators import role_required
from django.utils import timezone

# ============================
# 🧾 REGISTRO DE CLIENTE
# ============================

@require_http_methods(["GET", "POST"])
@csrf_protect
def cliente_register_view(request):
    """
    Registro exclusivo para clientes finales.
    Crea un usuario con rol 'cliente' y registra la acción en UserChangeLog.
    """
    if request.user.is_authenticated:
        messages.warning(request, _("Ya estás autenticado."))
        return redirect('users:dashboard_redirect')

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
                "ip_address": request.META.get('REMOTE_ADDR')
            }
        )
        messages.success(request, _("Registro exitoso. Inicia sesión para continuar."))
        return redirect('users:login')

    return render(request, 'users/cliente/register.html', {
        "form": form,
        "title": _("Registrarse como Cliente")
    })

# ============================
# 📊 PANEL PRINCIPAL DEL CLIENTE
# ============================

@login_required
@require_http_methods(["GET"])
@role_required('cliente')
def panel_cliente(request):
    """
    Panel principal para clientes.
    Muestra información básica del usuario y opciones disponibles.
    """
    user = request.user
    UserChangeLog.objects.create(
        user=user,
        change_type='update',
        change_description="Acceso al panel de cliente",
        details={"username": user.username}
    )

    return render(request, 'users/cliente/panel.html', {
        "user": user,
        "title": _("Panel de Cliente")
    })

# ============================
# ✏️ EDICIÓN DE PERFIL
# ============================

@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
@role_required('cliente')
def editar_perfil_cliente(request):
    """
    Permite a los clientes actualizar su perfil (nombre, correo, teléfono).
    Registra cambios en UserChangeLog.
    """
    user = request.user
    form = UserUpdateForm(request.POST or None, instance=user)

    if request.method == "POST" and form.is_valid():
        old_email = user.email
        form.save()

        # Registrar cambios en UserChangeLog
        changes = {}
        fields_to_track = ['email', 'first_name', 'last_name', 'telefono']
        for field in fields_to_track:
            old_value = getattr(user, field, None)
            new_value = form.cleaned_data.get(field)
            if old_value != new_value:
                changes[field] = {"before": old_value, "after": new_value}

        if changes:
            UserChangeLog.objects.create(
                user=user,
                change_type='update',
                change_description=f"Actualización de perfil: {', '.join(changes.keys())}",
                details=changes
            )

        messages.success(request, _("Perfil actualizado correctamente."))
        return redirect('users:panel_cliente')

    return render(request, 'users/cliente/editar_perfil.html', {
        "form": form,
        "title": _("Editar Perfil")
    })