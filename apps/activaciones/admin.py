"""
admin.py - Configuración del panel de administración para el módulo de activaciones en MexaRed.
Proporciona gestión avanzada de activaciones y auditorías con filtros avanzados, exportación multi-formato,
acciones personalizadas con formularios integrados, y trazabilidad regulatoria. Optimizado para uso exclusivo de
administradores y cumplimiento con estándares telco internacionales de nivel enterprise (PCI DSS, SOC2, ISO 27001).
"""

import json
import logging
from typing import Optional, Tuple, List
from django import forms
from django.contrib import admin
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.utils import timezone
from django.template.response import TemplateResponse
from django.utils.safestring import mark_safe
from import_export.admin import ExportMixin
from import_export import resources
from import_export.formats import base_formats
from rangefilter.filters import DateRangeFilter
from django.contrib.admin import SimpleListFilter
from .models import Activacion, PortabilidadDetalle, AuditLog
from .forms import FormularioActivacion
from .services import ActivacionService
from apps.users.models import User, ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR

# Configuración de logging para auditoría
logger = logging.getLogger(__name__)

# Formularios para acciones personalizadas
class AsignarDistribuidorForm(forms.Form):
    """
    Formulario para la acción de asignar distribuidor manualmente.
    """
    distribuidor_id = forms.ModelChoiceField(
        queryset=User.objects.filter(rol=ROLE_DISTRIBUIDOR, is_active=True),
        label=_("Distribuidor"),
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text=_("Seleccione el distribuidor a asignar.")
    )

class AsignarUsuarioSolicitaForm(forms.Form):
    """
    Formulario para la acción de asignar usuario solicitante manualmente.
    """
    usuario_solicita_id = forms.ModelChoiceField(
        queryset=User.objects.filter(rol__in=[ROLE_DISTRIBUIDOR, ROLE_VENDEDOR], is_active=True),
        label=_("Usuario Solicitante"),
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text=_("Seleccione el usuario solicitante a asignar.")
    )

class ActivacionResource(resources.ModelResource):
    """
    Resource para exportación de activaciones en múltiples formatos (CSV, Excel, JSON).
    Incluye campos traducidos, relaciones y propiedades calculadas para auditoría completa.
    """
    usuario_solicita_username = resources.Field(
        attribute='usuario_solicita__username',
        column_name=_('Usuario Solicitante')
    )
    distribuidor_asignado_username = resources.Field(
        attribute='distribuidor_asignado__username',
        column_name=_('Distribuidor Asignado')
    )
    oferta_nombre = resources.Field(
        attribute='oferta__nombre',
        column_name=_('Oferta')
    )
    ganancia_calculada = resources.Field(
        column_name=_('Ganancia Calculada'),
        attribute='ganancia'
    )

    class Meta:
        model = Activacion
        fields = (
            'id',
            'tipo_activacion',
            'tipo_producto',
            'iccid',
            'proveedor',
            'numero_asignado',
            'cliente_nombre',
            'cliente_email',
            'telefono_contacto',
            'estado',
            'precio_costo',
            'precio_final',
            'ganancia_calculada',
            'fecha_solicitud',
            'fecha_activacion',
            'usuario_solicita_username',
            'distribuidor_asignado_username',
            'oferta_nombre',
            'origen',
            'modo_pago_cliente',
            'codigo_addinteli',
            'ip_solicitud',
        )
        export_order = fields
        formats = [
            base_formats.CSV,
            base_formats.XLSX,
            base_formats.JSON,
        ]

    def dehydrate_estado(self, obj) -> str:
        """Traduce el estado para exportación."""
        return obj.get_estado_display()

    def dehydrate_tipo_activacion(self, obj) -> str:
        """Traduce el tipo de activación para exportación."""
        return obj.get_tipo_activacion_display()

    def dehydrate_tipo_producto(self, obj) -> str:
        """Traduce el tipo de producto para exportación."""
        return obj.get_tipo_producto_display()

    def dehydrate_modo_pago_cliente(self, obj) -> str:
        """Traduce el modo de pago para exportación."""
        return obj.get_modo_pago_cliente_display()

    def dehydrate_origen(self, obj) -> str:
        """Traduce el origen para exportación."""
        return obj.get_origen_display()

class TipoProductoFilter(SimpleListFilter):
    """Filtro personalizado para tipo de producto con traducción."""
    title = _('Tipo de Producto')
    parameter_name = 'tipo_producto'

    def lookups(self, request, model_admin) -> List[Tuple[str, str]]:
        return Activacion.PRODUCTOS

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(tipo_producto=self.value())
        return queryset

class EstadoFilter(SimpleListFilter):
    """Filtro personalizado para estado con colores."""
    title = _('Estado')
    parameter_name = 'estado'

    def lookups(self, request, model_admin) -> List[Tuple[str, str]]:
        return Activacion.ESTADOS

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(estado=self.value())
        return queryset

    def choices(self, changelist):
        for lookup, title in self.lookup_choices:
            yield {
                'selected': self.value() == lookup,
                'query_string': changelist.get_query_string({self.parameter_name: lookup}, []),
                'display': format_html(
                    '<span style="color: {}">{}</span>',
                    {
                        'exitosa': 'green',
                        'pendiente': 'orange',
                        'en_proceso': 'blue',
                        'fallida': 'red',
                        'revertida': 'purple',
                    }.get(lookup, 'gray'),
                    title
                ),
            }

class OrigenFilter(SimpleListFilter):
    """Filtro personalizado para origen con traducción."""
    title = _('Origen')
    parameter_name = 'origen'

    def lookups(self, request, model_admin) -> List[Tuple[str, str]]:
        return Activacion.ORIGENES

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(origen=self.value())
        return queryset

class PortabilidadDetalleInline(admin.StackedInline):
    """
    Inline para mostrar y editar detalles de portabilidad de una activación.
    """
    model = PortabilidadDetalle
    fields = (
        'numero_actual',
        'compañia_origen',
        'nip_portabilidad',
        'curp',
        'fecha_nacimiento',
        'tipo_identificacion',
        'identificacion_url',
        'numero_asignado_post_portabilidad',
    )
    readonly_fields = ('identificacion_url', 'numero_asignado_post_portabilidad')
    extra = 0
    can_delete = False
    verbose_name = _("Detalle de Portabilidad")
    verbose_name_plural = _("Detalles de Portabilidad")

    def numero_asignado_post_portabilidad(self, obj) -> str:
        """Muestra el número asignado tras la portabilidad."""
        return obj.activacion.numero_asignado if obj.activacion and obj.activacion.numero_asignado else '-'
    numero_asignado_post_portabilidad.short_description = _('Número Asignado')

@admin.register(Activacion)
class ActivacionAdmin(ExportMixin, admin.ModelAdmin):
    """
    Admin para gestionar activaciones.
    Integra formularios personalizados, filtros avanzados, exportación multi-formato, y acciones administrativas
    con formularios integrados. Soporta visualización de JSON de Addinteli, auditoría, y control granular por permisos.
    """
    form = FormularioActivacion
    resource_class = ActivacionResource
    inlines = [PortabilidadDetalleInline]
    list_display = (
        'id',
        'tipo_activacion_coloreado',
        'tipo_producto_coloreado',
        'iccid',
        'proveedor',
        'numero_asignado',
        'cliente_nombre',
        'telefono_contacto',
        'estado_coloreado',
        'precio_final',
        'ganancia_calculada',
        'origen_display',
        'usuario_solicita_link',
        'distribuidor_asignado_link',
        'oferta_nombre',
        'fecha_solicitud',
        'acciones_admin',
    )
    list_filter = (
        TipoProductoFilter,
        EstadoFilter,
        OrigenFilter,
        'tipo_activacion',
        'tipo_producto',
        'estado',
        'modo_pago_cliente',
        ('fecha_solicitud', DateRangeFilter),
        ('fecha_activacion', DateRangeFilter),
        'distribuidor_asignado',
        'usuario_solicita__rol',
    )
    search_fields = (
        'iccid',
        'cliente_nombre',
        'cliente_email',
        'telefono_contacto',
        'usuario_solicita__username',
        'distribuidor_asignado__username',
        'oferta__nombre',
        'numero_asignado',
        'codigo_addinteli',
    )
    ordering = ('-fecha_solicitud',)
    readonly_fields = (
        'id',
        'respuesta_addinteli_formatted',
        'fecha_solicitud',
        'fecha_activacion',
        'numero_asignado',
        'ganancia_calculada',
        'ip_solicitud',
        'pais_origen',
        'pais_destino',
        'lote_id',
        'addinteli_response_code',
        'mensaje_addinteli',
    )
    fieldsets = (
        (_('Información General'), {
            'fields': (
                'id',
                'tipo_activacion',
                'tipo_producto',
                'iccid',
                'proveedor',
                'cliente_nombre',
                'cliente_email',
                'telefono_contacto',
                'estado',
                'origen',
                'modo_pago_cliente',
                'ip_solicitud',
                'pais_origen',
                'pais_destino',
                'lote_id',
            )
        }),
        (_('Detalles Financieros'), {
            'fields': (
                'precio_costo',
                'precio_final',
                'ganancia_calculada',
            )
        }),
        (_('Relaciones'), {
            'fields': (
                'usuario_solicita',
                'distribuidor_asignado',
                'oferta',
            )
        }),
        (_('Respuesta de Addinteli'), {
            'fields': (
                'respuesta_addinteli_formatted',
                'codigo_addinteli',
                'addinteli_response_code',
                'mensaje_addinteli',
            ),
        }),
        (_('Fechas'), {
            'fields': (
                'fecha_solicitud',
                'fecha_activacion',
            )
        }),
    )
    actions = [
        'forzar_reproceso',
        'cambiar_estado_a_completado',
        'asignar_distribuidor_manual',
        'asignar_usuario_solicita_manual',
        'duplicar_activacion',
        'exportar_como_pdf',
    ]

    def get_form(self, request, obj: Optional[Activacion] = None, **kwargs) -> forms.Form:
        """Pasa el request al formulario para validaciones por rol."""
        kwargs['user'] = request.user
        return super().get_form(request, obj, **kwargs)

    def get_fieldsets(self, request, obj: Optional[Activacion] = None) -> List[Tuple[Optional[str], dict]]:
        """Oculta secciones sensibles para usuarios sin permisos."""
        fieldsets = super().get_fieldsets(request, obj)
        if not request.user.has_perm('activaciones.view_sensitive_data'):
            fieldsets = [fs for fs in fieldsets if fs[0] != _('Detalles Financieros')]
        return fieldsets

    def get_readonly_fields(self, request, obj: Optional[Activacion] = None) -> List[str]:
        """Restringe campos financieros para usuarios sin permisos."""
        readonly = list(super().get_readonly_fields(request, obj))
        if not request.user.has_perm('activaciones.view_sensitive_data'):
            readonly.extend(['precio_costo', 'precio_final', 'ganancia_calculada'])
        return readonly

    def tipo_activacion_coloreado(self, obj: Activacion) -> str:
        """Muestra el tipo de activación con color según su valor."""
        color = {
            'nueva': 'blue',
            'portabilidad': 'purple',
            'especifica': 'teal',
        }.get(obj.tipo_activacion, 'gray')
        return format_html('<strong style="color: {}">{}</strong>', color, obj.get_tipo_activacion_display())
    tipo_activacion_coloreado.short_description = _('Tipo de Activación')

    def tipo_producto_coloreado(self, obj: Activacion) -> str:
        """Muestra el tipo de producto con color según su valor."""
        color = {
            'SIM': 'green',
            'ESIM': 'cyan',
            'MIFI': 'orange',
            'HBB': 'purple',
            'IOT': 'brown',
        }.get(obj.tipo_producto, 'gray')
        return format_html('<strong style="color: {}">{}</strong>', color, obj.get_tipo_producto_display())
    tipo_producto_coloreado.short_description = _('Tipo de Producto')

    def estado_coloreado(self, obj: Activacion) -> str:
        """Muestra el estado con color según su valor."""
        color = {
            'exitosa': 'green',
            'pendiente': 'orange',
            'en_proceso': 'blue',
            'fallida': 'red',
            'revertida': 'purple',
        }.get(obj.estado, 'gray')
        return format_html('<strong style="color: {}">{}</strong>', color, obj.get_estado_display())
    estado_coloreado.short_description = _('Estado')

    def ganancia_calculada(self, obj: Activacion) -> str:
        """Muestra la ganancia calculada."""
        return f"{obj.ganancia:.2f}"
    ganancia_calculada.short_description = _('Ganancia Calculada')

    def origen_display(self, obj: Activacion) -> str:
        """Muestra el origen traducido."""
        return obj.get_origen_display()
    origen_display.short_description = _('Origen')

    def usuario_solicita_link(self, obj: Activacion) -> str:
        """Enlace al perfil del usuario solicitante."""
        if obj.usuario_solicita:
            url = reverse('admin:users_user_change', args=[obj.usuario_solicita.id])
            return format_html('<a href="{}">{}</a>', url, obj.usuario_solicita.username)
        return '-'
    usuario_solicita_link.short_description = _('Usuario Solicitante')

    def distribuidor_asignado_link(self, obj: Activacion) -> str:
        """Enlace al perfil del distribuidor asignado."""
        if obj.distribuidor_asignado:
            url = reverse('admin:users_user_change', args=[obj.distribuidor_asignado.id])
            return format_html('<a href="{}">{}</a>', url, obj.distribuidor_asignado.username)
        return '-'
    distribuidor_asignado_link.short_description = _('Distribuidor Asignado')

    def oferta_nombre(self, obj: Activacion) -> str:
        """Muestra el nombre de la oferta asociada."""
        return obj.oferta.nombre if obj.oferta else '-'
    oferta_nombre.short_description = _('Oferta')

    def respuesta_addinteli_formatted(self, obj: Activacion) -> str:
        """Muestra el JSON de respuesta de Addinteli formateado."""
        if obj.respuesta_addinteli:
            return format_html(
                '<pre style="background: #f5f5f5; padding: 10px; border-radius: 5px; max-height: 400px; overflow-y: auto;">{}</pre>',
                json.dumps(obj.respuesta_addinteli, indent=2, ensure_ascii=False)
            )
        return '-'
    respuesta_addinteli_formatted.short_description = _('Respuesta de Addinteli')

    def acciones_admin(self, obj: Activacion) -> str:
        """Botones personalizados para acciones en el listado."""
        view_url = reverse('admin:activaciones_activacion_change', args=[obj.id])
        return format_html(
            '<a class="button" href="{}" style="margin-right: 5px;">Ver</a>',
            view_url
        )
    acciones_admin.short_description = _('Acciones')

    @admin.action(description=_("Forzar reproceso de activaciones"), permissions=['change'])
    def forzar_reproceso(self, request, queryset):
        """Acción para reprocesar activaciones seleccionadas."""
        from django.db import transaction
        service = ActivacionService()
        success_count = 0
        for activacion in queryset:
            try:
                with transaction.atomic():
                    if activacion.estado not in ['pendiente', 'fallida']:
                        self.message_user(
                            request,
                            _(f"No se puede reprocesar la activación {activacion.id} (estado: {activacion.estado})."),
                            level=messages.WARNING
                        )
                        continue
                    result = service.procesar_activacion(activacion)
                    success_count += 1
                    AuditLog.objects.create(
                        usuario=request.user,
                        accion='REPROCESO_ACTIVACION',
                        entidad='Activacion',
                        entidad_id=str(activacion.id),
                        detalles={
                            'iccid': activacion.iccid,
                            'estado_anterior': activacion.estado,
                            'estado_nuevo': result['activacion'].estado,
                            'ip_address': request.META.get('REMOTE_ADDR', 'unknown'),
                        },
                        ip_address=request.META.get('REMOTE_ADDR', 'unknown')
                    )
                    logger.info(
                        f"Reproceso exitoso: Activación ID={activacion.id}, ICCID={activacion.iccid}, "
                        f"Usuario={request.user.username}"
                    )
            except Exception as e:
                self.message_user(
                    request,
                    _(f"Error reprocesando activación {activacion.id}: {str(e)}"),
                    level=messages.ERROR
                )
                logger.error(
                    f"Error reprocesando activación ID={activacion.id}: {str(e)}",
                    exc_info=True
                )
        if success_count:
            self.message_user(
                request,
                _(f"{success_count} activaciones reprocesadas exitosamente."),
                level=messages.SUCCESS
            )

    @admin.action(description=_("Marcar como exitosa"), permissions=['change'])
    def cambiar_estado_a_completado(self, request, queryset):
        """Acción para marcar activaciones como completadas."""
        from django.db import transaction
        with transaction.atomic():
            updated = queryset.update(estado='exitosa')
            AuditLog.objects.create(
                usuario=request.user,
                accion='CAMBIAR_ESTADO_ACTIVACION',
                entidad='Activacion',
                entidad_id=None,
                detalles={
                    'cantidad': updated,
                    'nuevo_estado': 'exitosa',
                    'ip_address': request.META.get('REMOTE_ADDR', 'unknown'),
                },
                ip_address=request.META.get('REMOTE_ADDR', 'unknown')
            )
            self.message_user(
                request,
                _(f"{updated} activaciones marcadas como exitosas."),
                level=messages.SUCCESS
            )
            logger.info(
                f"{updated} activaciones marcadas como exitosas por {request.user.username}"
            )

    @admin.action(description=_("Asignar distribuidor manualmente"), permissions=['change'])
    def asignar_distribuidor_manual(self, request, queryset):
        """Acción para asignar un distribuidor manualmente con formulario."""
        from django.db import transaction
        if request.POST.get('distribuidor_id'):
            form = AsignarDistribuidorForm(request.POST)
            if form.is_valid():
                with transaction.atomic():
                    distribuidor = form.cleaned_data['distribuidor_id']
                    updated = queryset.update(distribuidor_asignado=distribuidor)
                    AuditLog.objects.create(
                        usuario=request.user,
                        accion='ASIGNAR_DISTRIBUIDOR',
                        entidad='Activacion',
                        entidad_id=None,
                        detalles={
                            'cantidad': updated,
                            'distribuidor': distribuidor.username,
                            'ip_address': request.META.get('REMOTE_ADDR', 'unknown'),
                        },
                        ip_address=request.META.get('REMOTE_ADDR', 'unknown')
                    )
                    self.message_user(
                        request,
                        _(f"{updated} activaciones asignadas a {distribuidor.username}."),
                        level=messages.SUCCESS
                    )
                    logger.info(
                        f"{updated} activaciones asignadas a distribuidor {distribuidor.username} por {request.user.username}"
                    )
                    return HttpResponseRedirect(request.get_full_path())
        else:
            form = AsignarDistribuidorForm()
        return self.render_action_form(request, form, queryset, 'Asignar Distribuidor')

    @admin.action(description=_("Asignar usuario solicitante manualmente"), permissions=['change'])
    def asignar_usuario_solicita_manual(self, request, queryset):
        """Acción para asignar un usuario solicitante manualmente con formulario."""
        from django.db import transaction
        if request.POST.get('usuario_solicita_id'):
            form = AsignarUsuarioSolicitaForm(request.POST)
            if form.is_valid():
                with transaction.atomic():
                    usuario_solicita = form.cleaned_data['usuario_solicita_id']
                    updated = queryset.update(usuario_solicita=usuario_solicita)
                    AuditLog.objects.create(
                        usuario=request.user,
                        accion='ASIGNAR_USUARIO_SOLICITA',
                        entidad='Activacion',
                        entidad_id=None,
                        detalles={
                            'cantidad': updated,
                            'usuario_solicita': usuario_solicita.username,
                            'ip_address': request.META.get('REMOTE_ADDR', 'unknown'),
                        },
                        ip_address=request.META.get('REMOTE_ADDR', 'unknown')
                    )
                    self.message_user(
                        request,
                        _(f"{updated} activaciones asignadas a {usuario_solicita.username}."),
                        level=messages.SUCCESS
                    )
                    logger.info(
                        f"{updated} activaciones asignadas a usuario solicitante {usuario_solicita.username} por {request.user.username}"
                    )
                    return HttpResponseRedirect(request.get_full_path())
        else:
            form = AsignarUsuarioSolicitaForm()
        return self.render_action_form(request, form, queryset, 'Asignar Usuario Solicitante')

    @admin.action(description=_("Duplicar activaciones seleccionadas"), permissions=['add'])
    def duplicar_activacion(self, request, queryset):
        """Acción para duplicar activaciones seleccionadas."""
        from django.db import transaction
        success_count = 0
        for activacion in queryset:
            try:
                with transaction.atomic():
                    new_activacion = Activacion(
                        usuario_solicita=activacion.usuario_solicita,
                        distribuidor_asignado=activacion.distribuidor_asignado,
                        cliente_nombre=activacion.cliente_nombre,
                        cliente_email=activacion.cliente_email,
                        telefono_contacto=activacion.telefono_contacto,
                        iccid=activacion.iccid,  # Note: ICCID uniqueness will be validated in clean()
                        proveedor=activacion.proveedor,
                        tipo_producto=activacion.tipo_producto,
                        tipo_activacion=activacion.tipo_activacion,
                        precio_costo=activacion.precio_costo,
                        precio_final=activacion.precio_final,
                        oferta=activacion.oferta,
                        modo_pago_cliente=activacion.modo_pago_cliente,
                        ip_solicitud=activacion.ip_solicitud,
                        pais_origen=activacion.pais_origen,
                        pais_destino=activacion.pais_destino,
                        lote_id=activacion.lote_id,
                        estado='pendiente',
                        fecha_solicitud=timezone.now(),
                    )
                    new_activacion.full_clean()  # Validate before saving
                    new_activacion.save()
                    AuditLog.objects.create(
                        usuario=request.user,
                        accion='DUPLICAR_ACTIVACION',
                        entidad='Activacion',
                        entidad_id=str(new_activacion.id),
                        detalles={
                            'original_id': str(activacion.id),
                            'iccid': new_activacion.iccid,
                            'ip_address': request.META.get('REMOTE_ADDR', 'unknown'),
                        },
                        ip_address=request.META.get('REMOTE_ADDR', 'unknown')
                    )
                    success_count += 1
                    self.message_user(
                        request,
                        _(f"Duplicada activación {activacion.id} → {new_activacion.id}"),
                        level=messages.SUCCESS
                    )
                    logger.info(
                        f"Duplicada activación {activacion.id} → {new_activacion.id} por {request.user.username}"
                    )
            except Exception as e:
                self.message_user(
                    request,
                    _(f"Error duplicando activación {activacion.id}: {str(e)}"),
                    level=messages.ERROR
                )
                logger.error(
                    f"Error duplicando activación {activacion.id}: {str(e)}",
                    exc_info=True
                )
        if success_count:
            self.message_user(
                request,
                _(f"{success_count} activaciones duplicadas exitosamente."),
                level=messages.SUCCESS
            )

    @admin.action(description=_("Exportar como PDF"), permissions=['view'])
    def exportar_como_pdf(self, request, queryset):
        """Acción para exportar activaciones seleccionadas como PDF (futuro)."""
        self.message_user(
            request,
            _("Exportación a PDF no implementada aún. Use CSV o Excel por ahora."),
            level=messages.INFO
        )

    def render_action_form(self, request, form, queryset, title: str) -> TemplateResponse:
        """Renderiza un formulario para acciones personalizadas."""
        return TemplateResponse(
            request,
            'admin/action_form.html',
            {
                'title': title,
                'form': form,
                'queryset': queryset,
                'opts': self.model._meta,
                'action': request.POST.get('action', ''),
                'action_checkbox_name': admin.helpers.ACTION_CHECKBOX_NAME,
            }
        )

    def get_actions(self, request) -> dict:
        """Restringe acciones según permisos del usuario."""
        actions = super().get_actions(request)
        if not request.user.has_perm('activaciones.change_activacion'):
            for action in ['forzar_reproceso', 'cambiar_estado_a_completado', 'asignar_distribuidor_manual', 'asignar_usuario_solicita_manual']:
                actions.pop(action, None)
        if not request.user.has_perm('activaciones.add_activacion'):
            actions.pop('duplicar_activacion', None)
        if not request.user.has_perm('activaciones.view_activacion'):
            actions.pop('exportar_como_pdf', None)
        return actions

    def get_queryset(self, request):
        """Optimiza la consulta con select_related, prefetch_related y only."""
        return super().get_queryset(request).select_related(
            'usuario_solicita', 'distribuidor_asignado', 'oferta'
        ).prefetch_related('portabilidad_detalle').only(
            'id', 'tipo_activacion', 'tipo_producto', 'iccid', 'proveedor',
            'numero_asignado', 'cliente_nombre', 'telefono_contacto', 'estado',
            'precio_final', 'origen', 'fecha_solicitud',
            'usuario_solicita__username', 'distribuidor_asignado__username',
            'oferta__nombre'
        )

    def has_delete_permission(self, request, obj: Optional[Activacion] = None) -> bool:
        """Restringe eliminaciones a superusuarios."""
        return request.user.is_superuser

    def has_change_permission(self, request, obj: Optional[Activacion] = None) -> bool:
        """Restringe ediciones de activaciones exitosas."""
        if obj and obj.estado == 'exitosa':
            return False
        return super().has_change_permission(request, obj)

    def has_module_permission(self, request) -> bool:
        """Restringe acceso al módulo a administradores."""
        return request.user.is_staff and request.user.has_perm('activaciones.view_activacion')

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """
    Admin para gestionar registros de auditoría.
    Permite visualizar intentos de acceso, cambios, y errores con filtros avanzados.
    """
    list_display = (
        'id',
        'usuario_link',
        'accion',
        'entidad',
        'entidad_id',
        'ip_address',
        'origen_api',
        'integridad_verificada',
        'fecha',
        'detalles_formatted',
        'audit_hash_truncated',
    )
    list_filter = (
        'accion',
        'entidad',
        'origen_api',
        ('fecha', DateRangeFilter),
        'usuario__rol',
    )
    search_fields = (
        'usuario__username',
        'ip_address',
        'entidad_id',
        'detalles__action',
        'detalles__reason',
        'audit_hash',
    )
    readonly_fields = (
        'usuario',
        'accion',
        'entidad',
        'entidad_id',
        'detalles_formatted',
        'ip_address',
        'origen_api',
        'integridad_verificada',
        'fecha',
        'audit_hash',
    )
    ordering = ('-fecha',)
    fieldsets = (
        (_('Información General'), {
            'fields': (
                'usuario',
                'accion',
                'entidad',
                'entidad_id',
                'ip_address',
                'origen_api',
                'integridad_verificada',
                'fecha',
                'audit_hash',
            )
        }),
        (_('Detalles'), {
            'fields': ('detalles_formatted',),
        }),
    )

    def usuario_link(self, obj: AuditLog) -> str:
        """Enlace al perfil del usuario asociado."""
        if obj.usuario:
            url = reverse('admin:users_user_change', args=[obj.usuario.id])
            return format_html('<a href="{}">{}</a>', url, obj.usuario.username)
        return '-'
    usuario_link.short_description = _('Usuario')

    def detalles_formatted(self, obj: AuditLog) -> str:
        """Muestra los detalles del log formateados como JSON."""
        return format_html(
            '<pre style="background: #f5f5f5; padding: 10px; border-radius: 5px; max-height: 400px; overflow-y: auto;">{}</pre>',
            json.dumps(obj.detalles or {}, indent=2, ensure_ascii=False)
        )
    detalles_formatted.short_description = _('Detalles')

    def audit_hash_truncated(self, obj: AuditLog) -> str:
        """Muestra el hash de auditoría truncado para legibilidad."""
        return obj.audit_hash[:16] + '...' if obj.audit_hash else '-'
    audit_hash_truncated.short_description = _('Hash de Auditoría')

    def get_queryset(self, request):
        """Optimiza la consulta con select_related."""
        return super().get_queryset(request).select_related('usuario')

    def has_add_permission(self, request) -> bool:
        """Deshabilita la creación manual de logs."""
        return False

    def has_change_permission(self, request, obj: Optional[AuditLog] = None) -> bool:
        """Deshabilita la edición de logs."""
        return False

    def has_delete_permission(self, request, obj: Optional[AuditLog] = None) -> bool:
        """Deshabilita la eliminación de logs."""
        return False

    def has_module_permission(self, request) -> bool:
        """Restringe acceso al módulo a administradores."""
        return request.user.is_staff and request.user.has_perm('activaciones.view_activacion')