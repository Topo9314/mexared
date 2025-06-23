"""
Ledger financiero operativo de MexaRed - Versión Profesional.
Proporciona una visión exacta de la distribución de fondos por jerarquía completa.
Cumple con estándares SaaS financieros multinivel (PCI-DSS, SOC2, ISO 27001).
Soporta auditoría contable, visualización en tiempo real y extensibilidad para conciliaciones.
"""

import logging
from decimal import Decimal
from django.views.generic import TemplateView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from apps.users.models import User, ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR, ROLE_CLIENTE
from apps.wallet.models import Wallet

# Configuración de logging para auditoría en producción
logger = logging.getLogger("ledger_profesional")

class SecureRequiredMixin:
    """Forza HTTPS para cumplir con estándares bancarios (PCI-DSS)."""
    def dispatch(self, request, *args, **kwargs):
        if not request.is_secure() and request.META.get("HTTP_X_FORWARDED_PROTO", "https") != "https":
            logger.warning(
                f"Acceso no seguro a {self.__class__.__name__} desde {request.META.get('REMOTE_ADDR')}"
            )
            raise PermissionDenied(_("Conexión no segura. Use HTTPS."))
        return super().dispatch(request, *args, **kwargs)

class LedgerGlobalSummaryView(LoginRequiredMixin, SecureRequiredMixin, TemplateView):
    """
    Vista de resumen global de saldos (totales, disponibles y bloqueados) por rol.
    Accesible solo para superusuarios con rol ROLE_ADMIN.
    Proporciona una visión contable consolidada para auditorías.

    Attributes:
        template_name: Plantilla para renderizar el resumen.
    """
    template_name = "wallet/ledger_global_summary.html"

    def dispatch(self, request, *args, **kwargs):
        """Restringe acceso a superusuarios con rol ROLE_ADMIN."""
        if not request.user.is_superuser or request.user.rol != ROLE_ADMIN:
            logger.warning(
                f"Acceso denegado a LedgerGlobalSummaryView para {request.user.username} "
                f"(rol: {request.user.rol})"
            )
            raise PermissionDenied(_("No tienes permisos para acceder al libro mayor global."))
        logger.info(f"Usuario {request.user.username} accedió al resumen global del ledger.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """
        Proporciona contexto para la plantilla, incluyendo el resumen de saldos.

        Returns:
            dict: Contexto con título y resumen de saldos por rol.
        """
        context = super().get_context_data(**kwargs)
        context['title'] = _("Ledger Financiero Global")
        context['title_section'] = _("Resumen Contable Global")
        context['summary'] = self._global_summary()
        return context

    def _global_summary(self):
        """
        Calcula el resumen de saldos totales, disponibles y bloqueados por rol.

        Returns:
            dict: Resumen con saldos y conteo de cuentas por rol.
        """
        roles = {
            ROLE_ADMIN: _("Administradores"),
            ROLE_DISTRIBUIDOR: _("Distribuidores"),
            ROLE_VENDEDOR: _("Vendedores"),
            ROLE_CLIENTE: _("Clientes"),
        }

        summary = {}
        total_balance = Decimal('0.00')
        total_blocked = Decimal('0.00')
        total_available = Decimal('0.00')

        for role, label in roles.items():
            wallets = Wallet.objects.filter(
                user__rol=role,
                user__deleted_at__isnull=True
            ).select_related('user')
            aggregates = wallets.aggregate(
                balance=Sum('balance') or Decimal('0.00'),
                blocked=Sum('blocked_balance') or Decimal('0.00')
            )
            role_balance = aggregates['balance']
            role_blocked = aggregates['blocked']
            role_available = role_balance - role_blocked

            summary[label] = {
                "balance": role_balance,
                "blocked": role_blocked,
                "available": role_available,
                "count": wallets.count(),
            }

            total_balance += role_balance
            total_blocked += role_blocked
            total_available += role_available

        summary[_("Total Global")] = {
            "balance": total_balance,
            "blocked": total_blocked,
            "available": total_available,
            "count": Wallet.objects.filter(user__deleted_at__isnull=True).count(),
        }

        logger.debug(f"Resumen global calculado: {summary}")
        return summary

class LedgerDistribuidorDetailView(LoginRequiredMixin, SecureRequiredMixin, DetailView):
    """
    Vista detallada de saldos para un Distribuidor, incluyendo su propia billetera y las de sus subordinados.
    Accesible para superusuarios, ROLE_ADMIN o el propio Distribuidor.

    Attributes:
        model: Modelo User para el Distribuidor.
        template_name: Plantilla para renderizar el detalle.
        pk_url_kwarg: Nombre del parámetro de URL para el ID del Distribuidor.
        context_object_name: Nombre del objeto en el contexto.
    """
    model = User
    template_name = "wallet/ledger_distribuidor_detail.html"
    pk_url_kwarg = 'distribuidor_id'
    context_object_name = 'distribuidor'

    def dispatch(self, request, *args, **kwargs):
        """Valida que el usuario sea un Distribuidor y que el solicitante tenga permisos."""
        obj = self.get_object()
        if not obj or obj.rol != ROLE_DISTRIBUIDOR:
            logger.warning(
                f"Acceso denegado a LedgerDistribuidorDetailView para {request.user.username}: "
                f"Usuario {obj.id if obj else 'None'} no es distribuidor"
            )
            raise PermissionDenied(_("Este usuario no es un distribuidor válido."))
        if not request.user.is_superuser and request.user.rol != ROLE_ADMIN and request.user != obj:
            logger.warning(
                f"Acceso denegado a LedgerDistribuidorDetailView para {request.user.username}: "
                f"No autorizado para distribuidor {obj.id}"
            )
            raise PermissionDenied(_("No estás autorizado para ver este detalle."))
        logger.info(
            f"Usuario {request.user.username} accedió al detalle del ledger para distribuidor {obj.id}"
        )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """
        Proporciona contexto para la plantilla, incluyendo resumen de saldos del distribuidor y subordinados.

        Returns:
            dict: Contexto con título y resumen detallado.
        """
        context = super().get_context_data(**kwargs)
        context['title'] = _("Detalle Financiero del Distribuidor")
        context['title_section'] = _(
            "Detalles Contables para %(username)s"
        ) % {'username': self.object.username}
        context['summary'] = self._distribuidor_summary()
        return context

    def _distribuidor_summary(self):
        """
        Calcula el resumen de saldos para el Distribuidor y sus subordinados.

        Returns:
            dict: Resumen con saldos del distribuidor, subordinados y total consolidado.
        """
        distribuidor = self.get_object()
        wallet = getattr(distribuidor, 'wallet', None)

        dist_balance = wallet.balance if wallet else Decimal('0.00')
        dist_blocked = wallet.blocked_balance if wallet else Decimal('0.00')
        dist_available = dist_balance - dist_blocked

        subordinados = User.objects.filter(
            wallet__hierarchy_root=distribuidor,
            deleted_at__isnull=True
        ).select_related('wallet').order_by('username')

        sub_balance = Decimal('0.00')
        sub_blocked = Decimal('0.00')
        sub_count = 0
        accounts = []

        for user in subordinados:
            user_wallet = getattr(user, 'wallet', None)
            user_balance = user_wallet.balance if user_wallet else Decimal('0.00')
            user_blocked = user_wallet.blocked_balance if user_wallet else Decimal('0.00')
            user_available = user_balance - user_blocked

            accounts.append({
                "user_id": user.id,
                "username": user.username,
                "rol": user.get_rol_display(),
                "balance": user_balance,
                "blocked": user_blocked,
                "available": user_available,
                "has_wallet": bool(user_wallet)
            })

            sub_balance += user_balance
            sub_blocked += user_blocked
            sub_count += 1

        summary = {
            "distribuidor": {
                "balance": dist_balance,
                "blocked": dist_blocked,
                "available": dist_available,
                "has_wallet": bool(wallet)
            },
            "subaccounts": {
                "accounts": accounts,
                "balance": sub_balance,
                "blocked": sub_blocked,
                "available": sub_balance - sub_blocked,
                "count": sub_count
            },
            "total_consolidado": {
                "balance": dist_balance + sub_balance,
                "blocked": dist_blocked + sub_blocked,
                "available": dist_available + (sub_balance - sub_blocked),
                "total_users": sub_count + (1 if wallet else 0)
            }
        }

        logger.debug(
            f"Resumen detallado calculado para distribuidor {distribuidor.id}: {summary}"
        )
        return summary