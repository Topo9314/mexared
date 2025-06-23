from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db.models import Q, F
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from decimal import Decimal

# Centralized decimal precision constants for consistency
DECIMAL_MAX_DIGITS = 10
DECIMAL_DECIMAL_PLACES = 2

# Monedas soportadas (extensible for global markets)
CURRENCY_CHOICES = [
    ('MXN', 'Peso Mexicano'),
    ('USD', 'US Dollar'),
    ('EUR', 'Euro'),
    ('BRL', 'Brazilian Real'),
    ('GBP', 'British Pound'),
    ('JPY', 'Japanese Yen'),
]

# Categorías de servicio soportadas (alineado con Addinteli)
CATEGORIAS_SERVICIO = [
    ('movilidad', _('Movilidad')),
    ('mifi', _('MIFI')),
    ('hbb', _('HBB')),
]

class Oferta(models.Model):
    """
    Catálogo sincronizado desde Addinteli, representing base plans without margins.
    Supports versioning for audit and rollback, with service category classification.
    """
    codigo_addinteli = models.CharField(max_length=50, unique=True, db_index=True)
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)
    costo_base = models.DecimalField(
        max_digits=DECIMAL_MAX_DIGITS,
        decimal_places=DECIMAL_DECIMAL_PLACES,
        validators=[MinValueValidator(Decimal('0.00'))],
        null=False,
    )
    duracion_dias = models.PositiveIntegerField(default=30, db_default=30)
    categoria_servicio = models.CharField(
        max_length=20,
        choices=CATEGORIAS_SERVICIO,
        default='movilidad',
        verbose_name=_("Service Category"),
        help_text=_("Tipo de servicio asociado: Movilidad, MIFI, HBB.")
    )
    moneda = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='MXN', null=False)
    language = models.CharField(max_length=10, default='es', null=False)  # For multi-lingual support
    activo = models.BooleanField(default=True, db_default=True)
    version = models.PositiveIntegerField(default=1, db_default=1)  # For catalog versioning
    fecha_sincronizacion = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Offer (Base Catalog)")
        verbose_name_plural = _("Offers (Base Catalog)")
        indexes = [
            models.Index(fields=['codigo_addinteli'], name='idx_oferta_code'),
            models.Index(fields=['moneda', 'activo'], name='idx_oferta_active_currency', include=['costo_base']),
            models.Index(fields=['categoria_servicio'], name='idx_oferta_categoria_servicio'),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.codigo_addinteli}) - {self.get_categoria_servicio_display()}"

class MargenDistribuidor(models.Model):
    """
    Custom margins and prices per distributor, enforcing business logic.
    """
    oferta = models.ForeignKey(Oferta, on_delete=models.CASCADE, related_name='margenes_distribuidor')
    distribuidor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'rol': 'distribuidor'},
        related_name='margenes_asignados'
    )
    precio_distribuidor = models.DecimalField(
        max_digits=DECIMAL_MAX_DIGITS,
        decimal_places=DECIMAL_DECIMAL_PLACES,
        null=False,
    )
    precio_vendedor = models.DecimalField(
        max_digits=DECIMAL_MAX_DIGITS,
        decimal_places=DECIMAL_DECIMAL_PLACES,
        null=False,
    )
    precio_cliente = models.DecimalField(
        max_digits=DECIMAL_MAX_DIGITS,
        decimal_places=DECIMAL_DECIMAL_PLACES,
        null=False,
    )
    moneda = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='MXN', null=False)
    activo = models.BooleanField(default=True, db_default=True)
    fecha_asignacion = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Distributor Margin")
        verbose_name_plural = _("Distributor Margins")
        unique_together = ('oferta', 'distribuidor')
        indexes = [
            models.Index(fields=['oferta', 'distribuidor'], name='idx_margin_dist', include=['precio_cliente']),
        ]

    def __str__(self):
        return f"{self.oferta} - {self.distribuidor}"

    @cached_property
    def margen_admin(self) -> Decimal:
        """Calculates the administrator's margin."""
        return self.precio_distribuidor - self.oferta.costo_base

    @cached_property
    def margen_distribuidor(self) -> Decimal:
        """Calculates the distributor's margin."""
        return self.precio_vendedor - self.precio_distribuidor

    @cached_property
    def margen_vendedor(self) -> Decimal:
        """Calculates the vendor's margin."""
        return self.precio_cliente - self.precio_vendedor

    @cached_property
    def margen_total(self) -> Decimal:
        """Calculates the total system margin."""
        return self.precio_cliente - self.oferta.costo_base

class ListaPreciosEspecial(models.Model):
    """
    Container for VIP or corporate special price lists.
    """
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True, null=True)
    moneda = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='MXN', null=False)
    language = models.CharField(max_length=10, default='es', null=False)  # Multi-lingual support
    activo = models.BooleanField(default=True, db_default=True)
    fecha_creacion = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Special Price List")
        verbose_name_plural = _("Special Price Lists")
        indexes = [
            models.Index(fields=['moneda', 'activo'], name='idx_list_active_currency'),
        ]

    def __str__(self):
        return self.nombre

class OfertaListaPreciosEspecial(models.Model):
    """
    Special prices per offer within a VIP list.
    """
    lista = models.ForeignKey(ListaPreciosEspecial, on_delete=models.CASCADE, related_name='precios')
    oferta = models.ForeignKey(Oferta, on_delete=models.CASCADE)
    precio_cliente_especial = models.DecimalField(
        max_digits=DECIMAL_MAX_DIGITS,
        decimal_places=DECIMAL_DECIMAL_PLACES,
        validators=[MinValueValidator(Decimal('0.00'))],
        null=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Special Offer Price")
        verbose_name_plural = _("Special Offer Prices")
        unique_together = ('lista', 'oferta')
        indexes = [
            models.Index(fields=['lista', 'oferta'], name='idx_special_price', include=['precio_cliente_especial']),
        ]

    def __str__(self):
        return f"{self.lista.nombre} - {self.oferta.nombre}"

class ClienteListaAsignada(models.Model):
    """
    Assignment of VIP price lists to end clients.
    """
    cliente = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'rol': 'cliente'}
    )
    lista = models.ForeignKey(ListaPreciosEspecial, on_delete=models.CASCADE)
    fecha_asignacion = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Client with Special List")
        verbose_name_plural = _("Clients with Special Lists")
        unique_together = ('cliente',)
        indexes = [
            models.Index(fields=['cliente'], name='idx_client_list'),
        ]

    def __str__(self):
        return f"{self.cliente} → {self.lista.nombre}"

class MargenVendedor(models.Model):
    """
    Vendor-specific margins negotiated by distributors, linked to MargenDistribuidor.
    """
    margen_distribuidor = models.ForeignKey(
        MargenDistribuidor,
        on_delete=models.CASCADE,
        related_name='margen_vendedores'
    )
    vendedor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'rol': 'vendedor'}
    )
    precio_vendedor = models.DecimalField(
        max_digits=DECIMAL_MAX_DIGITS,
        decimal_places=DECIMAL_DECIMAL_PLACES,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    precio_cliente = models.DecimalField(
        max_digits=DECIMAL_MAX_DIGITS,
        decimal_places=DECIMAL_DECIMAL_PLACES,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    activo = models.BooleanField(default=True, db_default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Vendor Margin")
        verbose_name_plural = _("Vendor Margins")
        unique_together = ('margen_distribuidor', 'vendedor')
        indexes = [
            models.Index(fields=['margen_distribuidor', 'vendedor'], name='idx_vendor_margin_dist_vend'),
            models.Index(fields=['activo'], name='idx_vendor_margin_active'),
        ]

    def __str__(self):
        return f"{self.vendedor} - {self.margen_distribuidor.oferta.nombre}"

    @cached_property
    def margen_vendedor(self) -> Decimal:
        """Calculates the vendor's margin."""
        return self.precio_cliente - self.precio_vendedor