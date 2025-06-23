"""
Panel de administración para la app transacciones en MexaRed.
Proporciona una interfaz profesional, segura y escalable para gestionar transacciones financieras,
historiales de saldo, monedas, motivos y auditorías internas. Diseñado para entornos empresariales
de alto volumen con soporte multi-moneda y auditoría detallada.
Permite a superusuarios crear transacciones tipo CARGA para recargar saldo a distribuidores manualmente,
utilizando formularios inteligentes para validaciones robustas, y una interfaz dedicada para añadir saldo
con selección de moneda, auditoría avanzada y comentarios administrativos.
"""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.utils.timezone import localtime, now
from django.urls import path, reverse
from django.shortcuts import redirect, render
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django import forms
import json
import logging
from decimal import Decimal

from apps.transacciones.models import Transaccion, HistorialSaldo, Moneda, MotivoTransaccion, AuditoriaTransaccion
from apps.transacciones.forms import TransaccionForm, MotivoTransaccionForm
from apps.transacciones.services import asignar_saldo
from apps.users.models import User
from apps.vendedores.models import DistribuidorVendedor

# Configuración del logger para auditoría profesional
logger = logging.getLogger(__name__)

# ============================
# 🔹 PERSONALIZACIÓN VISUAL
# ============================

admin.site.site_title = _("Administración MexaRed")
admin.site.site_header = _("Panel de Administración MexaRed - Transacciones")
admin.site.index_title = _("Gestión de Transacciones Financieras")

# ============================
# 🔹 FORMULARIO PARA CARGAR SALDO
# ============================

class CargarSaldoDistribuidorForm(forms.Form):
    """
    Formulario personalizado para cargar saldo a distribuidores desde el panel de administración.
    Incluye validaciones robustas y soporte multi-moneda.
    """
    distribuidor = forms.ModelChoiceField(
        queryset=User.objects.filter(rol='distribuidor', activo=True).order_by('username'),
        label=_("Distribuidor"),
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'data-testid': 'distribuidor-select',
        })
    )
    monto = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0.01'),
        label=_("Monto"),
        widget=forms.NumberInput(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'step': '0.01',
            'placeholder': _("Ej. 1000.00"),
            'data-testid': 'monto-input',
        })
    )
    moneda = forms.ModelChoiceField(
        queryset=Moneda.objects.all().order_by('codigo'),
        label=_("Moneda"),
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'data-testid': 'moneda-select',
        })
    )
    motivo = forms.ModelChoiceField(
        queryset=MotivoTransaccion.objects.filter(activo=True).order_by('codigo'),
        required=False,
        label=_("Motivo"),
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'data-testid': 'motivo-select',
        })
    )
    descripcion = forms.CharField(
        label=_("Comentario/Justificación"),
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'rows': 4,
            'placeholder': _("Ingrese una justificación para la carga de saldo (opcional)."),
            'data-testid': 'descripcion-textarea',
        })
    )

    def clean(self):
        """Valida la consistencia del formulario."""
        cleaned_data = super().clean()
        distribuidor = cleaned_data.get('distribuidor')
        moneda = cleaned_data.get('moneda')
        monto = cleaned_data.get('monto')

        if distribuidor and moneda:
            try:
                profile = distribuidor.perfil_distribuidor
                if profile.moneda != moneda.codigo:
                    raise ValidationError(
                        _("La moneda seleccionada no coincide con la moneda del perfil del distribuidor (%s).")
                        % profile.moneda
                    )
            except AttributeError:
                raise ValidationError(_("El distribuidor seleccionado no tiene un perfil asociado."))

        if monto and monto <= 0:
            raise ValidationError(_("El monto debe ser mayor a cero."))

        return cleaned_data

# ============================
# 🔹 ADMIN PARA TRANSACCIÓN
# ============================

@admin.register(Transaccion)
class TransaccionAdmin(admin.ModelAdmin):
    """
    Administración para el modelo Transaccion.
    Permite crear, visualizar, filtrar, buscar y auditar transacciones financieras con formato profesional.
    Utiliza TransaccionForm para validaciones avanzadas y soporte para transacciones tipo CARGA.
    Incluye una interfaz dedicada para cargar saldo a distribuidores con auditoría avanzada.
    """
    form = TransaccionForm
    list_display = (
        'uuid_short',
        'tipo_display',
        'monto_formatted',
        'moneda_display',
        'emisor_display',
        'receptor_display',
        'motivo_display',
        'estado_coloreado',
        'fecha_creacion_local',
    )
    list_filter = (
        'tipo',
        'estado',
        'moneda',
        'emisor__rol',
        'receptor__rol',
        'motivo',
        'fecha_creacion',
    )
    search_fields = (
        'uuid',
        'emisor__username',
        'receptor__username',
        'referencia_externa',
        'motivo__codigo',
        'motivo__descripcion',
        'descripcion',
    )
    readonly_fields = (
        'uuid',
        'fecha_creacion',
        'fecha_actualizacion',
        'fecha_creacion_local',
        'fecha_actualizacion_local',
    )
    ordering = ('-fecha_creacion',)
    list_per_page = 25
    date_hierarchy = 'fecha_creacion'
    list_select_related = ('emisor', 'receptor', 'moneda', 'motivo', 'realizado_por')
    actions = ['asignar_saldo_vendedores']

    fieldsets = (
        (_("Información Principal"), {
            'fields': (
                'uuid',
                'tipo',
                'motivo',
                'estado',
                'descripcion',
            )
        }),
        (_("Detalles Financieros"), {
            'fields': (
                'monto',
                'moneda',
                'tasa_cambio',
            )
        }),
        (_("Usuarios Involucrados"), {
            'fields': (
                'emisor',
                'receptor',
                'realizado_por',
            )
        }),
        (_("Referencias y Auditoría"), {
            'fields': (
                'referencia_externa',
                'fecha_creacion_local',
                'fecha_actualizacion_local',
            )
        }),
    )

    def get_form(self, request, obj=None, **kwargs):
        """Pasa el usuario autenticado al formulario para validaciones dinámicas."""
        kwargs['form'] = self.form
        form = super().get_form(request, obj, **kwargs)
        form.user = request.user
        return form

    def get_urls(self):
        """Añade URL personalizada para cargar saldo."""
        urls = super().get_urls()
        custom_urls = [
            path(
                'cargar-saldo-distribuidor/',
                self.admin_site.admin_view(self.cargar_saldo_view),
                name='cargar-saldo-distribuidor'
            ),
        ]
        return custom_urls + urls

    def cargar_saldo_view(self, request):
        """Vista para cargar saldo a distribuidores desde el admin."""
        if not request.user.is_superuser:
            messages.error(request, _("Solo superusuarios pueden cargar saldo a distribuidores."))
            logger.warning(
                f"[{now()}] Intento no autorizado de cargar saldo por {request.user.username} "
                f"(IP: {request.META.get('REMOTE_ADDR', 'N/A')}, "
                f"User-Agent: {request.META.get('HTTP_USER_AGENT', 'N/A')})"
            )
            return redirect('admin:transacciones_transaccion_changelist')

        if request.method == 'POST':
            form = CargarSaldoDistribuidorForm(request.POST)
            if form.is_valid():
                try:
                    with transaction.atomic():
                        distribuidor = form.cleaned_data['distribuidor']
                        monto = form.cleaned_data['monto']
                        moneda = form.cleaned_data['moneda']
                        motivo = form.cleaned_data['motivo']
                        descripcion = form.cleaned_data['descripcion'] or \
                            f"Carga manual de saldo por {request.user.username} el {now().strftime('%Y-%m-%d %H:%M:%S')}"

                        # Crear transacción
                        transaccion = Transaccion.objects.create(
                            uuid=uuid.uuid4(),
                            tipo='CARGA',
                            estado='EXITOSA',
                            emisor=None,  # No hay emisor específico en cargas admin
                            receptor=distribuidor,
                            monto=monto,
                            moneda=moneda,
                            motivo=motivo,
                            descripcion=descripcion,
                            realizado_por=request.user
                        )

                        # Actualizar saldo del distribuidor
                        profile = distribuidor.perfil_distribuidor
                        saldo_before = profile.saldo_actual
                        profile.saldo_actual += monto
                        profile.save(update_fields=['saldo_actual'])

                        # Registrar historial de saldo
                        HistorialSaldo.objects.create(
                            usuario=distribuidor,
                            saldo_antes=saldo_before,
                            saldo_despues=profile.saldo_actual,
                            transaccion=transaccion
                        )

                        # Registrar auditoría
                        AuditoriaTransaccion.objects.create(
                            transaccion=transaccion,
                            tipo='CREACION',
                            usuario=request.user,
                            detalles={
                                'evento': 'Carga de saldo desde admin',
                                'monto': str(monto),
                                'moneda': moneda.codigo,
                                'distribuidor': distribuidor.username,
                                'ip': request.META.get('REMOTE_ADDR', 'N/A'),
                                'user_agent': request.META.get('HTTP_USER_AGENT', 'N/A')
                            }
                        )

                        messages.success(
                            request,
                            _(f"Saldo cargado exitosamente: {monto} {moneda.codigo} a {distribuidor.username}.")
                        )
                        logger.info(
                            f"[{now()}] Carga de saldo exitosa por {request.user.username}: "
                            f"{monto} {moneda.codigo} a {distribuidor.username} "
                            f"(UUID: {transaccion.uuid})"
                        )
                        return redirect('admin:transacciones_transaccion_changelist')
                except ValidationError as e:
                    messages.error(request, str(e))
                    logger.error(
                        f"[{now()}] Error al cargar saldo por {request.user.username}: {str(e)}"
                    )
                except Exception as e:
                    messages.error(request, _("Error inesperado al procesar la carga de saldo: ") + str(e))
                    logger.error(
                        f"[{now()}] Error inesperado al cargar saldo por {request.user.username}: {str(e)}"
                    )
        else:
            form = CargarSaldoDistribuidorForm()

        context = {
            **self.admin_site.each_context(request),
            'title': _("Cargar Saldo a Distribuidor"),
            'form': form,
            'opts': self.model._meta,
            'app_label': self.model._meta.app_label,
        }
        return render(request, 'admin/transacciones/cargar_saldo.html', context)

    def uuid_short(self, obj):
        """Muestra los primeros 8 caracteres del UUID."""
        return str(obj.uuid)[:8]
    uuid_short.short_description = _("UUID")

    def tipo_display(self, obj):
        """Muestra el nombre legible del tipo de transacción."""
        return obj.get_tipo_display()
    tipo_display.short_description = _("Tipo")

    def monto_formatted(self, obj):
        """Formatea el monto con el símbolo de la moneda."""
        return f"{obj.moneda.simbolo}{obj.monto:,.2f}" if obj.moneda else f"{obj.monto:,.2f}"
    monto_formatted.short_description = _("Monto")

    def moneda_display(self, obj):
        """Muestra el código de la moneda."""
        return obj.moneda.codigo if obj.moneda else '—'
    moneda_display.short_description = _("Moneda")

    def emisor_display(self, obj):
        """Muestra el username del emisor como enlace al perfil."""
        if obj.emisor:
            url = reverse('admin:users_user_change', args=[obj.emisor.pk])
            return format_html('<a href="{}">{}</a>', url, obj.emisor.username)
        return '—'
    emisor_display.short_description = _("Emisor")

    def receptor_display(self, obj):
        """Muestra el username del receptor como enlace al perfil."""
        if obj.receptor:
            url = reverse('admin:users_user_change', args=[obj.receptor.pk])
            return format_html('<a href="{}">{}</a>', url, obj.receptor.username)
        return '—'
    receptor_display.short_description = _("Receptor")

    def motivo_display(self, obj):
        """Muestra la descripción del motivo."""
        return obj.motivo.descripcion if obj.motivo else '—'
    motivo_display.short_description = _("Motivo")

    def estado_coloreado(self, obj):
        """Muestra el estado con color según su valor."""
        colors = {
            'EXITOSA': 'green',
            'PENDIENTE': 'blue',
            'FALLIDA': 'red',
            'CANCELADA': 'gray',
        }
        color = colors.get(obj.estado, 'black')
        return format_html(
            '<strong style="color:{}">{}</strong>',
            color, obj.get_estado_display()
        )
    estado_coloreado.short_description = _("Estado")

    def fecha_creacion_local(self, obj):
        """Muestra la fecha de creación en formato local."""
        return localtime(obj.fecha_creacion).strftime("%Y-%m-%d %H:%M:%S")
    fecha_creacion_local.short_description = _("Fecha Creación")

    def fecha_actualizacion_local(self, obj):
        """Muestra la fecha de actualización en formato local."""
        return localtime(obj.fecha_actualización).strftime("%Y-%m-%d %H:%M:%S")
    fecha_actualizacion_local.short_description = _("Fecha Actualización")

    def get_queryset(self, request):
        """Optimiza la consulta con select_related."""
        return super().get_queryset(request).select_related(
            'emisor', 'receptor', 'moneda', 'motivo', 'realizado_por'
        )

    def save_model(self, request, obj, form, change):
        """
        Valida y procesa la creación o actualización de transacciones, asegurando que las transacciones
        tipo CARGA sean manejadas correctamente con auditoría y actualización de saldo.
        """
        if not request.user.is_superuser:
            self.message_user(
                request, _("Solo superusers pueden modificar transacciones."), level=messages.ERROR
            )
            return

        if not change:  # Solo para creación de nuevas transacciones
            if obj.tipo != 'CARGA':
                self.message_user(
                    request, _("Solo se pueden crear transacciones de tipo CARGA desde el admin."), level=messages.ERROR
                )
                return

            if not obj.receptor or obj.receptor.rol != 'distribuidor':
                self.message_user(
                    request, _("El receptor debe ser un usuario con rol distribuidor."), level=messages.ERROR
                )
                return

            if obj.estado not in ['EXITOSA', 'PENDIENTE']:
                self.message_user(
                    request, _("El estado debe ser EXITOSA o PENDIENTE."), level=messages.ERROR
                )
                return

        try:
            with transaction.atomic():
                obj.realizado_por = request.user
                super().save_model(request, obj, form, change)

                if not change and obj.estado == 'EXITOSA':
                    # Actualizar saldo del distribuidor para transacciones CARGA exitosas
                    try:
                        profile = obj.receptor.perfil_distribuidor
                        if profile.moneda != obj.moneda.codigo:
                            raise ValidationError(
                                _("La moneda seleccionada no coincide con la del perfil del distribuidor.")
                            )
                        saldo_before = profile.saldo_actual
                        profile.saldo_actual += obj.monto
                        profile.save(update_fields=['saldo_actual'])

                        # Registrar historial de saldo
                        HistorialSaldo.objects.create(
                            usuario=obj.receptor,
                            saldo_antes=saldo_before,
                            saldo_despues=profile.saldo_actual,
                            transaccion=obj
                        )

                        # Registrar auditoría
                        AuditoriaTransaccion.objects.create(
                            transaccion=obj,
                            tipo='CREACION',
                            usuario=request.user,
                            detalles={
                                'evento': 'Creación de transacción CARGA desde admin',
                                'monto': str(obj.monto),
                                'moneda': obj.moneda.codigo,
                                'receptor': obj.receptor.username,
                                'ip': request.META.get('REMOTE_ADDR', 'N/A'),
                                'user_agent': request.META.get('HTTP_USER_AGENT', 'N/A')
                            }
                        )

                        self.message_user(
                            request,
                            _(f"Transacción CARGA registrada exitosamente: {obj.monto} {obj.moneda.codigo} "
                              f"al distribuidor {obj.receptor.username}."),
                            level=messages.SUCCESS
                        )
                        logger.info(
                            f"[{now()}] Transacción CARGA creada por {request.user.username}: "
                            f"{obj.monto} {obj.moneda.codigo} a {obj.receptor.username} "
                            f"(UUID: {obj.uuid})"
                        )
                    except AttributeError:
                        raise ValidationError(_("El distribuidor no tiene un perfil asociado."))
        except ValidationError as e:
            self.message_user(request, str(e), level=messages.ERROR)
            logger.error(
                f"[{now()}] Error al procesar transacción CARGA por {request.user.username}: {str(e)} "
                f"(UUID: {obj.uuid})"
            )

    def asignar_saldo_vendedores(self, request, queryset):
        """
        Acción para asignar saldo a vendedores desde la selección de transacciones.
        Solo permite procesar transacciones de tipo ASIGNACION con un receptor válido.
        """
        if not request.user.is_superuser:
            self.message_user(request, _("Solo superusers pueden asignar saldo."), level=messages.ERROR)
            return

        for transaccion in queryset:
            if transaccion.tipo != 'ASIGNACION' or not transaccion.receptor:
                self.message_user(
                    request,
                    _(f"La transacción {transaccion.uuid} no es una asignación válida o no tiene receptor."),
                    level=messages.ERROR
                )
                continue

            try:
                distribuidor = transaccion.emisor
                vendedor = transaccion.receptor
                if not DistribuidorVendedor.objects.filter(
                    distribuidor=distribuidor, vendedor=vendedor, activo=True
                ).exists():
                    self.message_user(
                        request,
                        _(f"No existe una relación activa entre {distribuidor.username} y {vendedor.username}."),
                        level=messages.ERROR
                    )
                    continue

                asignar_saldo(
                    distribuidor=distribuidor,
                    vendedor=vendedor,
                    monto=transaccion.monto,
                    moneda=transaccion.moneda,
                    realizado_por=request.user,
                    motivo=transaccion.motivo,
                    descripcion=transaccion.descripcion or _("Asignación desde panel admin")
                )
                self.message_user(
                    request,
                    _(f"Saldo asignado exitosamente: {transaccion.monto} {transaccion.moneda.codigo} "
                      f"a {vendedor.username} desde {distribuidor.username}."),
                    level=messages.SUCCESS
                )
                logger.info(
                    f"[{now()}] Saldo asignado desde admin por {request.user.username}: "
                    f"{transaccion.monto} {transaccion.moneda.codigo} a {vendedor.username} "
                    f"desde {distribuidor.username} (UUID: {transaccion.uuid})"
                )
            except ValidationError as e:
                self.message_user(request, str(e), level=messages.ERROR)
                logger.error(
                    f"[{now()}] Error al asignar saldo desde admin por {request.user.username}: {str(e)} "
                    f"(UUID: {transaccion.uuid})"
                )

    asignar_saldo_vendedores.short_description = _("Asignar saldo a vendedores seleccionados")

# ============================
# 🔹 ADMIN PARA HISTORIALSALDO
# ============================

@admin.register(HistorialSaldo)
class HistorialSaldoAdmin(admin.ModelAdmin):
    """
    Administración para el modelo HistorialSaldo.
    Permite auditar cambios en los saldos de usuarios con trazabilidad detallada.
    """
    list_display = (
        'usuario_display',
        'saldo_antes_formatted',
        'saldo_despues_formatted',
        'tipo_display',
        'uuid_transaccion_short',
        'fecha_local',
    )
    list_filter = (
        ('usuario__rol', admin.RelatedOnlyFieldListFilter),
        'transaccion__tipo',
        'fecha',
    )
    search_fields = (
        'usuario__username',
        'transaccion__uuid',
        'transaccion__motivo__codigo',
    )
    readonly_fields = (
        'usuario_display',
        'saldo_antes_formatted',
        'saldo_despues_formatted',
        'transaccion_display',
        'fecha_local',
    )
    ordering = ('-fecha',)
    list_per_page = 25
    date_hierarchy = 'fecha'
    list_select_related = ('usuario', 'transaccion', 'transaccion__moneda')

    fieldsets = (
        (_("Información del Saldo"), {
            'fields': ('usuario_display', 'saldo_antes_formatted', 'saldo_despues_formatted')
        }),
        (_("Transacción Asociada"), {
            'fields': ('transaccion_display',)
        }),
        (_("Auditoría"), {
            'fields': ('fecha_local',)
        }),
    )

    def usuario_display(self, obj):
        """Muestra el username del usuario como enlace al perfil."""
        url = reverse('admin:users_user_change', args=[obj.usuario.pk])
        return format_html('<a href="{}">{}</a>', url, obj.usuario.username)
    usuario_display.short_description = _("Usuario")

    def saldo_antes_formatted(self, obj):
        """Formatea el saldo antes con la moneda."""
        return f"{obj.transaccion.moneda.simbolo}{obj.saldo_antes:,.2f}" if obj.transaccion.moneda else f"{obj.saldo_antes:,.2f}"
    saldo_antes_formatted.short_description = _("Saldo Antes")

    def saldo_despues_formatted(self, obj):
        """Formatea el saldo después con la moneda."""
        return f"{obj.transaccion.moneda.simbolo}{obj.saldo_despues:,.2f}" if obj.transaccion.moneda else f"{obj.saldo_despues:,.2f}"
    saldo_despues_formatted.short_description = _("Saldo Después")

    def tipo_display(self, obj):
        """Muestra el tipo de transacción asociada."""
        return obj.transaccion.get_tipo_display()
    tipo_display.short_description = _("Tipo de Transacción")

    def uuid_transaccion_short(self, obj):
        """Muestra los primeros 8 caracteres del UUID de la transacción."""
        return str(obj.transaccion.uuid)[:8]
    uuid_transaccion_short.short_description = _("Transacción UUID")

    def transaccion_display(self, obj):
        """Muestra detalles de la transacción como enlace."""
        url = reverse('admin:transacciones_transaccion_change', args=[obj.transaccion.pk])
        return format_html(
            '<a href="{}">{}: {} {} ({})</a>',
            url, obj.transaccion.get_tipo_display(), obj.transaccion.monto,
            obj.transaccion.moneda.codigo if obj.transaccion.moneda else '—', obj.transaccion.get_estado_display()
        )
    transaccion_display.short_description = _("Transacción")

    def fecha_local(self, obj):
        """Muestra la fecha en formato local."""
        return localtime(obj.fecha).strftime("%Y-%m-%d %H:%M:%S")
    fecha_local.short_description = _("Fecha")

    def get_queryset(self, request):
        """Optimiza la consulta con select_related."""
        return super().get_queryset(request).select_related(
            'usuario', 'transaccion', 'transaccion__moneda'
        )

# ============================
# 🔹 ADMIN PARA MONEDA
# ============================

@admin.register(Moneda)
class MonedaAdmin(admin.ModelAdmin):
    """
    Administración para el modelo Moneda.
    Gestiona monedas soportadas para transacciones internacionales.
    """
    list_display = (
        'codigo',
        'nombre',
        'simbolo',
        'tasa_cambio_usd_formatted',
        'fecha_actualizacion_local',
    )
    list_filter = ('fecha_actualizacion',)
    search_fields = ('codigo', 'nombre')
    readonly_fields = ('fecha_actualizacion_local',)
    ordering = ('codigo',)
    list_per_page = 25

    fieldsets = (
        (_("Información de la Moneda"), {
            'fields': ('codigo', 'nombre', 'simbolo', 'tasa_cambio_usd')
        }),
        (_("Auditoría"), {
            'fields': ('fecha_actualizacion_local',)
        }),
    )

    def tasa_cambio_usd_formatted(self, obj):
        """Formatea la tasa de cambio a USD."""
        return f"{obj.tasa_cambio_usd:.4f}"
    tasa_cambio_usd_formatted.short_description = _("Tasa Cambio USD")

    def fecha_actualizacion_local(self, obj):
        """Muestra la fecha de actualización en formato local."""
        return localtime(obj.fecha_actualizacion).strftime("%Y-%m-%d %H:%M:%S")
    fecha_actualizacion_local.short_description = _("Fecha Actualización")

# ============================
# 🔹 ADMIN PARA MOTIVOTRANSACCION
# ============================

@admin.register(MotivoTransaccion)
class MotivoTransaccionAdmin(admin.ModelAdmin):
    """
    Administración para el modelo MotivoTransaccion.
    Gestiona motivos específicos para clasificar transacciones.
    """
    form = MotivoTransaccionForm
    list_display = (
        'codigo',
        'descripcion',
        'activo',
        'fecha_creacion_local',
    )
    list_filter = ('activo', 'fecha_creacion')
    search_fields = ('codigo', 'descripcion')
    readonly_fields = ('fecha_creacion_local',)
    ordering = ('codigo',)
    list_per_page = 25

    fieldsets = (
        (_("Información del Motivo"), {
            'fields': ('codigo', 'descripcion', 'activo')
        }),
        (_("Auditoría"), {
            'fields': ('fecha_creacion_local',)
        }),
    )

    def fecha_creacion_local(self, obj):
        """Muestra la fecha de creación en formato local."""
        return localtime(obj.fecha_creacion).strftime("%Y-%m-%d %H:%M:%S")
    fecha_creacion_local.short_description = _("Fecha Creación")

# ============================
# 🔹 ADMIN PARA AUDITORIATRANSACCION
# ============================

@admin.register(AuditoriaTransaccion)
class AuditoriaTransaccionAdmin(admin.ModelAdmin):
    """
    Administración para el modelo AuditoriaTransaccion.
    Permite auditar acciones internas sobre transacciones con trazabilidad detallada.
    """
    list_display = (
        'transaccion_uuid_short',
        'tipo_display',
        'usuario_display',
        'detalles_preview',
        'fecha_local',
    )
    list_filter = (
        'tipo',
        'fecha',
        ('usuario__rol', admin.RelatedOnlyFieldListFilter),
    )
    search_fields = (
        'transaccion__uuid',
        'usuario__username',
        'detalles',
    )
    readonly_fields = (
        'transaccion_display',
        'tipo_display',
        'usuario_display',
        'detalles_preview',
        'fecha_local',
    )
    ordering = ('-fecha',)
    list_per_page = 50
    date_hierarchy = 'fecha'
    list_select_related = ('transaccion', 'usuario')

    fieldsets = (
        (_("Información de la Auditoría"), {
            'fields': ('transaccion_display', 'tipo_display', 'usuario_display', 'detalles_preview')
        }),
        (_("Auditoría"), {
            'fields': ('fecha_local',)
        }),
    )

    def transaccion_uuid_short(self, obj):
        """Muestra los primeros 8 caracteres del UUID de la transacción."""
        return str(obj.transaccion.uuid)[:8]
    transaccion_uuid_short.short_description = _("Transacción UUID")

    def tipo_display(self, obj):
        """Muestra el nombre legible del tipo de auditoría."""
        return obj.get_tipo_display()
    tipo_display.short_description = _("Tipo")

    def usuario_display(self, obj):
        """Muestra el username del usuario como enlace al perfil."""
        if obj.usuario:
            url = reverse('admin:users_user_change', args=[obj.usuario.pk])
            return format_html('<a href="{}">{}</a>', url, obj.usuario.username)
        return 'Sistema'
    usuario_display.short_description = _("Usuario")

    def transaccion_display(self, obj):
        """Muestra detalles de la transacción como enlace."""
        url = reverse('admin:transacciones_transaccion_change', args=[obj.transaccion.pk])
        return format_html(
            '<a href="{}">{}: {} {} ({})</a>',
            url, obj.transaccion.get_tipo_display(), obj.transaccion.monto,
            obj.transaccion.moneda.codigo if obj.transaccion.moneda else '—', obj.transaccion.get_estado_display()
        )
    transaccion_display.short_description = _("Transacción")

    def detalles_preview(self, obj):
        """Muestra una vista previa legible de los detalles JSON."""
        if obj.detalles:
            try:
                details_str = json.dumps(obj.detalles, indent=2, ensure_ascii=False)
                preview = details_str[:200] + '...' if len(details_str) > 200 else details_str
                return format_html('<pre style="margin: 0; font-size: 12px;">{}</pre>', preview)
            except Exception:
                return str(obj.detalles)
        return '—'
    detalles_preview.short_description = _("Detalles")

    def fecha_local(self, obj):
        """Muestra la fecha en formato local."""
        return localtime(obj.fecha).strftime("%Y-%m-%d %H:%M:%S")
    fecha_local.short_description = _("Fecha")

    def has_add_permission(self, request):
        """Impide agregar registros manualmente."""
        return False

    def has_change_permission(self, request, obj=None):
        """Impide modificar registros de auditoría."""
        return False

    def get_queryset(self, request):
        """Optimiza la consulta con select_related."""
        return super().get_queryset(request).select_related('transaccion', 'usuario')