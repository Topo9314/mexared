"""
Vistas específicas para distribuidores en MexaRed.
Gestiona el panel principal y la edición de perfil del distribuidor.
Integra el saldo de la billetera para visualización en el panel.
Proporciona auditoría detallada, seguridad robusta y soporte multilenguaje.
Cumple con estándares internacionales (PCI DSS, SOC2, ISO 27001) y escalabilidad SaaS.
"""

import logging
from decimal import Decimal
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.db.models import Q, Count
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError

from apps.users.models import User, UserChangeLog, DistribuidorVendedor
from apps.users.forms import UserUpdateForm
from apps.users.decorators import role_required
from apps.wallet.models import Wallet

# Configuración del logger para auditoría empresarial
logger = logging.getLogger(__name__)

# ============================
# 📊 PANEL PRINCIPAL DEL DISTRIBUIDOR
# ============================

@login_required
@require_http_methods(["GET"])
@role_required(['distribuidor'])
def panel_distribuidor(request):
    """
    Panel principal para distribuidores.
    Muestra KPIs: número de vendedores, clientes, últimos registros, acciones y saldo disponible.
    Optimiza consultas con select_related y annotate para escalabilidad.
    Integra el saldo de la billetera del distribuidor de forma segura y auditada.
    """
    user = request.user

    # Obtener saldo disponible de la billetera
    try:
        wallet = Wallet.objects.select_related('user').get(user=user)
        saldo_disponible = wallet.balance
    except Wallet.DoesNotExist:
        logger.warning(f"Usuario {user.username} (ID: {user.id}) no tiene billetera asociada al acceder al panel.")
        saldo_disponible = Decimal('0.00')
        messages.warning(request, _("No tienes una billetera asociada. Contacta a soporte."))
    except Exception as e:
        logger.error(f"Error al obtener saldo para {user.username} (ID: {user.id}): {str(e)}", exc_info=True)
        saldo_disponible = Decimal('0.00')
        messages.error(request, _("Error al cargar el saldo disponible. Intenta de nuevo más tarde."))

    # Contar vendedores asignados
    vendedores_count = DistribuidorVendedor.objects.filter(
        distribuidor=user, activo=True
    ).count()

    # Contar clientes (propios y de vendedores)
    vendedores_ids = DistribuidorVendedor.objects.filter(
        distribuidor=user, activo=True
    ).values_list('vendedor_id', flat=True)
    clientes_count = User.objects.filter(
        Q(created_by=user) | Q(created_by__in=vendedores_ids),
        rol='cliente', deleted_at__isnull=True
    ).count()

    # Últimos 5 vendedores
    ultimos_vendedores = User.objects.filter(
        distribuidor_asignado__distribuidor=user,
        distribuidor_asignado__activo=True,
        rol='vendedor',
        deleted_at__isnull=True
    ).select_related().order_by('-date_joined')[:5]

    # Últimas acciones
    ultimas_acciones = UserChangeLog.objects.filter(
        Q(user=user) | Q(changed_by=user)
    ).select_related('user', 'changed_by').order_by('-timestamp')[:5]

    # Registrar acceso en auditoría
    try:
        with transaction.atomic():
            UserChangeLog.objects.create(
                user=user,
                change_type='update',
                change_description="Acceso al panel de distribuidor",
                details={
                    "ip_address": request.META.get('REMOTE_ADDR', 'unknown'),
                    "saldo_disponible": str(saldo_disponible),
                    "vendedores_count": vendedores_count,
                    "clientes_count": clientes_count
                }
            )
    except Exception as e:
        logger.error(f"Error al registrar auditoría para {user.username} (ID: {user.id}): {str(e)}", exc_info=True)

    logger.info(f"[{timezone.now()}] Distribuidor {user.username} (ID: {user.id}) accedió al panel con saldo: {saldo_disponible} MXN")

    return render(request, 'users/distribuidor/panel.html', {
        "title": _("Panel de Distribuidor"),
        "vendedores_count": vendedores_count,
        "clientes_count": clientes_count,
        "ultimos_vendedores": ultimos_vendedores,
        "ultimas_acciones": ultimas_acciones,
        "saldo_disponible": saldo_disponible
    })

# ============================
# ✏️ EDICIÓN DE PERFIL
# ============================

@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
@role_required(['distribuidor'])
def editar_perfil_distribuidor(request):
    """
    Permite a los distribuidores actualizar su perfil.
    Registra cambios en UserChangeLog con auditoría detallada.
    """
    user = request.user
    form = UserUpdateForm(request.POST or None, instance=user)

    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                old_data = {
                    'email': user.email,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'telefono': user.telefono
                }
                form.save()
                changes = {
                    field: {"before": old_data[field], "after": getattr(user, field)}
                    for field in old_data if old_data[field] != getattr(user, field)
                }

                if changes:
                    UserChangeLog.objects.create(
                        user=user,
                        change_type='update',
                        change_description=f"Actualización de perfil: {', '.join(changes.keys())}",
                        details=changes
                    )
                    logger.info(f"[{timezone.now()}] Distribuidor {user.username} actualizó perfil: {changes.keys()}")

                messages.success(request, _("Perfil actualizado correctamente."))
                return redirect('users:panel_distribuidor')
        except Exception as e:
            messages.error(request, _("Error al actualizar el perfil: ") + str(e))
            logger.error(f"[{timezone.now()}] Error al actualizar perfil de {user.username}: {str(e)}", exc_info=True)

    return render(request, 'users/distribuidor/editar_perfil.html', {
        "form": form,
        "title": _("Editar Perfil")
    })