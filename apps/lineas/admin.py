"""
Panel de administración para el módulo de Líneas en MexaRed.
Proporciona una interfaz optimizada para visualizar, buscar, filtrar y gestionar líneas telefónicas (SIMs).
Diseñado para administradores financieros, técnicos y de soporte, con UX de clase mundial, seguridad robusta
y cumplimiento normativo (PCI DSS, SOC2, ISO 27001).
Soporta internacionalización, auditoría y escalabilidad en entornos SaaS multinivel.
Integra LineaForm para validaciones estrictas y auditoría de actualizaciones.
"""

import logging
import uuid
from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.forms import ValidationError

from apps.users.models import User, UserChangeLog, ROLE_DISTRIBUIDOR
from apps.vendedores.models import DistribuidorVendedor
from apps.activaciones.models import Activacion
from .forms import LineaForm
from .models import Linea, AsignacionBackup

# Configuración de logging para auditoría en producción
logger = logging.getLogger(__name__)

class AsignarDistribuidorForm(forms.Form):
    """
    Formulario para asignar un distribuidor a múltiples líneas en una acción masiva.
    Valida UUIDs de líneas seleccionadas, conflictos de distribuidores y relaciones distribuidor-vendedor.
    """
    _selected_action = forms.CharField(widget=forms.MultipleHiddenInput)
    distribuidor = forms.ModelChoiceField(
        queryset=User.objects.filter(
            rol=ROLE_DISTRIBUIDOR, activo=True, is_active=True
        ).order_by('username'),
        label=_("Distribuidor a asignar"),
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500'
        }),
        help_text=_("Seleccione el distribuidor al que se asignarán las líneas seleccionadas.")
    )

    def clean(self):
        """
        Valida la selección de líneas, asegurando que los UUIDs sean válidos y que no haya conflictos
        con distribuidores o relaciones distribuidor-vendedor.
        """
        cleaned_data = super().clean()
        selected_lines = cleaned_data.get('_selected_action', '')
        distribuidor = cleaned_data.get('distribuidor')

        if not selected_lines:
            raise ValidationError(_("No se seleccionaron líneas."), code='no_selection')

        # Normalizar selected_lines a una lista de UUIDs
        if isinstance(selected_lines, str):
            selected_lines = [
                s.strip() for s in selected_lines.strip('[]').replace("'", "").split(',')
                if s.strip()
            ]

        # Validar que cada elemento sea un UUID válido
        validated_uuids = []
        for uuid_str in selected_lines:
            try:
                validated_uuids.append(str(uuid.UUID(uuid_str)))
            except ValueError:
                raise ValidationError(
                    _(f"'{uuid_str}' no es un UUID válido."), code='invalid_uuid'
                )

        # Verificar existencia y conflictos de líneas
        try:
            lineas = Linea.objects.filter(
                uuid__in=validated_uuids
            ).select_related('distribuidor', 'vendedor')
            if not lineas.exists():
                raise ValidationError(
                    _("Ninguna de las líneas seleccionadas existe."), code='no_lines'
                )

            for linea in lineas:
                if linea.distribuidor and linea.distribuidor != distribuidor:
                    raise ValidationError(
                        _(f"La línea {linea.msisdn} ya está asignada al distribuidor {linea.distribuidor.username}."),
                        code='distribuidor_conflict'
                    )
                if linea.vendedor and not DistribuidorVendedor.objects.filter(
                    distribuidor=distribuidor, vendedor=linea.vendedor, activo=True
                ).exists():
                    raise ValidationError(
                        _(f"El vendedor {linea.vendedor.username} no está asignado al distribuidor {distribuidor.username}."),
                        code='invalid_distribuidor_vendedor'
                    )
                # Validar que la línea no esté activa (estado 'assigned' requiere activación)
                if linea.estado == 'assigned':
                    raise ValidationError(
                        _(f"La línea {linea.msisdn} ya está asignada y activa. Use el módulo de Activaciones para gestionar."),
                        code='line_already_assigned'
                    )
        except ValueError as e:
            logger.error(f"Error procesando UUIDs en selección de líneas: {str(e)}")
            raise ValidationError(_("Selección de líneas inválida."), code='invalid_selection')

        cleaned_data['_selected_action'] = validated_uuids
        return cleaned_data

@admin.action(description=_("Asignar líneas vírgenes a 'prueba'"))
def asignar_lineas_a_prueba(modeladmin, request, queryset):
    """
    Acción personalizada para asignar líneas en estado 'idle' al distribuidor 'prueba'.
    Mantiene el estado 'idle' hasta que se procese una activación exitosa.
    Registra auditoría en UserChangeLog y usa transacciones atómicas.
    """
    if not request.user.is_superuser:
        logger.warning(
            f"Intento de asignación a 'prueba' denegado para {request.user.username} (no superusuario)"
        )
        messages.error(request, _("Solo los superusuarios pueden realizar esta acción."))
        return HttpResponseRedirect(request.get_full_path())

    try:
        distribuidor = User.objects.get(
            username='prueba', rol=ROLE_DISTRIBUIDOR, activo=True, is_active=True
        )
    except User.DoesNotExist:
        logger.error("El usuario 'prueba' no existe o no es un distribuidor activo.")
        messages.error(
            request, _("El usuario 'prueba' no existe o no es un distribuidor activo.")
        )
        return HttpResponseRedirect(request.get_full_path())

    with transaction.atomic():
        queryset = queryset.filter(
            estado='idle', distribuidor__isnull=True
        ).select_related('vendedor')
        if not queryset.exists():
            logger.warning(
                f"No hay líneas con estado 'idle' y sin distribuidor para asignar a 'prueba' por {request.user.username}"
            )
            messages.warning(
                request, _("No hay líneas con estado 'idle' y sin distribuidor para asignar.")
            )
            return HttpResponseRedirect(request.get_full_path())

        updated = 0
        failed = []
        audit_logs = []
        now = timezone.now()

        for linea in queryset:
            try:
                if linea.vendedor and not DistribuidorVendedor.objects.filter(
                    distribuidor=distribuidor, vendedor=linea.vendedor, activo=True
                ).exists():
                    raise ValidationError(
                        _(f"El vendedor {linea.vendedor.username} no está asignado al distribuidor 'prueba'."),
                        code='invalid_distribuidor_vendedor'
                    )

                # Normalizar tipo_sim si es inválido
                if linea.tipo_sim not in ['physical', 'esim']:
                    logger.warning(
                        f"Normalizando tipo_sim inválido '{linea.tipo_sim}' a 'physical' para línea {linea.msisdn}"
                    )
                    linea.tipo_sim = 'physical'

                linea.distribuidor = distribuidor
                linea.estado = 'idle'  # Mantener idle hasta activación
                linea.actualizado_por = request.user
                linea.fecha_actualizacion = now
                linea.full_clean()
                linea.save()

                audit_logs.append(UserChangeLog(
                    user=distribuidor,
                    changed_by=request.user,
                    change_type='update',
                    change_description=_(f"Asignación de línea {linea.msisdn} al distribuidor 'prueba'"),
                    details={
                        'msisdn': linea.msisdn,
                        'iccid': linea.iccid,
                        'distribuidor': distribuidor.username,
                        'estado': linea.estado,
                        'tipo_sim': linea.tipo_sim,
                        'vendedor': linea.vendedor.username if linea.vendedor else None,
                        'timestamp': now.isoformat()
                    }
                ))
                updated += 1
            except ValidationError as e:
                logger.error(
                    f"Error al asignar línea {linea.msisdn} a distribuidor 'prueba': {str(e)}",
                    exc_info=True
                )
                failed.append({'msisdn': linea.msisdn, 'error': str(e)})
            except Exception as e:
                logger.error(
                    f"Error inesperado al asignar línea {linea.msisdn} a distribuidor 'prueba': {str(e)}",
                    exc_info=True
                )
                failed.append({
                    'msisdn': linea.msisdn,
                    'error': _("Error inesperado al procesar la línea.")
                })

        if audit_logs:
            UserChangeLog.objects.bulk_create(audit_logs)

        if updated:
            messages.success(
                request,
                _(f"✅ {updated} líneas asignadas correctamente al distribuidor 'prueba'.")
            )
        if failed:
            for failure in failed:
                messages.warning(
                    request, _(f"⚠️ Error al asignar línea {failure['msisdn']}: {failure['error']}")
                )
        if not updated and not failed:
            messages.warning(
                request, _("⚠️ No se encontraron líneas vírgenes sin distribuidor.")
            )

        logger.info(
            f"{request.user.username} asignó {updated} líneas al distribuidor 'prueba' (fallos: {len(failed)})"
        )
        return HttpResponseRedirect(request.get_full_path())

@admin.action(description=_("📦 Asignar líneas a un distribuidor"))
def asignar_distribuidor(modeladmin, request, queryset):
    """
    Acción personalizada para asignar un distribuidor a múltiples líneas seleccionadas.
    Mantiene el estado 'idle' hasta que se procese una activación exitosa.
    Registra auditoría en UserChangeLog y AsignacionBackup, valida permisos de superusuario
    y usa transacciones atómicas.
    """
    if not request.user.is_superuser:
        logger.warning(
            f"Intento de asignación de distribuidor denegado para {request.user.username} (no superusuario)"
        )
        messages.error(request, _("Solo los superusuarios pueden realizar esta acción."))
        return HttpResponseRedirect(request.get_full_path())

    selected_ids = request.POST.getlist(ACTION_CHECKBOX_NAME)
    logger.debug(
        f"Procesando asignar_distribuidor: method={request.method}, selected_ids={selected_ids}"
    )

    if request.method == "POST" and "apply" in request.POST:
        form = AsignarDistribuidorForm(request.POST)
        has_conflicts = False
        if form.is_valid():
            distribuidor = form.cleaned_data['distribuidor']
            validated_uuids = form.cleaned_data['_selected_action']
            logger.info(
                f"Iniciando asignación de {len(validated_uuids)} líneas a distribuidor {distribuidor.username} por {request.user.username}"
            )

            with transaction.atomic():
                queryset = queryset.filter(
                    uuid__in=validated_uuids
                ).select_related('distribuidor', 'vendedor')
                lineas_con_distribuidor = queryset.filter(distribuidor__isnull=False)

                if lineas_con_distribuidor.exists():
                    AsignacionBackup.objects.bulk_create([
                        AsignacionBackup(
                            linea=linea,
                            distribuidor_anterior=linea.distribuidor,
                            creado_por=request.user,
                            fecha_respaldo=timezone.now()
                        ) for linea in lineas_con_distribuidor
                    ])

                updated = 0
                failed = []
                audit_logs = []
                now = timezone.now()

                for linea in queryset:
                    try:
                        # Normalizar tipo_sim si es inválido
                        if linea.tipo_sim not in ['physical', 'esim']:
                            logger.warning(
                                f"Normalizando tipo_sim inválido '{linea.tipo_sim}' a 'physical' para línea {linea.msisdn}"
                            )
                            linea.tipo_sim = 'physical'

                        linea.distribuidor = distribuidor
                        linea.estado = 'idle'  # Mantener idle hasta activación
                        linea.actualizado_por = request.user
                        linea.fecha_actualizacion = now
                        linea.full_clean()
                        linea.save()

                        audit_logs.append(UserChangeLog(
                            user=distribuidor,
                            changed_by=request.user,
                            change_type='update',
                            change_description=_(f"Asignación de línea {linea.msisdn} al distribuidor"),
                            details={
                                'msisdn': linea.msisdn,
                                'iccid': linea.iccid,
                                'distribuidor': distribuidor.username,
                                'estado': linea.estado,
                                'vendedor': linea.vendedor.username if linea.vendedor else None,
                                'timestamp': now.isoformat()
                            }
                        ))
                        updated += 1
                    except ValidationError as e:
                        logger.error(
                            f"Error al asignar línea {linea.msisdn} a distribuidor {distribuidor.username}: {str(e)}",
                            exc_info=True
                        )
                        failed.append({'msisdn': linea.msisdn, 'error': str(e)})
                        if 'distribuidor_conflict' in str(e) or 'line_already_assigned' in str(e):
                            has_conflicts = True
                    except Exception as e:
                        logger.error(
                            f"Error inesperado al asignar línea {linea.msisdn} a distribuidor {distribuidor.username}: {str(e)}",
                            exc_info=True
                        )
                        failed.append({
                            'msisdn': linea.msisdn,
                            'error': _("Error inesperado al procesar la línea.")
                        })

                if audit_logs:
                    UserChangeLog.objects.bulk_create(audit_logs)

                if updated:
                    messages.success(
                        request,
                        _(f"✅ {updated} líneas asignadas correctamente al distribuidor '{distribuidor.username}'.")
                    )
                if failed:
                    for failure in failed:
                        messages.warning(
                            request, _(f"⚠️ Error al asignar línea {failure['msisdn']}: {failure['error']}")
                        )
                if not updated and not failed:
                    messages.warning(
                        request, _("⚠️ No se encontraron líneas válidas para asignar.")
                    )

                logger.info(
                    f"{request.user.username} asignó {updated} líneas al distribuidor {distribuidor.username} (fallos: {len(failed)})"
                )
                return HttpResponseRedirect(request.get_full_path())
        else:
            logger.warning(
                f"Formulario de asignación inválido para {request.user.username}: {form.errors}"
            )
            messages.error(
                request, _("Por favor, corrija los errores en el formulario: ") + str(form.errors)
            )
            has_conflicts = any(
                'distribuidor_conflict' in str(e) or 'line_already_assigned' in str(e)
                for e in form.errors.get('__all__', [])
            )
    else:
        logger.debug(
            f"Mostrando formulario de asignación para {queryset.count()} líneas por {request.user.username}"
        )
        form = AsignarDistribuidorForm(initial={
            '_selected_action': ','.join(selected_ids)
        })
        has_conflicts = False

    context = {
        'title': _("Asignar distribuidor a líneas seleccionadas"),
        'objects': queryset,
        'form': form,
        'selected_ids': selected_ids,
        'action_checkbox_name': ACTION_CHECKBOX_NAME,
        'opts': modeladmin.model._meta,
        'app_label': modeladmin.model._meta.app_label,
        'site_title': admin.site.site_title,
        'site_url': '/',
        'action_name': 'asignar_distribuidor',
        'has_conflicts': has_conflicts,
    }
    return render(request, "admin/asignar_distribuidor.html", context)

@admin.action(description=_("🔓 Liberar líneas del distribuidor"))
def liberar_distribuidor(modeladmin, request, queryset):
    """
    Acción personalizada para liberar líneas de su distribuidor actual.
    Registra auditoría en UserChangeLog y AsignacionBackup, valida permisos de superusuario
    y usa transacciones atómicas.
    """
    if not request.user.is_superuser:
        logger.warning(
            f"Intento de liberación de distribuidor denegado para {request.user.username} (no superusuario)"
        )
        messages.error(request, _("Solo los superusuarios pueden realizar esta acción."))
        return HttpResponseRedirect(request.get_full_path())

    with transaction.atomic():
        queryset = queryset.select_related('distribuidor').prefetch_related('vendedor')
        lineas_con_distribuidor = queryset.filter(distribuidor__isnull=False)
        actualizadas = lineas_con_distribuidor.count()

        if not lineas_con_distribuidor.exists():
            logger.warning(
                f"No hay líneas con distribuidor para liberar por {request.user.username}"
            )
            messages.warning(
                request, _("Ninguna de las líneas seleccionadas tiene un distribuidor asignado.")
            )
            return HttpResponseRedirect(request.get_full_path())

        now = timezone.now()
        backups = [
            AsignacionBackup(
                linea=linea,
                distribuidor_anterior=linea.distribuidor,
                creado_por=request.user,
                fecha_respaldo=now
            ) for linea in lineas_con_distribuidor
        ]
        AsignacionBackup.objects.bulk_create(backups)

        audit_logs = [
            UserChangeLog(
                user=linea.distribuidor,
                changed_by=request.user,
                change_type='update',
                change_description=_(f"Línea liberada de distribuidor ({linea.msisdn})"),
                details={
                    'msisdn': linea.msisdn,
                    'iccid': linea.iccid,
                    'estado': linea.estado,
                    'distribuidor_anterior': linea.distribuidor.username,
                    'timestamp': now.isoformat()
                }
            ) for linea in lineas_con_distribuidor
        ]
        UserChangeLog.objects.bulk_create(audit_logs)

        lineas_con_distribuidor.update(
            distribuidor=None,
            actualizado_por=request.user,
            fecha_actualizacion=now
        )

        logger.info(
            f"{request.user.username} liberó {actualizadas} líneas de su distribuidor"
        )
        messages.success(
            request, _(f"🔓 {actualizadas} líneas liberadas correctamente del distribuidor.")
        )
        return HttpResponseRedirect(request.get_full_path())

@admin.register(Linea)
class LineaAdmin(admin.ModelAdmin):
    """
    Clase de administración para el modelo Linea.
    Permite visualizar, buscar, filtrar y gestionar líneas de forma eficiente.
    Protege campos críticos, ofrece UX intuitiva y está optimizada para alto volumen de datos.
    Usa LineaForm para validaciones de negocio y auditoría de actualizaciones.
    """
    form = LineaForm
    list_display = (
        'msisdn',
        'iccid',
        'estado_coloreado',
        'distribuidor_username',
        'vendedor_username',
        'tipo_sim',
        'dias_disponibles',
        'fecha_ultima_recarga',
        'fecha_vencimiento_plan',
        'fecha_activacion',
        'fecha_suspension',
        'fecha_actualizacion',
    )
    list_filter = (
        'estado',
        'tipo_sim',
        'categoria_servicio',
        'portability_status',
        'distribuidor',
        'vendedor',
        'fecha_vencimiento_plan',
        'fecha_registro',
    )
    search_fields = (
        'msisdn',
        'iccid',
        'distribuidor__username',
        'vendedor__username',
    )
    ordering = ('-fecha_registro',)
    readonly_fields = (
        'uuid',
        'fecha_registro',
        'fecha_actualizacion',
        'fecha_activacion',
        'fecha_suspension',
        'fecha_baja',
        'port_in_date',
        'port_out_date',
        'creado_por',
        'actualizado_por',
    )
    fieldsets = (
        (_('Datos de Línea'), {
            'fields': (
                'uuid', 'msisdn', 'iccid', 'tipo_sim', 'categoria_servicio', 'estado',
                'portability_status', 'distribuidor', 'vendedor',
            )
        }),
        (_('Fechas de Estado'), {
            'fields': (
                'fecha_activacion', 'fecha_suspension', 'fecha_baja',
                'port_in_date', 'port_out_date',
            )
        }),
        (_('Consumo y Beneficios'), {
            'fields': (
                'fecha_ultima_recarga', 'fecha_vencimiento_plan', 'dias_disponibles',
                'datos_consumidos', 'datos_disponibles',
                'minutos_consumidos', 'minutos_disponibles',
                'sms_consumidos', 'sms_disponibles',
            )
        }),
        (_('Auditoría'), {
            'fields': (
                'creado_por', 'actualizado_por', 'fecha_registro', 'fecha_actualizacion',
            )
        }),
    )
    list_per_page = 50
    list_select_related = ('distribuidor', 'vendedor', 'creado_por', 'actualizado_por')
    autocomplete_fields = ['distribuidor', 'vendedor', 'creado_por', 'actualizado_por']
    actions = [asignar_lineas_a_prueba, asignar_distribuidor, liberar_distribuidor]

    def distribuidor_username(self, obj):
        """Muestra el username del distribuidor."""
        return obj.distribuidor.username if obj.distribuidor else '-'
    distribuidor_username.short_description = _("Distribuidor")

    def vendedor_username(self, obj):
        """Muestra el username del vendedor."""
        return obj.vendedor.username if obj.vendedor else '-'
    vendedor_username.short_description = _("Vendedor")

    def estado_coloreado(self, obj):
        """
        Muestra el estado de la línea con colores para mejor visualización.
        """
        color_map = {
            'assigned': 'green',
            'idle': 'gray',
            'suspended': 'orange',
            'cancelled': 'red',
            'port-out': 'purple',
            'processing': 'blue',
        }
        color = color_map.get(obj.estado, 'black')
        return format_html(
            '<b style="color: {}; padding: 2px 8px; border-radius: 4px;">{}</b>',
            color, obj.get_estado_display()
        )
    estado_coloreado.short_description = _("Estado")
    estado_coloreado.admin_order_field = 'estado'

    def get_queryset(self, request):
        """
        Optimiza consultas con select_related para reducir accesos a la base de datos.
        """
        return super().get_queryset(request).select_related(
            'distribuidor', 'vendedor', 'creado_por', 'actualizado_por'
        )

    def get_form(self, request, obj=None, **kwargs):
        """
        Pasa el usuario actual al formulario para auditoría de actualizaciones.
        """
        form = super().get_form(request, obj, **kwargs)
        form.user = request.user
        return form

    def has_change_permission(self, request, obj=None):
        """
        Permite edición solo a superusuarios para proteger datos sensibles.
        """
        if request.user.is_superuser:
            return True
        logger.warning(
            f"Intento de edición de línea denegado para {request.user.username} (no superusuario)"
        )
        return False

    def has_delete_permission(self, request, obj=None):
        """
        Deshabilita eliminación para mantener trazabilidad.
        """
        logger.warning(
            f"Intento de eliminación de línea denegado para {request.user.username}"
        )
        return False

@admin.register(AsignacionBackup)
class AsignacionBackupAdmin(admin.ModelAdmin):
    """
    Clase de administración para el modelo AsignacionBackup.
    Permite visualizar y filtrar el historial de asignaciones previas de líneas.
    """
    list_display = (
        'linea_msisdn',
        'distribuidor_anterior_username',
        'fecha_respaldo_localized',
        'creado_por_username',
    )
    list_filter = (
        'distribuidor_anterior',
        'fecha_respaldo',
        'creado_por',
    )
    search_fields = (
        'linea__msisdn',
        'distribuidor_anterior__username',
        'creado_por__username',
    )
    ordering = ('-fecha_respaldo',)
    readonly_fields = (
        'linea',
        'distribuidor_anterior',
        'fecha_respaldo',
        'creado_por',
    )
    list_per_page = 50
    list_select_related = (
        'linea',
        'distribuidor_anterior',
        'creado_por',
    )

    def linea_msisdn(self, obj):
        """Muestra el MSISDN de la línea."""
        return obj.linea.msisdn if obj.linea else '-'
    linea_msisdn.short_description = _("Línea (MSISDN)")

    def distribuidor_anterior_username(self, obj):
        """Muestra el username del distribuidor anterior."""
        return obj.distribuidor_anterior.username if obj.distribuidor_anterior else '-'
    distribuidor_anterior_username.short_description = _("Distribuidor anterior")

    def creado_por_username(self, obj):
        """Muestra el username del usuario que creó el respaldo."""
        return obj.creado_por.username if obj.creado_por else '-'
    creado_por_username.short_description = _("Creado por")

    def fecha_respaldo_localized(self, obj):
        """Muestra la fecha de respaldo en formato localizado."""
        return timezone.localtime(obj.fecha_respaldo).strftime('%Y-%m-%d %H:%M:%S')
    fecha_respaldo_localized.short_description = _("Fecha de respaldo")

    def has_change_permission(self, request, obj=None):
        """Deshabilita la edición para proteger la integridad del respaldo."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Deshabilita la eliminación para mantener trazabilidad."""
        logger.warning(
            f"Intento de eliminación de respaldo denegado para {request.user.username}"
        )
        return False