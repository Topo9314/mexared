"""
Administración avanzada financiera para el módulo Wallet de MexaRed.
Proporciona un visor de auditoría optimizado para billeteras y movimientos financieros.
Permite recargas y transferencias jerárquicas controladas por superusuarios vía acciones administrativas.
Diseñado para trazabilidad completa, cumplimiento regulatorio (PCI DSS, SOC2, ISO 27001, SAT),
y escalabilidad en entornos SaaS multinivel.
Uses only @admin.register to avoid AlreadyRegistered errors.
"""

import logging
from django.contrib import admin
from django import forms
from django.contrib import messages
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.shortcuts import render, redirect
from django.db import transaction
from django.urls import reverse
from decimal import Decimal
from apps.wallet.models import Wallet, WalletMovement
from apps.wallet.enums import TipoMovimiento
from apps.wallet.services import WalletService
from apps.users.models import User, ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR, ROLE_CLIENTE, UserChangeLog
from apps.wallet.exceptions import WalletException

# Configuración avanzada de logging para auditoría empresarial
logger = logging.getLogger(__name__)

class RecargaAdminForm(forms.Form):
    """
    Formulario para recargar saldo a una billetera desde el Django Admin.
    Usado en la acción administrativa 'recargar_saldo' para superusuarios.
    """
    monto = forms.DecimalField(
        label=_("Monto a recargar (MXN)"),
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0.01'),
        max_value=Decimal('1000000.00'),
        help_text=_("Monto en MXN a acreditar en la billetera (mínimo 0.01, máximo 1,000,000)."),
        widget=forms.NumberInput(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ejemplo: 1000.00"),
            'step': '0.01',
        })
    )
    referencia = forms.CharField(
        label=_("Referencia externa (opcional)"),
        max_length=255,
        required=False,
        help_text=_("Identificador externo, e.g., ID de transacción MercadoPago."),
        widget=forms.TextInput(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ejemplo: MP-1234567890"),
        })
    )

    def clean(self):
        """
        Valida la integridad de los datos de entrada.
        """
        cleaned_data = super().clean()
        referencia = cleaned_data.get('referencia')
        if referencia and not referencia.strip():
            raise forms.ValidationError(_("La referencia no puede estar vacía si se proporciona."), code='empty_referencia')
        return cleaned_data

class TransferenciaAdminForm(forms.Form):
    """
    Formulario para transferir saldo entre billeteras desde el Django Admin.
    Usado en la acción administrativa 'transferir_saldo' para superusuarios.
    """
    destino = forms.ModelChoiceField(
        queryset=User.objects.filter(rol__in=[ROLE_VENDEDOR, ROLE_CLIENTE], is_active=True).select_related('wallet'),
        label=_("Usuario Destino"),
        help_text=_("Selecciona el usuario al que deseas transferir saldo (Vendedor o Cliente activo)."),
        widget=forms.Select(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
        })
    )
    monto = forms.DecimalField(
        label=_("Monto a transferir (MXN)"),
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0.01'),
        max_value=Decimal('1000000.00'),
        help_text=_("Monto en MXN a transferir (mínimo 0.01, máximo 1,000,000)."),
        widget=forms.NumberInput(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ejemplo: 1000.00"),
            'step': '0.01',
        })
    )
    referencia = forms.CharField(
        label=_("Referencia (opcional)"),
        max_length=255,
        required=False,
        help_text=_("Identificador externo, e.g., ID de transacción interna."),
        widget=forms.TextInput(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ejemplo: TX-1234567890"),
        })
    )

    def clean(self):
        """
        Valida la integridad de los datos de entrada.
        """
        cleaned_data = super().clean()
        monto = cleaned_data.get('monto')
        referencia = cleaned_data.get('referencia')
        destino = cleaned_data.get('destino')

        if referencia and not referencia.strip():
            raise forms.ValidationError(_("La referencia no puede estar vacía si se proporciona."), code='empty_referencia')
        if destino:
            try:
                destino.wallet
            except Wallet.DoesNotExist:
                raise forms.ValidationError(
                    _("El usuario destino no tiene una billetera asociada."), code='no_wallet_destino'
                )
        return cleaned_data

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    """
    Interfaz administrativa para el modelo Wallet.
    Permite monitoreo, auditoría, recargas y transferencias jerárquicas de billeteras con acceso controlado.
    Incluye acciones administrativas para recargar y transferir saldos por superusuarios.
    """
    list_display = ('user_display', 'balance_display', 'blocked_balance_display', 'hierarchy_root_display', 'last_updated')
    search_fields = ('user__username', 'user__email', 'user__first_name', 'user__last_name')
    list_filter = ('user__rol',)
    readonly_fields = ('user', 'hierarchy_root', 'balance', 'blocked_balance', 'last_updated')
    ordering = ('-last_updated',)
    list_per_page = 50
    list_select_related = ('user', 'hierarchy_root')
    actions = ['recargar_saldo', 'transferir_saldo']

    def get_queryset(self, request):
        """
        Optimiza consultas con select_related para usuario y jerarquía.
        """
        return super().get_queryset(request).select_related('user', 'hierarchy_root')

    @admin.display(description=_("Usuario"))
    def user_display(self, obj):
        """
        Muestra el username y rol del usuario con enlace seguro al perfil.
        """
        name = obj.user.username
        rol = obj.user.get_rol_display()
        return format_html('<a href="/admin/users/user/{}/change/">{} ({})</a>', obj.user.id, name, rol)

    @admin.display(description=_("Saldo disponible"))
    def balance_display(self, obj):
        """
        Formatea el saldo disponible con precisión financiera.
        """
        return f"${obj.balance:,.2f} MXN"

    @admin.display(description=_("Saldo bloqueado"))
    def blocked_balance_display(self, obj):
        """
        Formatea el saldo bloqueado con precisión financiera.
        """
        return f"${obj.blocked_balance:,.2f} MXN"

    @admin.display(description=_("Jerarquía superior"))
    def hierarchy_root_display(self, obj):
        """
        Muestra el username y rol del hierarchy_root, o '-' si no existe.
        """
        if obj.hierarchy_root:
            name = obj.hierarchy_root.username
            rol = obj.hierarchy_root.get_rol_display()
            return format_html('<a href="/admin/users/user/{}/change/">{} ({})</a>', obj.hierarchy_root.id, name, rol)
        return "-"

    def has_add_permission(self, request):
        """
        Permite creación manual solo para superusuarios.
        """
        if request.user.is_superuser:
            logger.info(f"Permiso de creación de billetera concedido a {request.user.username}")
            return True
        logger.warning(f"Intento de creación de billetera denegado para {request.user.username}")
        return False

    def has_change_permission(self, request, obj=None):
        """
        Deshabilita edición directa para proteger integridad financiera.
        """
        logger.warning(f"Intento de edición de billetera denegado para {request.user.username}")
        return False

    def has_delete_permission(self, request, obj=None):
        """
        Deshabilita eliminación para mantener trazabilidad.
        """
        logger.warning(f"Intento de eliminación de billetera denegado para {request.user.username}")
        return False

    @admin.action(description=_("Recargar saldo seleccionado"))
    def recargar_saldo(self, request, queryset):
        """
        Acción administrativa para recargar saldo en una billetera seleccionada.
        Restringida a superusuarios con rol ROLE_ADMIN, usa WalletService.deposit para trazabilidad.
        """
        if not request.user.is_superuser or request.user.rol != ROLE_ADMIN:
            logger.warning(f"Intento de recarga denegado para {request.user.username} (no superusuario o no ROLE_ADMIN)")
            messages.error(request, _("Solo administradores pueden realizar recargas."))
            return

        if queryset.count() != 1:
            logger.warning(f"Selección inválida para recarga por {request.user.username}: {queryset.count()} billeteras")
            messages.warning(request, _("Selecciona solo una billetera para recargar."))
            return

        wallet = queryset.first()
        if wallet.user.rol != ROLE_DISTRIBUIDOR:
            logger.warning(f"Intento de recarga a billetera no Distribuidor por {request.user.username}: {wallet.user.rol}")
            messages.error(request, _("Solo se puede recargar a billeteras de Distribuidores."))
            return

        if request.method == "POST":
            form = RecargaAdminForm(request.POST)
            if form.is_valid():
                with transaction.atomic():
                    monto = form.cleaned_data['monto']
                    referencia = form.cleaned_data['referencia'] or None
                    try:
                        WalletService.deposit(
                            wallet=wallet,
                            amount=monto,
                            creado_por=request.user,
                            referencia=referencia,
                            actor_ip=request.META.get('REMOTE_ADDR', 'unknown'),
                            device_info=request.META.get('HTTP_USER_AGENT', 'Django Admin'),
                            moneda_codigo='MXN'
                        )
                        # Registrar auditoría adicional
                        UserChangeLog.objects.create(
                            user=wallet.user,
                            changed_by=request.user,
                            change_type='update',
                            change_description=_(f"Recarga de saldo: {monto} MXN"),
                            details={
                                'monto': str(monto),
                                'referencia': referencia or 'N/A',
                                'wallet_id': wallet.id
                            }
                        )
                        logger.info(
                            f"Recarga exitosa por {request.user.username}: {monto} MXN a {wallet.user.username} "
                            f"(wallet_id: {wallet.id}, referencia: {referencia or 'N/A'})"
                        )
                        messages.success(
                            request,
                            _("Saldo recargado correctamente: %(monto)s MXN.") % {'monto': f"${monto:,.2f}"}
                        )
                        return redirect("admin:wallet_wallet_changelist")
                    except WalletException as e:
                        logger.error(
                            f"Error en recarga por {request.user.username} para {wallet.user.username}: {str(e)}",
                            exc_info=True
                        )
                        messages.error(request, _("Error al recargar saldo: %(error)s") % {'error': str(e)})
                    except Exception as e:
                        logger.error(
                            f"Error inesperado en recarga por {request.user.username} para {wallet.user.username}: {str(e)}",
                            exc_info=True
                        )
                        messages.error(request, _("Error inesperado al procesar la operación."))
            else:
                logger.debug(f"Formulario de recarga inválido para {request.user.username}: {form.errors}")
                messages.error(request, _("Por favor corrige los errores en el formulario."))
        else:
            form = RecargaAdminForm()

        context = {
            'form': form,
            'wallet': wallet,
            'title': _("Recargar Saldo"),
            'action': 'recargar_saldo',
            'opts': self.model._meta,
            'app_label': self.model._meta.app_label,
            'cl': self.get_changelist_instance(request),
            'site_title': admin.site.site_title,
            'site_url': '/',
            'has_view_permission': self.has_view_permission(request, wallet),
        }
        context.update(self.admin_site.each_context(request))
        return render(request, "admin/wallet/recargar_saldo.html", context)

    @admin.action(description=_("Transferir saldo seleccionado"))
    def transferir_saldo(self, request, queryset):
        """
        Acción administrativa para transferir saldo desde una billetera origen a una destino.
        Restringida a superusuarios con rol ROLE_ADMIN, usa WalletService.transfer para validar jerarquía.
        """
        if not request.user.is_superuser or request.user.rol != ROLE_ADMIN:
            logger.warning(f"Intento de transferencia denegado para {request.user.username} (no superusuario o no ROLE_ADMIN)")
            messages.error(request, _("Solo administradores pueden realizar transferencias."))
            return

        if queryset.count() != 1:
            logger.warning(f"Selección inválida para transferencia por {request.user.username}: {queryset.count()} billeteras")
            messages.warning(request, _("Selecciona solo una billetera origen para transferir."))
            return

        origen_wallet = queryset.first()
        if origen_wallet.user.rol != ROLE_DISTRIBUIDOR:
            logger.warning(f"Intento de transferencia desde billetera no Distribuidor por {request.user.username}: {origen_wallet.user.rol}")
            messages.error(request, _("Solo se permite transferir desde billeteras de Distribuidores."))
            return

        if request.method == "POST":
            form = TransferenciaAdminForm(request.POST)
            if form.is_valid():
                with transaction.atomic():
                    destino_user = form.cleaned_data['destino']
                    destino_wallet = destino_user.wallet
                    monto = form.cleaned_data['monto']
                    referencia = form.cleaned_data['referencia'] or None

                    try:
                        WalletService.transfer(
                            origen_wallet=origen_wallet,
                            destino_wallet=destino_wallet,
                            amount=monto,
                            creado_por=request.user,
                            referencia=referencia,
                            actor_ip=request.META.get('REMOTE_ADDR', 'unknown'),
                            device_info=request.META.get('HTTP_USER_AGENT', 'Django Admin')
                        )
                        # Registrar auditoría adicional
                        UserChangeLog.objects.create(
                            user=destino_user,
                            changed_by=request.user,
                            change_type='update',
                            change_description=_(f"Transferencia recibida: {monto} MXN desde {origen_wallet.user.username}"),
                            details={
                                'monto': str(monto),
                                'referencia': referencia or 'N/A',
                                'origen_wallet_id': origen_wallet.id,
                                'destino_wallet_id': destino_wallet.id
                            }
                        )
                        logger.info(
                            f"Transferencia exitosa por {request.user.username}: {monto} MXN de {origen_wallet.user.username} "
                            f"a {destino_user.username} (referencia: {referencia or 'N/A'})"
                        )
                        messages.success(
                            request,
                            _("Transferencia exitosa de %(monto)s MXN a %(destino)s.") % {
                                'monto': f"${monto:,.2f}",
                                'destino': destino_user.username
                            }
                        )
                        return redirect("admin:wallet_wallet_changelist")
                    except WalletException as e:
                        logger.error(
                            f"Error en transferencia por {request.user.username} de {origen_wallet.user.username} "
                            f"a {destino_user.username}: {str(e)}",
                            exc_info=True
                        )
                        messages.error(request, _("Error en transferencia: %(error)s") % {'error': str(e)})
                    except Exception as e:
                        logger.error(
                            f"Error inesperado en transferencia por {request.user.username} de {origen_wallet.user.username} "
                            f"a {destino_user.username}: {str(e)}",
                            exc_info=True
                        )
                        messages.error(request, _("Error inesperado al procesar la operación."))
            else:
                logger.debug(f"Formulario de transferencia inválido para {request.user.username}: {form.errors}")
                messages.error(request, _("Por favor corrige los errores en el formulario."))
        else:
            form = TransferenciaAdminForm()

        context = {
            'form': form,
            'origen_wallet': origen_wallet,
            'title': _("Transferir Saldo"),
            'action': 'transferir_saldo',
            'opts': self.model._meta,
            'app_label': self.model._meta.app_label,
            'cl': self.get_changelist_instance(request),
            'site_title': admin.site.site_title,
            'site_url': '/',
            'has_view_permission': self.has_view_permission(request, origen_wallet),
        }
        context.update(self.admin_site.each_context(request))
        return render(request, "admin/wallet/transferir_saldo.html", context)

@admin.register(WalletMovement)
class WalletMovementAdmin(admin.ModelAdmin):
    """
    Interfaz administrativa para el modelo WalletMovement.
    Permite auditar movimientos financieros con filtros avanzados y optimización para grandes volúmenes.
    """
    list_display = ('short_id', 'wallet_display', 'tipo_display', 'monto_display', 'referencia', 'conciliado_display', 'fecha')
    search_fields = ('wallet__user__username', 'wallet__user__email', 'referencia', 'operacion_id')
    list_filter = ('tipo', 'conciliado', 'fecha')
    readonly_fields = (
        'wallet', 'tipo', 'monto', 'referencia', 'operacion_id',
        'fecha', 'creado_por', 'actor_ip', 'device_info', 'origen_wallet',
        'conciliado', 'fecha_conciliacion'
    )
    ordering = ('-fecha',)
    list_per_page = 50
    date_hierarchy = 'fecha'
    list_select_related = ('wallet__user', 'creado_por', 'origen_wallet__user')

    def get_queryset(self, request):
        """
        Optimiza consultas con select_related para billetera, creador y origen.
        """
        return super().get_queryset(request).select_related('wallet__user', 'creado_por', 'origen_wallet__user')

    @admin.display(description=_("ID Movimiento"))
    def short_id(self, obj):
        """
        Muestra un ID abreviado para facilitar lectura.
        """
        return str(obj.id)[:8]

    @admin.display(description=_("Billetera"))
    def wallet_display(self, obj):
        """
        Muestra el username de la billetera con enlace seguro al perfil.
        """
        name = obj.wallet.user.username
        return format_html('<a href="/admin/users/user/{}/change/">{}</a>', obj.wallet.user.id, name)

    @admin.display(description=_("Tipo"))
    def tipo_display(self, obj):
        """
        Muestra el tipo de movimiento traducido con manejo de excepciones.
        """
        try:
            return TipoMovimiento[obj.tipo].label
        except KeyError:
            logger.warning(f"Tipo de movimiento inválido para ID {obj.id}: {obj.tipo}")
            return _("Desconocido")

    @admin.display(description=_("Monto"))
    def monto_display(self, obj):
        """
        Formatea el monto con precisión financiera.
        """
        return f"${obj.monto:,.2f} MXN"

    @admin.display(description=_("Estado conciliación"))
    def conciliado_display(self, obj):
        """
        Muestra el estado de conciliación de forma legible.
        """
        return _("Conciliado") if obj.conciliado else _("Pendiente")

    def has_add_permission(self, request):
        """
        Deshabilita creación manual de movimientos.
        """
        logger.warning(f"Intento de creación de movimiento denegado para {request.user.username}")
        return False

    def has_change_permission(self, request, obj=None):
        """
        Deshabilita edición de movimientos para proteger integridad financiera.
        """
        logger.warning(f"Intento de edición de movimiento denegado para {request.user.username}")
        return False

    def has_delete_permission(self, request, obj=None):
        """
        Deshabilita eliminación de movimientos para mantener trazabilidad.
        """
        logger.warning(f"Intento de eliminación de movimiento denegado para {request.user.username}")
        return False