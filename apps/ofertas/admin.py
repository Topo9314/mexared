# apps/ofertas/admin.py

from django.contrib import admin, messages
from django.db.models import Sum
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.contrib.admin.views.decorators import staff_member_required

from apps.ofertas.models import (
    Oferta,
    MargenDistribuidor,
    ListaPreciosEspecial,
    OfertaListaPreciosEspecial,
    ClienteListaAsignada,
    MargenVendedor
)
from apps.ofertas.utils.sync_addinteli import sync_addinteli_offers

# Global configurations
LIST_PER_PAGE = 50
LIST_MAX_SHOW_ALL = 1000  # Limit for "Show All" to prevent performance issues

# Customize admin site
admin.site.site_header = _("🌐 Global Telecom Financial Console")
admin.site.site_title = _("International Backoffice Suite")
admin.site.index_title = _("Operations Management Dashboard")

@admin.register(Oferta)
class OfertaAdmin(admin.ModelAdmin):
    """
    Admin interface for managing Oferta model with optimized queries and synchronization action.
    """
    list_display = (
        'codigo_addinteli',
        'nombre',
        'categoria_servicio_display',
        'costo_base_display',
        'moneda',
        'activo',
        'version',
        'fecha_sincronizacion_display',
        'sync_action',
    )
    search_fields = ('codigo_addinteli', 'nombre', 'descripcion')
    list_filter = ('categoria_servicio', 'activo', 'moneda', 'language', 'version')
    readonly_fields = ('created_at', 'updated_at', 'fecha_sincronizacion', 'version')
    ordering = ('-fecha_sincronizacion',)
    list_per_page = LIST_PER_PAGE
    list_max_show_all = LIST_MAX_SHOW_ALL
    actions = ['trigger_sync_offers']

    def get_queryset(self, request):
        """Optimize queries with select_related for margenes_distribuidor."""
        return super().get_queryset(request).select_related('margenes_distribuidor')

    def costo_base_display(self, obj):
        """Display base cost with currency."""
        return format_html("{:.2f} {}", obj.costo_base, obj.moneda)
    costo_base_display.short_description = _("Base Cost")

    def fecha_sincronizacion_display(self, obj):
        """Display last synchronization date in UTC."""
        return obj.fecha_sincronizacion.strftime('%Y-%m-%d %H:%M UTC') if obj.fecha_sincronizacion else '-'
    fecha_sincronizacion_display.short_description = _("Last Sync")

    def categoria_servicio_display(self, obj):
        """Display human-readable service category."""
        return obj.get_categoria_servicio_display()
    categoria_servicio_display.short_description = _("Service Category")

    def sync_action(self, obj):
        """Display a button to trigger synchronization."""
        return format_html(
            '<a class="button" href="{}">{}</a>',
            reverse('admin:ofertas_sync_offers'),
            _("Sync Now")
        )
    sync_action.short_description = _("Sync Action")
    sync_action.allow_tags = True

    def trigger_sync_offers(self, request, queryset):
        """Action to trigger synchronization of offers from Addinteli."""
        try:
            new_count, updated_count = sync_addinteli_offers()
            self.message_user(
                request,
                _(f"Synchronization successful: {new_count} new offers created, {updated_count} updated"),
                messages.SUCCESS
            )
        except Exception as e:
            self.message_user(
                request,
                _(f"Failed to synchronize offers: {str(e)}"),
                messages.ERROR
            )
    trigger_sync_offers.short_description = _("Synchronize offers from Addinteli")

@admin.register(MargenDistribuidor)
class MargenDistribuidorAdmin(admin.ModelAdmin):
    """
    Admin interface for managing distributor margins with optimized queries and formatted displays.
    """
    list_display = (
        'oferta',
        'distribuidor',
        'precio_distribuidor_display',
        'precio_vendedor_display',
        'precio_cliente_display',
        'margen_admin_display',
        'margen_distribuidor_display',
        'margen_vendedor_display',
        'moneda',
        'activo',
    )
    search_fields = ('oferta__nombre', 'distribuidor__username')
    list_filter = ('activo', 'moneda')
    readonly_fields = ('created_at', 'updated_at', 'fecha_asignacion')
    ordering = ('-fecha_asignacion',)
    list_per_page = LIST_PER_PAGE
    list_max_show_all = LIST_MAX_SHOW_ALL

    def get_queryset(self, request):
        """Optimize queries with select_related for oferta and distribuidor."""
        return super().get_queryset(request).select_related('oferta', 'distribuidor')

    def precio_distribuidor_display(self, obj):
        """Display distributor price with currency."""
        return format_html("{:.2f} {}", obj.precio_distribuidor, obj.moneda)
    precio_distribuidor_display.short_description = _("Distributor Price")

    def precio_vendedor_display(self, obj):
        """Display vendor price with currency."""
        return format_html("{:.2f} {}", obj.precio_vendedor, obj.moneda)
    precio_vendedor_display.short_description = _("Vendor Price")

    def precio_cliente_display(self, obj):
        """Display client price with currency."""
        return format_html("{:.2f} {}", obj.precio_cliente, obj.moneda)
    precio_cliente_display.short_description = _("Client Price")

    def margen_admin_display(self, obj):
        """Display admin margin with currency (bold)."""
        return format_html("<b>{:.2f}</b> {}", obj.margen_admin, obj.moneda)
    margen_admin_display.short_description = _("Admin Margin")

    def margen_distribuidor_display(self, obj):
        """Display distributor margin with currency (bold)."""
        return format_html("<b>{:.2f}</b> {}", obj.margen_distribuidor, obj.moneda)
    margen_distribuidor_display.short_description = _("Distributor Margin")

    def margen_vendedor_display(self, obj):
        """Display vendor margin with currency (bold)."""
        return format_html("<b>{:.2f}</b> {}", obj.margen_vendedor, obj.moneda)
    margen_vendedor_display.short_description = _("Vendor Margin")

@admin.register(ListaPreciosEspecial)
class ListaPreciosEspecialAdmin(admin.ModelAdmin):
    """
    Admin interface for managing special price lists with optimized prefetching.
    """
    list_display = ('nombre', 'moneda', 'language', 'activo', 'fecha_creacion_display')
    search_fields = ('nombre', 'descripcion')
    list_filter = ('activo', 'moneda', 'language')
    readonly_fields = ('created_at', 'updated_at', 'fecha_creacion')
    ordering = ('-fecha_creacion',)
    list_per_page = LIST_PER_PAGE
    list_max_show_all = LIST_MAX_SHOW_ALL

    def get_queryset(self, request):
        """Optimize queries with prefetch_related for precios."""
        return super().get_queryset(request).prefetch_related('precios')

    def fecha_creacion_display(self, obj):
        """Display creation date in UTC."""
        return obj.fecha_creacion.strftime('%Y-%m-%d %H:%M UTC') if obj.fecha_creacion else '-'
    fecha_creacion_display.short_description = _("Creation Date")

@admin.register(OfertaListaPreciosEspecial)
class OfertaListaPreciosEspecialAdmin(admin.ModelAdmin):
    """
    Admin interface for managing special offer prices with optimized queries.
    """
    list_display = ('lista', 'oferta', 'precio_cliente_especial_display')
    search_fields = ('lista__nombre', 'oferta__nombre')
    list_filter = ('lista__moneda',)
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('lista__nombre',)
    list_per_page = LIST_PER_PAGE
    list_max_show_all = LIST_MAX_SHOW_ALL

    def get_queryset(self, request):
        """Optimize queries with select_related for lista and oferta."""
        return super().get_queryset(request).select_related('lista', 'oferta')

    def precio_cliente_especial_display(self, obj):
        """Display special client price with currency."""
        return format_html("{:.2f} {}", obj.precio_cliente_especial, obj.oferta.moneda)
    precio_cliente_especial_display.short_description = _("Special Client Price")

@admin.register(ClienteListaAsignada)
class ClienteListaAsignadaAdmin(admin.ModelAdmin):
    """
    Admin interface for managing client assignments to special price lists.
    """
    list_display = ('cliente', 'lista', 'fecha_asignacion_display')
    search_fields = ('cliente__username', 'lista__nombre')
    list_filter = ('lista__moneda',)
    readonly_fields = ('created_at', 'updated_at', 'fecha_asignacion')
    ordering = ('-fecha_asignacion',)
    list_per_page = LIST_PER_PAGE
    list_max_show_all = LIST_MAX_SHOW_ALL

    def get_queryset(self, request):
        """Optimize queries with select_related for cliente and lista."""
        return super().get_queryset(request).select_related('cliente', 'lista')

    def fecha_asignacion_display(self, obj):
        """Display assignment date in UTC."""
        return obj.fecha_asignacion.strftime('%Y-%m-%d %H:%M UTC') if obj.fecha_asignacion else '-'
    fecha_asignacion_display.short_description = _("Assigned At")

@admin.register(MargenVendedor)
class MargenVendedorAdmin(admin.ModelAdmin):
    """
    Admin interface for managing vendor margins with optimized queries.
    """
    list_display = (
        'vendedor',
        'margen_distribuidor',
        'distribuidor_display',
        'oferta_display',
        'precio_vendedor_display',
        'precio_cliente_display',
        'activo',
    )
    search_fields = (
        'vendedor__username',
        'margen_distribuidor__oferta__nombre',
        'margen_distribuidor__distribuidor__username',
    )
    list_filter = ('activo', 'margen_distribuidor__moneda')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-created_at',)
    list_per_page = LIST_PER_PAGE
    list_max_show_all = LIST_MAX_SHOW_ALL

    def get_queryset(self, request):
        """Optimize queries with select_related for related models."""
        return super().get_queryset(request).select_related(
            'vendedor',
            'margen_distribuidor__oferta',
            'margen_distribuidor__distribuidor',
        )

    def distribuidor_display(self, obj):
        """Display distributor username."""
        return obj.margen_distribuidor.distribuidor.username
    distribuidor_display.short_description = _("Distributor")

    def oferta_display(self, obj):
        """Display offer name."""
        return obj.margen_distribuidor.oferta.nombre
    oferta_display.short_description = _("Offer")

    def precio_vendedor_display(self, obj):
        """Display vendor price with currency."""
        return format_html("{:.2f} {}", obj.precio_vendedor, obj.margen_distribuidor.moneda)
    precio_vendedor_display.short_description = _("Vendor Price")

    def precio_cliente_display(self, obj):
        """Display client price with currency."""
        return format_html("{:.2f} {}", obj.precio_cliente, obj.margen_distribuidor.moneda)
    precio_cliente_display.short_description = _("Client Price")