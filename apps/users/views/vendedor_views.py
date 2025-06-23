"""
Vistas específicas para vendedores en MexaRed.
Maneja panel, edición de perfil, registro de clientes, listado/detalle de clientes,
reporte de comisiones y soporte, con soporte para internacionalización y auditoría.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.core.exceptions import PermissionDenied
from django.utils import timezone
import re

from apps.users.models import User, UserChangeLog, DistribuidorVendedor
from apps.users.forms import ClientRegisterForm, UserUpdateForm
from apps.users.decorators import role_required
from apps.users.services.auth_service import normalize_email, normalize_username

# ============================
# 📊 PANEL PRINCIPAL DEL VENDEDOR
# ============================

@login_required
@require_http_methods(["GET"])
@role_required(['vendedor'])
def vendedor_dashboard(request):
    """
    Panel principal para vendedores.
    Muestra información básica y estadísticas iniciales.
    """
    user = request.user
    # Contar clientes captados
    clientes_count = User.objects.filter(
        rol='cliente', created_by=user
    ).count()
    # Obtener distribuidor asignado (si existe)
    distribuidor = DistribuidorVendedor.objects.filter(
        vendedor=user, activo=True
    ).select_related('distribuidor').first()

    UserChangeLog.objects.create(
        user=user,
        change_type='update',
        change_description="Acceso al panel de vendedor",
        details={"username": user.username, "ip_address": request.META.get('REMOTE_ADDR')}
    )

    return render(request, 'users/vendedor/panel.html', {
        "title": _("Panel de Vendedor"),
        "clientes_count": clientes_count,
        "distribuidor": distribuidor.distribuidor if distribuidor else None
    })

# ============================
# ✏️ EDICIÓN DE PERFIL
# ============================

@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
@role_required(['vendedor'])
def editar_perfil_vendedor(request):
    """
    Permite a los vendedores actualizar su perfil (nombre, correo, teléfono).
    Registra cambios en UserChangeLog.
    """
    user = request.user
    form = UserUpdateForm(request.POST or None, instance=user)

    if request.method == "POST" and form.is_valid():
        old_data = {
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'telefono': user.telefono
        }
        form.save()

        # Registrar cambios en UserChangeLog
        changes = {}
        fields_to_track = ['email', 'first_name', 'last_name', 'telefono']
        for field in fields_to_track:
            old_value = old_data[field]
            new_value = getattr(user, field)
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
        return redirect('users:dashboard_vendedor')

    return render(request, 'users/vendedor/editar_perfil.html', {
        "form": form,
        "title": _("Editar Perfil")
    })

# ============================
# 🧾 REGISTRO DE NUEVO CLIENTE
# ============================

@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
@role_required(['vendedor'])
def registrar_cliente_por_vendedor(request):
    """
    Permite a los vendedores registrar nuevos clientes.
    El vendedor se asigna como 'created_by' y se registra en UserChangeLog.
    """
    form = ClientRegisterForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.rol = 'cliente'
        user.email = normalize_email(user.email)
        user.username = normalize_username(user.username)
        user.created_by = request.user  # Asignar vendedor como creador
        user.save()

        UserChangeLog.objects.create(
            user=user,
            changed_by=request.user,
            change_type='create',
            change_description="Registro de nuevo cliente por vendedor",
            details={
                "username": user.username,
                "email": user.email,
                "created_by": request.user.username,
                "ip_address": request.META.get('REMOTE_ADDR')
            }
        )

        messages.success(request, _("Cliente registrado exitosamente."))
        return redirect('users:listado_clientes_captados')

    return render(request, 'users/vendedor/registrar_cliente.html', {
        "form": form,
        "title": _("Registrar Cliente")
    })

# ============================
# 📋 LISTADO DE CLIENTES CAPTADOS
# ============================

@login_required
@require_http_methods(["GET"])
@role_required(['vendedor'])
def listado_clientes_captados(request):
    """
    Muestra una lista paginada de clientes captados por el vendedor.
    Incluye búsqueda por nombre o correo.
    """
    query = request.GET.get('q', '')
    clientes = User.objects.filter(
        rol='cliente', created_by=request.user, deleted_at__isnull=True
    ).select_related()

    if query:
        clientes = clientes.filter(
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        )

    paginator = Paginator(clientes, 10)  # 10 clientes por página
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    UserChangeLog.objects.create(
        user=request.user,
        change_type='update',
        change_description="Consulta de listado de clientes captados",
        details={"query": query, "ip_address": request.META.get('REMOTE_ADDR')}
    )

    return render(request, 'users/vendedor/listado_clientes.html', {
        "page_obj": page_obj,
        "query": query,
        "title": _("Clientes Captados")
    })

# ============================
# 🔍 DETALLE DE CLIENTE CAPTADO
# ============================

@login_required
@require_http_methods(["GET"])
@role_required(['vendedor'])
def detalle_cliente_captado(request, cliente_id):
    """
    Muestra detalles de un cliente captado por el vendedor.
    Solo accesible si el vendedor es el creador.
    """
    cliente = get_object_or_404(
        User,
        id=cliente_id,
        rol='cliente',
        created_by=request.user,
        deleted_at__isnull=True
    )

    UserChangeLog.objects.create(
        user=request.user,
        change_type='update',
        change_description="Consulta de detalle de cliente",
        details={"cliente_id": cliente_id, "cliente_username": cliente.username}
    )

    return render(request, 'users/vendedor/detalle_cliente.html', {
        "cliente": cliente,
        "title": _("Detalle del Cliente")
    })

# ============================
# 💸 HISTORIAL DE COMISIONES
# ============================

@login_required
@require_http_methods(["GET"])
@role_required(['vendedor'])
def historial_comisiones(request):
    """
    Muestra el historial de comisiones del vendedor.
    Preparado para futura integración con un modelo de comisiones.
    """
    # Placeholder: Asume un modelo Comision relacionado con User
    comisiones = []
    total = 0

    try:
        comisiones = request.user.comisiones.filter(activo=True).select_related()
        total = comisiones.aggregate(total=Sum('monto'))['total'] or 0
    except AttributeError:
        # Si no existe el modelo de comisiones, usar datos ficticios
        pass

    UserChangeLog.objects.create(
        user=request.user,
        change_type='update',
        change_description="Consulta de historial de comisiones",
        details={"total": float(total)}
    )

    return render(request, 'users/vendedor/comisiones.html', {
        "comisiones": comisiones,
        "total": total,
        "title": _("Historial de Comisiones")
    })

# ============================
# 🆘 SOPORTE PARA VENDEDORES
# ============================

@login_required
@require_http_methods(["GET"])
@role_required(['vendedor'])
def soporte_vendedor(request):
    """
    Página de soporte con información de contacto y ayuda.
    Incluye enlace al distribuidor asignado (si existe).
    """
    distribuidor = DistribuidorVendedor.objects.filter(
        vendedor=request.user, activo=True
    ).select_related('distribuidor').first()

    UserChangeLog.objects.create(
        user=request.user,
        change_type='update',
        change_description="Acceso a página de soporte",
        details={"ip_address": request.META.get('REMOTE_ADDR')}
    )

    return render(request, 'users/vendedor/soporte.html', {
        "distribuidor": distribuidor.distribuidor if distribuidor else None,
        "title": _("Soporte para Vendedores")
    })