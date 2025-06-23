"""
Vistas operativas financieras de Wallet en MexaRed.
Controlan operaciones de recarga, transferencia, bloqueo, desbloqueo, dashboard y exportación CSV.
Diseñadas para cumplir con PCI DSS, SOC2, ISO 27001, integrándose en paneles administrativos seguros.
Utilizan Class-Based Views (CBV) para mantenibilidad y escalabilidad en entornos SaaS financieros.
"""

import logging
import csv
from decimal import Decimal
from django.views.generic import FormView, TemplateView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from django.db.models import Sum, Q
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_date

# Imports de proyecto
from apps.users.models import User, ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR, ROLE_CLIENTE
from apps.users.services.auth_service import AuthService
from apps.wallet.models import Wallet, WalletMovement
from apps.wallet.enums import TipoMovimiento
from apps.wallet.services import WalletService
from apps.wallet.forms import AdminRecargaForm, TransferenciaForm, BloqueoFondosForm, DesbloqueoFondosForm
from apps.wallet.exceptions import (
    WalletException,
    MovimientoInvalidoException,
    SaldoInsuficienteException,
    OperacionNoPermitidaException,
    ReferenciaExternaDuplicadaException,
    BloqueoFondosInvalidoException,
    ConciliacionInvalidaException,
)

# Configuración de logging para auditoría en producción
logger = logging.getLogger(__name__)

class SecureRequiredMixin:
    """Asegura que la vista se acceda solo vía HTTPS en producción."""
    def dispatch(self, request, *args, **kwargs):
        if not request.is_secure() and not settings.DEBUG:
            logger.warning(f"Acceso no seguro a {self.__class__.__name__} desde {request.META.get('REMOTE_ADDR')}")
            raise PermissionDenied(_("Acceso no seguro. Use HTTPS."))
        return super().dispatch(request, *args, **kwargs)

class RoleRequiredMixin(LoginRequiredMixin, SecureRequiredMixin):
    """
    Valida el rol de acceso permitido para la vista.

    Attributes:
        allowed_roles: Lista de roles permitidos (e.g., [ROLE_ADMIN, ROLE_DISTRIBUIDOR]).
    """
    allowed_roles = []

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            logger.warning(f"Intento de acceso anónimo a {self.__class__.__name__} desde {request.META.get('REMOTE_ADDR')}")
            raise PermissionDenied(_("Debes iniciar sesión para acceder a esta sección."))
        if request.user.rol not in self.allowed_roles:
            logger.warning(f"Acceso denegado a {self.__class__.__name__} para {request.user.username} (rol: {request.user.rol})")
            raise PermissionDenied(_("No tienes permiso para acceder a esta sección."))
        return super().dispatch(request, *args, **kwargs)

class PermissionRequiredMixin(RoleRequiredMixin):
    """
    Valida permisos específicos usando AuthService.

    Attributes:
        permission_required: Permiso requerido (e.g., 'wallet.creditar').
    """
    permission_required = None

    def dispatch(self, request, *args, **kwargs):
        if self.permission_required and not AuthService.has_permission(request.user, self.permission_required):
            logger.warning(f"Permiso {self.permission_required} denegado para {request.user.username}")
            raise PermissionDenied(_("No tienes el permiso necesario para esta operación."))
        return super().dispatch(request, *args, **kwargs)

@method_decorator(csrf_protect, name='dispatch')
class AdminRecargaView(PermissionRequiredMixin, FormView):
    """
    Vista para recargas de saldo por Admins.
    Permite acreditar fondos a cualquier billetera usando AdminRecargaForm.

    Attributes:
        template_name: Plantilla de la vista.
        form_class: Formulario asociado.
        success_url: URL de redirección tras éxito.
        allowed_roles: Roles permitidos (ROLE_ADMIN).
        permission_required: Permiso requerido (wallet.creditar).
    """
    template_name = "wallet/admin_recarga.html"
    form_class = AdminRecargaForm
    success_url = reverse_lazy("wallet:recarga")
    allowed_roles = [ROLE_ADMIN]
    permission_required = "wallet.creditar"

    def form_valid(self, form):
        """
        Procesa el formulario de recarga, ejecutando la operación vía WalletService.

        Args:
            form: Instancia del formulario validado.

        Returns:
            HttpResponse: Respuesta de éxito o error.
        """
        try:
            movement = WalletService.deposit(
                wallet=form.cleaned_data['usuario'].wallet,
                amount=form.cleaned_data['monto'],
                creado_por=self.request.user,
                referencia=form.cleaned_data.get('referencia'),
                actor_ip=self.request.META.get('REMOTE_ADDR', 'unknown'),
                device_info=self.request.META.get('HTTP_USER_AGENT', 'unknown'),
            )
            messages.success(self.request, _("Recarga realizada exitosamente."))
            logger.info(
                f"Recarga exitosa por {self.request.user.username}: "
                f"Wallet ID: {form.cleaned_data['usuario'].wallet.id}, "
                f"Monto: {form.cleaned_data['monto']} MXN, "
                f"Referencia: {form.cleaned_data.get('referencia') or 'N/A'}, "
                f"Movement ID: {movement.id}"
            )
            return super().form_valid(form)
        except WalletException as e:
            logger.exception(f"Error en recarga por {self.request.user.username}: {str(e)}")
            messages.error(self.request, str(e))
            form.add_error(None, str(e))
            return self.form_invalid(form)
        except Exception as ex:
            logger.exception(f"Falla inesperada en AdminRecargaView por {self.request.user.username}: {str(ex)}")
            messages.error(self.request, _("Ha ocurrido un error inesperado. Por favor, intenta nuevamente."))
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        """
        Añade contexto adicional para la plantilla.

        Args:
            **kwargs: Argumentos adicionales.

        Returns:
            dict: Contexto actualizado.
        """
        context = super().get_context_data(**kwargs)
        context['title'] = _("Recargar Saldo")
        context['title_section'] = _("Recarga de Fondos")
        return context

@method_decorator(csrf_protect, name='dispatch')
class TransferenciaView(PermissionRequiredMixin, FormView):
    """
    Vista para transferencias de saldo por Admins o Distribuidores.
    Permite mover fondos entre billeteras respetando jerarquías usando TransferenciaForm.

    Attributes:
        template_name: Plantilla de la vista.
        form_class: Formulario asociado.
        success_url: URL de redirección tras éxito.
        allowed_roles: Roles permitidos (ROLE_ADMIN, ROLE_DISTRIBUIDOR).
        permission_required: Permiso requerido (wallet.transferir).
    """
    template_name = "wallet/transferencia.html"
    form_class = TransferenciaForm
    success_url = reverse_lazy("wallet:transferencia")
    allowed_roles = [ROLE_ADMIN, ROLE_DISTRIBUIDOR]
    permission_required = "wallet.transferir"

    def get_initial(self):
        """
        Prellena el formulario con el destino si se proporciona en GET, validando jerarquía.

        Returns:
            dict: Datos iniciales del formulario.
        """
        initial = super().get_initial()
        destino_id = self.request.GET.get('destino')
        if destino_id:
            try:
                destino = User.objects.select_related('wallet').get(
                    id=destino_id,
                    rol__in=[ROLE_VENDEDOR, ROLE_CLIENTE],
                    hierarchy_root=self.request.user
                )
                initial['destino'] = destino
                logger.debug(f"Prellenado destino con ID {destino_id} para {self.request.user.username}")
            except User.DoesNotExist:
                logger.warning(f"Intento de prellenar destino inválido o no subordinado ID {destino_id} por {self.request.user.username}")
                messages.warning(self.request, _("El usuario destino especificado no es válido o no pertenece a su red."))
        return initial

    def get_form_kwargs(self):
        """
        Pasa el usuario autenticado al formulario para filtrar destinos válidos.

        Returns:
            dict: Argumentos del formulario.
        """
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        """
        Procesa el formulario de transferencia, ejecutando la operación vía WalletService.

        Args:
            form: Instancia del formulario validado.

        Returns:
            HttpResponse: Respuesta de éxito o error.
        """
        try:
            movements = WalletService.transfer(
                origen_wallet=self.request.user.wallet,
                destino_wallet=form.cleaned_data['destino'].wallet,
                amount=form.cleaned_data['monto'],
                creado_por=self.request.user,
                referencia=form.cleaned_data.get('referencia'),
                actor_ip=self.request.META.get('REMOTE_ADDR', 'unknown'),
                device_info=self.request.META.get('HTTP_USER_AGENT', 'unknown'),
            )
            messages.success(self.request, _("Transferencia realizada exitosamente."))
            logger.info(
                f"Transferencia exitosa por {self.request.user.username}: "
                f"Origen Wallet ID: {self.request.user.wallet.id}, "
                f"Destino Wallet ID: {form.cleaned_data['destino'].wallet.id}, "
                f"Monto: {form.cleaned_data['monto']} MXN, "
                f"Referencia: {form.cleaned_data.get('referencia') or 'N/A'}, "
                f"Movement IDs: {[m.id for m in movements]}"
            )
            return super().form_valid(form)
        except WalletException as e:
            logger.exception(f"Error en transferencia por {self.request.user.username}: {str(e)}")
            messages.error(self.request, str(e))
            form.add_error(None, str(e))
            return self.form_invalid(form)
        except Exception as ex:
            logger.exception(f"Falla inesperada en TransferenciaView por {self.request.user.username}: {str(ex)}")
            messages.error(self.request, _("Ha ocurrido un error inesperado. Por favor, intenta nuevamente."))
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        """
        Añade contexto adicional para la plantilla.

        Args:
            **kwargs: Argumentos adicionales.

        Returns:
            dict: Contexto actualizado.
        """
        context = super().get_context_data(**kwargs)
        context['title'] = _("Transferir Saldo")
        context['title_section'] = _("Transferencia de Fondos")
        return context

@method_decorator(csrf_protect, name='dispatch')
class BloqueoFondosView(PermissionRequiredMixin, FormView):
    """
    Vista para bloqueo de fondos por Admins.
    Permite retener fondos en una billetera usando BloqueoFondosForm.

    Attributes:
        template_name: Plantilla de la vista.
        form_class: Formulario asociado.
        success_url: URL de redirección tras éxito.
        allowed_roles: Roles permitidos (ROLE_ADMIN).
        permission_required: Permiso requerido (wallet.bloquear).
    """
    template_name = "wallet/bloqueo.html"
    form_class = BloqueoFondosForm
    success_url = reverse_lazy("wallet:bloqueo")
    allowed_roles = [ROLE_ADMIN]
    permission_required = "wallet.bloquear"

    def form_valid(self, form):
        """
        Procesa el formulario de bloqueo, ejecutando la operación vía WalletService.

        Args:
            form: Instancia del formulario validado.

        Returns:
            HttpResponse: Respuesta de éxito o error.
        """
        try:
            movement = WalletService.block_funds(
                wallet=form.cleaned_data['usuario'].wallet,
                amount=form.cleaned_data['monto'],
                creado_por=self.request.user,
                referencia=form.cleaned_data.get('referencia'),
                actor_ip=self.request.META.get('REMOTE_ADDR', 'unknown'),
                device_info=self.request.META.get('HTTP_USER_AGENT', 'unknown'),
            )
            messages.success(self.request, _("Bloqueo realizado exitosamente."))
            logger.info(
                f"Bloqueo exitoso por {self.request.user.username}: "
                f"Wallet ID: {form.cleaned_data['usuario'].wallet.id}, "
                f"Monto: {form.cleaned_data['monto']} MXN, "
                f"Referencia: {form.cleaned_data.get('referencia') or 'N/A'}, "
                f"Movement ID: {movement.id}"
            )
            return super().form_valid(form)
        except WalletException as e:
            logger.exception(f"Error en bloqueo por {self.request.user.username}: {str(e)}")
            messages.error(self.request, str(e))
            form.add_error(None, str(e))
            return self.form_invalid(form)
        except Exception as ex:
            logger.exception(f"Falla inesperada en BloqueoFondosView por {self.request.user.username}: {str(ex)}")
            messages.error(self.request, _("Ha ocurrido un error inesperado. Por favor, intenta nuevamente."))
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        """
        Añade contexto adicional para la plantilla.

        Args:
            **kwargs: Argumentos adicionales.

        Returns:
            dict: Contexto actualizado.
        """
        context = super().get_context_data(**kwargs)
        context['title'] = _("Bloquear Fondos")
        context['title_section'] = _("Bloqueo de Fondos")
        return context

@method_decorator(csrf_protect, name='dispatch')
class DesbloqueoFondosView(PermissionRequiredMixin, FormView):
    """
    Vista para desbloqueo de fondos por Admins.
    Permite liberar fondos retenidos usando DesbloqueoFondosForm.

    Attributes:
        template_name: Plantilla de la vista.
        form_class: Formulario asociado.
        success_url: URL de redirección tras éxito.
        allowed_roles: Roles permitidos (ROLE_ADMIN).
        permission_required: Permiso requerido (wallet.desbloquear).
    """
    template_name = "wallet/desbloqueo.html"
    form_class = DesbloqueoFondosForm
    success_url = reverse_lazy("wallet:desbloqueo")
    allowed_roles = [ROLE_ADMIN]
    permission_required = "wallet.desbloquear"

    def form_valid(self, form):
        """
        Procesa el formulario de desbloqueo, ejecutando la operación vía WalletService.

        Args:
            form: Instancia del formulario validado.

        Returns:
            HttpResponse: Respuesta de éxito o error.
        """
        try:
            movement = WalletService.unblock_funds(
                wallet=form.cleaned_data['usuario'].wallet,
                amount=form.cleaned_data['monto'],
                creado_por=self.request.user,
                referencia=form.cleaned_data.get('referencia'),
                actor_ip=self.request.META.get('REMOTE_ADDR', 'unknown'),
                device_info=self.request.META.get('HTTP_USER_AGENT', 'unknown'),
            )
            messages.success(self.request, _("Desbloqueo realizado exitosamente."))
            logger.info(
                f"Desbloqueo exitoso por {self.request.user.username}: "
                f"Wallet ID: {form.cleaned_data['usuario'].wallet.id}, "
                f"Monto: {form.cleaned_data['monto']} MXN, "
                f"Referencia: {form.cleaned_data.get('referencia') or 'N/A'}, "
                f"Movement ID: {movement.id}"
            )
            return super().form_valid(form)
        except WalletException as e:
            logger.exception(f"Error en desbloqueo por {self.request.user.username}: {str(e)}")
            messages.error(self.request, str(e))
            form.add_error(None, str(e))
            return self.form_invalid(form)
        except Exception as ex:
            logger.exception(f"Falla inesperada en DesbloqueoFondosView por {self.request.user.username}: {str(ex)}")
            messages.error(self.request, _("Ha ocurrido un error inesperado. Por favor, intenta nuevamente."))
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        """
        Añade contexto adicional para la plantilla.

        Args:
            **kwargs: Argumentos adicionales.

        Returns:
            dict: Contexto actualizado.
        """
        context = super().get_context_data(**kwargs)
        context['title'] = _("Desbloquear Fondos")
        context['title_section'] = _("Desbloqueo de Fondos")
        return context

@method_decorator(csrf_protect, name='dispatch')
class WalletDashboardView(PermissionRequiredMixin, TemplateView):
    """
    Vista de panel de monitoreo para Admins, Distribuidores y Vendedores.
    Muestra saldo disponible, saldo bloqueado, movimientos recientes y estadísticas.
    Soporta filtros, paginación y reportes fiscales.

    Attributes:
        template_name: Plantilla de la vista.
        allowed_roles: Roles permitidos (ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR).
        permission_required: Permiso requerido (wallet.ver_dashboard).
    """
    template_name = "wallet/dashboard.html"
    allowed_roles = [ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR]
    permission_required = "wallet.ver_dashboard"

    def get_context_data(self, **kwargs):
        """
        Proporciona contexto para la plantilla, incluyendo saldos, movimientos y estadísticas.
        Incluye información sobre el usuario destino en transferencias internas.

        Args:
            **kwargs: Argumentos adicionales.

        Returns:
            dict: Contexto actualizado.
        """
        context = super().get_context_data(**kwargs)
        user = self.request.user

        try:
            wallet = Wallet.objects.get(user=user)
        except Wallet.DoesNotExist:
            wallet = None
            messages.warning(self.request, _("No tienes una billetera asociada. Contacta a soporte."))
            logger.warning(f"Usuario {user.username} accedió al dashboard sin billetera.")

        context['wallet'] = wallet
        context['saldo_disponible'] = f"${wallet.balance:,.2f}" if wallet else "$0.00"
        context['saldo_bloqueado'] = f"${wallet.blocked_balance:,.2f}" if wallet else "$0.00"
        context['title'] = _("Panel de Billetera")
        context['title_section'] = _("Dashboard de Billetera")

        if wallet:
            movimientos = WalletMovement.objects.filter(wallet=wallet).select_related('creado_por', 'origen_wallet__user').only(
                'id', 'tipo', 'monto', 'referencia', 'fecha', 'conciliado', 'creado_por__username', 'origen_wallet__user__username'
            ).order_by('-fecha')

            # Aplicar filtros con validación segura
            tipo = self.request.GET.get('tipo')
            fecha_inicio = self.request.GET.get('fecha_inicio')
            fecha_fin = self.request.GET.get('fecha_fin')
            estado = self.request.GET.get('estado')

            if tipo and tipo in TipoMovimiento.values():
                movimientos = movimientos.filter(tipo=tipo)
                context['filtro_tipo'] = tipo
            if fecha_inicio:
                fecha_inicio_parsed = parse_date(fecha_inicio)
                if not fecha_inicio_parsed:
                    logger.warning(f"Filtro de fecha_inicio inválido: {fecha_inicio} por {user.username}")
                    messages.error(self.request, _("Formato de fecha de inicio inválido (use AAAA-MM-DD)."))
                else:
                    movimientos = movimientos.filter(fecha__gte=fecha_inicio_parsed)
                    context['filtro_fecha_inicio'] = fecha_inicio
            if fecha_fin:
                fecha_fin_parsed = parse_date(fecha_fin)
                if not fecha_fin_parsed:
                    logger.warning(f"Filtro de fecha_fin inválido: {fecha_fin} por {user.username}")
                    messages.error(self.request, _("Formato de fecha final inválido (use AAAA-MM-DD)."))
                else:
                    movimientos = movimientos.filter(fecha__lte=fecha_fin_parsed)
                    context['filtro_fecha_fin'] = fecha_fin
            if estado in ['conciliado', 'pendiente']:
                conciliado = estado == 'conciliado'
                movimientos = movimientos.filter(conciliado=conciliado)
                context['filtro_estado'] = estado

            # Estadísticas
            stats = movimientos.aggregate(
                total_creditos=Sum('monto', filter=Q(tipo=TipoMovimiento.CREDITO.name)) or Decimal('0.00'),
                total_debitos=Sum('monto', filter=Q(tipo=TipoMovimiento.DEBITO.name)) or Decimal('0.00'),
                total_transferencias=Sum('monto', filter=Q(tipo=TipoMovimiento.TRANSFERENCIA_INTERNA.name)) or Decimal('0.00'),
                total_bloqueos=Sum('monto', filter=Q(tipo=TipoMovimiento.BLOQUEO.name)) or Decimal('0.00'),
                total_desbloqueos=Sum('monto', filter=Q(tipo=TipoMovimiento.DESBLOQUEO.name)) or Decimal('0.00'),
            )

            # Procesar movimientos para incluir usuario destino en transferencias
            movimientos_lista = []
            for movimiento in movimientos:
                movimiento_dict = {
                    'id': movimiento.id,
                    'tipo': movimiento.tipo,
                    'monto': movimiento.monto,
                    'referencia': movimiento.referencia,
                    'fecha': movimiento.fecha,
                    'conciliado': movimiento.conciliado,
                    'creado_por': movimiento.creado_por.username if movimiento.creado_por else None,
                    'origen_username': movimiento.origen_wallet.user.username if movimiento.origen_wallet else None,
                    'destino_username': None
                }
                # Para transferencias internas, buscar el usuario destino
                if movimiento.tipo == TipoMovimiento.TRANSFERENCIA_INTERNA.name and movimiento.origen_wallet:
                    destino_movimiento = WalletMovement.objects.filter(
                        tipo=TipoMovimiento.TRANSFERENCIA_INTERNA.name,
                        monto=movimiento.monto,
                        fecha=movimiento.fecha,
                        referencia=movimiento.referencia,
                        origen_wallet=movimiento.origen_wallet
                    ).exclude(wallet=movimiento.wallet).select_related('wallet__user').first()
                    if destino_movimiento:
                        movimiento_dict['destino_username'] = destino_movimiento.wallet.user.username
                movimientos_lista.append(movimiento_dict)

            # Paginación
            paginator = Paginator(movimientos_lista, 10)
            page_number = self.request.GET.get('page')
            page_obj = paginator.get_page(page_number)

            context.update({
                'movimientos': page_obj,
                'tipo_movimientos': [(t.name, t.value) for t in TipoMovimiento],
                'creditos': stats['total_creditos'],
                'debitos': stats['total_debitos'],
                'transferencias': stats['total_transferencias'],
                'bloqueos': stats['total_bloqueos'],
                'desbloqueos': stats['total_desbloqueos'],
                'filtro_estado': estado,
            })

        logger.info(f"Usuario {user.username} accedió al dashboard de billetera.")
        return context

@method_decorator(csrf_protect, name='dispatch')
class ExportMovimientosView(PermissionRequiredMixin, View):
    """
    Vista para exportar movimientos a CSV.
    Restringida a Admins, Distribuidores y Vendedores, con filtros aplicados.

    Attributes:
        allowed_roles: Roles permitidos (ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR).
        permission_required: Permiso requerido (wallet.exportar_movimientos).
    """
    def get(self, request, *args, **kwargs):
        """
        Exporta movimientos a CSV basándose en filtros aplicados.

        Args:
            request: Solicitud HTTP.

        Returns:
            HttpResponse: Respuesta con archivo CSV o estado 204 si no hay datos.
        """
        user = request.user
        try:
            wallet = Wallet.objects.get(user=user)
        except Wallet.DoesNotExist:
            logger.error(f"Usuario {user.username} intentó exportar movimientos sin billetera.")
            messages.error(request, _("No tienes una billetera asociada."))
            return HttpResponse(status=400)

        movimientos = WalletMovement.objects.filter(wallet=wallet).select_related('creado_por', 'origen_wallet__user').only(
            'id', 'tipo', 'monto', 'referencia', 'fecha', 'conciliado', 'creado_por__username', 'origen_wallet__user__username'
        ).order_by('-fecha')

        # Aplicar filtros con validación segura
        tipo = request.GET.get('tipo')
        fecha_inicio = request.GET.get('fecha_inicio')
        fecha_fin = request.GET.get('fecha_fin')
        estado = request.GET.get('estado')

        if tipo and tipo in TipoMovimiento.values():
            movimientos = movimientos.filter(tipo=tipo)
        if fecha_inicio:
            fecha_inicio_parsed = parse_date(fecha_inicio)
            if not fecha_inicio_parsed:
                logger.warning(f"Filtro de fecha_inicio inválido: {fecha_inicio} por {user.username}")
                messages.error(request, _("Formato de fecha de inicio inválido (use AAAA-MM-DD)."))
                return HttpResponse(status=400)
            movimientos = movimientos.filter(fecha__gte=fecha_inicio_parsed)
        if fecha_fin:
            fecha_fin_parsed = parse_date(fecha_fin)
            if not fecha_fin_parsed:
                logger.warning(f"Filtro de fecha_fin inválido: {fecha_fin} por {user.username}")
                messages.error(request, _("Formato de fecha final inválido (use AAAA-MM-DD)."))
                return HttpResponse(status=400)
            movimientos = movimientos.filter(fecha__lte=fecha_fin_parsed)
        if estado in ['conciliado', 'pendiente']:
            conciliado = estado == 'conciliado'
            movimientos = movimientos.filter(conciliado=conciliado)

        # Validar si hay movimientos para exportar
        if not movimientos.exists():
            logger.warning(f"Usuario {user.username} intentó exportar CSV sin movimientos filtrados.")
            messages.warning(request, _("No hay movimientos para exportar con los filtros seleccionados."))
            return HttpResponse(status=204)

        # Generar CSV
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = (
            f'attachment; filename="movimientos_wallet_{user.username}_{timezone.now().strftime("%Y%m%d")}.csv"'
        )
        writer = csv.writer(response)
        writer.writerow([
            _('ID'), _('Tipo'), _('Monto'), _('Referencia'),
            _('Creado Por'), _('Fecha'), _('Estado')
        ])

        for movimiento in movimientos:
            creado_por = movimiento.creado_por.username if movimiento.creado_por else _("Sistema")
            estado = _("Conciliado") if movimiento.conciliado else _("Pendiente")
            writer.writerow([
                str(movimiento.id),
                movimiento.tipo,
                f"{movimiento.monto:,.2f}",
                movimiento.referencia or '-',
                creado_por,
                movimiento.fecha.strftime('%Y-%m-%d %H:%M'),
                estado
            ])

        logger.info(f"Usuario {user.username} exportó movimientos a CSV.")
        return response
