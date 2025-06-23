"""
Panel de administración para la app vendedores en MexaRed.
Proporciona gestión avanzada de relaciones Distribuidor-Vendedor y auditoría,
con soporte para internacionalización, optimización y seguridad.
"""
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Q
from builtins import PermissionError  # o simplemente elimínala si no la usas

from .models import DistribuidorVendedor, DistribuidorVendedorChangeLog


@admin.register(DistribuidorVendedor)
class DistribuidorVendedorAdmin(admin.ModelAdmin):
    """
    Administración personalizada para el modelo DistribuidorVendedor.
    Permite gestionar relaciones con visualización optimizada y auditoría.
    """
    list_display = (
        'vendedor_link',
        'distribuidor_link',
        'saldo_asignado_formatted',
        'saldo_disponible_formatted',
        'moneda',
        'status_badge',
        'fecha_creacion',
    )
    list_filter = (
        'activo',
        'moneda',
        'fecha_creacion',
        ('distribuidor', admin.RelatedOnlyFieldListFilter),
        ('vendedor', admin.RelatedOnlyFieldListFilter),
    )
    search_fields = (
        'vendedor__username',
        'vendedor__email',
        'vendedor__first_name',
        'vendedor__last_name',
        'distribuidor__username',
        'distribuidor__email',
        'distribuidor__first_name',
        'distribuidor__last_name',
    )
    readonly_fields = (
        'uuid',
        'fecha_creacion',
        'fecha_actualizacion',
        'fecha_desactivacion',
        'configuracion',
        'creado_por',
    )
    ordering = ('-fecha_creacion',)
    list_per_page = 25
    autocomplete_fields = ['distribuidor', 'vendedor']
    list_select_related = ('distribuidor', 'vendedor', 'creado_por')
    actions = ['deactivate_relations', 'reactivate_relations']

    fieldsets = (
        (_("Información Principal"), {
            'fields': ('distribuidor', 'vendedor', 'activo')
        }),
        (_("Saldos"), {
            'fields': ('saldo_asignado', 'saldo_disponible', 'moneda')
        }),
        (_("Auditoría"), {
            'fields': ('uuid', 'creado_por', 'fecha_creacion', 'fecha_actualizacion', 'fecha_desactivacion')
        }),
        (_("Configuraciones"), {
            'fields': ('configuracion',),
            'classes': ('collapse',)
        }),
    )

    def vendedor_link(self, obj):
        """Muestra el vendedor como enlace al perfil de usuario."""
        url = reverse('admin:users_user_change', args=[obj.vendedor.pk])
        return format_html('<a href="{}">{}</a>', url, obj.vendedor.full_name)
    vendedor_link.short_description = _("Vendedor")

    def distribuidor_link(self, obj):
        """Muestra el distribuidor como enlace al perfil de usuario."""
        url = reverse('admin:users_user_change', args=[obj.distribuidor.pk])
        return format_html('<a href="{}">{}</a>', url, obj.distribuidor.full_name)
    distribuidor_link.short_description = _("Distribuidor")

    def saldo_asignado_formatted(self, obj):
        """Formatea el saldo asignado con moneda."""
        return f"{obj.moneda} {obj.saldo_asignado:,.2f}"
    saldo_asignado_formatted.short_description = _("Saldo Asignado")

    def saldo_disponible_formatted(self, obj):
        """Formatea el saldo disponible con moneda."""
        return f"{obj.moneda} {obj.saldo_disponible:,.2f}"
    saldo_disponible_formatted.short_description = _("Saldo Disponible")

    def status_badge(self, obj):
        """Muestra un indicador visual del estado activo."""
        color = "green" if obj.activo else "red"
        label = _("Activo") if obj.activo else _("Inactivo")
        return format_html(
            '<span style="color: {}; font-weight: bold; padding: 2px 8px; border-radius: 4px;">{}</span>',
            color, label
        )
    status_badge.short_description = _("Estado")

    def deactivate_relations(self, request, queryset):
        """Acción para desactivar relaciones seleccionadas."""
        if not request.user.is_superuser:
            raise PermissionError(_("Solo superusuarios pueden desactivar relaciones."))
        for relation in queryset.filter(activo=True):
            relation.desactivar(changed_by=request.user)
        self.message_user(request, _("Relaciones desactivadas correctamente."))
    deactivate_relations.short_description = _("Desactivar relaciones seleccionadas")

    def reactivate_relations(self, request, queryset):
        """Acción para reactivar relaciones seleccionadas."""
        if not request.user.is_superuser:
            raise PermissionError(_("Solo superusuarios pueden reactivar relaciones."))
        for relation in queryset.filter(activo=False):
            relation.reactivar(changed_by=request.user)
        self.message_user(request, _("Relaciones reactivadas correctamente."))
    reactivate_relations.short_description = _("Reactivar relaciones seleccionadas")

    def get_queryset(self, request):
        """Optimiza consultas con select_related."""
        return super().get_queryset(request).select_related('distribuidor', 'vendedor', 'creado_por')

    def get_readonly_fields(self, request, obj=None):
        """Restringe edición de campos sensibles para no superusuarios."""
        readonly = list(self.readonly_fields)
        if not request.user.is_superuser:
            readonly.extend(['activo', 'saldo_asignado', 'saldo_disponible', 'moneda'])
        return readonly

    def get_search_results(self, request, queryset, search_term):
        """Permite búsqueda por nombre completo."""
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        if search_term:
            queryset |= self.model.objects.filter(
                Q(vendedor__first_name__icontains=search_term) |
                Q(vendedor__last_name__icontains=search_term) |
                Q(distribuidor__first_name__icontains=search_term) |
                Q(distribuidor__last_name__icontains=search_term)
            )
        return queryset, use_distinct


@admin.register(DistribuidorVendedorChangeLog)
class DistribuidorVendedorChangeLogAdmin(admin.ModelAdmin):
    """
    Administración para registros de auditoría de DistribuidorVendedor.
    Campos de solo lectura para proteger la integridad.
    """
    list_display = (
        'relacion_link',
        'change_type',
        'changed_by_display',
        'details_preview',
        'timestamp',
    )
    list_filter = (
        'change_type',
        'timestamp',
        ('relacion__distribuidor', admin.RelatedOnlyFieldListFilter),
        ('relacion__vendedor', admin.RelatedOnlyFieldListFilter),
    )
    search_fields = (
        'relacion__vendedor__username',
        'relacion__vendedor__email',
        'relacion__distribuidor__username',
        'relacion__distribuidor__email',
        'changed_by__username',
        'changed_by__email',
    )
    readonly_fields = (
        'relacion',
        'change_type',
        'changed_by',
        'change_description',
        'details',
        'timestamp',
    )
    ordering = ('-timestamp',)
    list_per_page = 50
    date_hierarchy = 'timestamp'

    def relacion_link(self, obj):
        """Muestra la relación como enlace al objeto DistribuidorVendedor."""
        url = reverse('admin:vendedores_distribuidorvendedor_change', args=[obj.relacion.pk])
        return format_html('<a href="{}">{}</a>', url, str(obj.relacion))
    relacion_link.short_description = _("Relación")

    def changed_by_display(self, obj):
        """Muestra el usuario que realizó el cambio como enlace o 'Sistema'."""
        if obj.changed_by:
            url = reverse('admin:users_user_change', args=[obj.changed_by.pk])
            return format_html('<a href="{}">{}</a>', url, obj.changed_by.full_name)
        return _("Sistema")
    changed_by_display.short_description = _("Modificado por")

    def details_preview(self, obj):
        """Muestra una vista previa legible de los detalles JSON."""
        if obj.details:
            try:
                import json
                details_str = json.dumps(obj.details, indent=2, ensure_ascii=False)
                preview = details_str[:200] + '...' if len(details_str) > 200 else details_str
                return format_html('<pre style="margin: 0; font-size: 12px;">{}</pre>', preview)
            except Exception:
                return str(obj.details)
        return "-"
    details_preview.short_description = _("Detalles")

    def has_add_permission(self, request):
        """Impide agregar registros manualmente."""
        return False

    def has_change_permission(self, request, obj=None):
        """Impide modificar registros de auditoría."""
        return False

    def get_queryset(self, request):
        """Optimiza consultas con select_related."""
        return super().get_queryset(request).select_related(
            'relacion__distribuidor', 'relacion__vendedor', 'changed_by'
        )