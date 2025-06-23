"""
Modelos para la gestión de vendedores en MexaRed.
Define la relación entre distribuidores y vendedores, con soporte para contacto,
auditoría, multi-moneda, y escalabilidad internacional de nivel empresarial.
"""
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import JSONField
from django.core.validators import MinValueValidator, RegexValidator
import uuid
from decimal import Decimal

import re



class DistribuidorVendedor(models.Model):
    """
    Modelo robusto que regula la relación entre un distribuidor y un vendedor,
    gestionando saldo, contacto, auditoría, y soporte internacional.
    """
    # Identificador único universal
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        verbose_name=_("UUID"),
        help_text=_("Identificador único universal para la relación.")
    )

    # Relación con el distribuidor
    distribuidor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vendedores_asignados_via_relacion',
        limit_choices_to={'rol': 'distribuidor'},
        verbose_name=_("Distribuidor"),
        help_text=_("Usuario con rol de distribuidor que gestiona este vendedor.")
    )

    # Relación con el vendedor (OneToOne para garantizar unicidad)
    vendedor = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='perfil_distribuidor',
        limit_choices_to={'rol': 'vendedor'},
        verbose_name=_("Vendedor"),
        help_text=_("Usuario con rol de vendedor asignado a este distribuidor.")
    )

    # Saldo inicial asignado
    saldo_inicial = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0.00)],
        verbose_name=_("Saldo Inicial"),
        help_text=_("Monto inicial asignado al vendedor al crear la relación.")
    )

    # Saldo asignado total
    saldo_asignado = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0.00)],
        verbose_name=_("Saldo Asignado Total"),
        help_text=_("Monto total asignado por el distribuidor, incluyendo adiciones posteriores.")
    )

    # Saldo disponible actual
    saldo_disponible = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0.00)],
        verbose_name=_("Saldo Disponible Actual"),
        help_text=_("Monto disponible para operaciones del vendedor.")
    )

    # Moneda del saldo
    moneda = models.CharField(
        max_length=3,
        default='MXN',
        verbose_name=_("Moneda"),
        help_text=_("Código ISO 4217 de la moneda del saldo (e.g., MXN, USD, EUR)."),
        validators=[
            RegexValidator(
                regex=r'^[A-Z]{3}$',
                message=_("La moneda debe ser un código ISO 4217 válido (e.g., MXN, USD, EUR).")
            )
        ]
    )

    # Estado de la relación
    activo = models.BooleanField(
        default=True,
        verbose_name=_("Activo"),
        help_text=_("Indica si el vendedor está habilitado para operar.")
    )

    # Dirección (nuevo campo solicitado)
    direccion = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Dirección"),
        help_text=_("Dirección principal del vendedor (opcional).")
    )

    # Datos de contacto adicionales
    direccion_contacto = models.TextField(
        blank=True,
        verbose_name=_("Dirección de Contacto"),
        help_text=_("Dirección física o ubicación de contacto adicional del vendedor (opcional).")
    )
    telefono_contacto = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("Teléfono de Contacto"),
        help_text=_("Número telefónico del vendedor (WhatsApp, celular, fijo, etc., opcional)."),
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{10,15}$',
                message=_("El número de teléfono debe ser válido (10-15 dígitos, opcionalmente con +).")
            )
        ]
    )
    correo_contacto = models.EmailField(
        blank=True,
        verbose_name=_("Correo de Contacto"),
        help_text=_("Correo electrónico adicional de contacto del vendedor (opcional).")
    )
    nombre_comercial = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Nombre Comercial"),
        help_text=_("Nombre de marca o empresa bajo la que trabaja el vendedor (opcional).")
    )

    # Indicador de creación directa
    es_creado_directamente = models.BooleanField(
        default=True,
        verbose_name=_("Creado por Distribuidor"),
        help_text=_("Indica si este vendedor fue creado directamente por el distribuidor.")
    )

    # Fechas de auditoría
    fecha_asignacion = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Fecha de Asignación"),
        help_text=_("Fecha en que se creó la relación (sin auditoría).")
    )
    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Fecha de Creación"),
        help_text=_("Fecha en que se creó la relación (con auditoría).")
    )
    fecha_actualizacion = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Fecha de Última Actualización"),
        help_text=_("Fecha de la última actualización de la relación.")
    )
    fecha_desactivacion = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Fecha de Desactivación"),
        help_text=_("Fecha en que el vendedor fue desactivado, si aplica.")
    )

    # Creador de la relación
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='relaciones_dist_vend_creadas',
        verbose_name=_("Creado por"),
        help_text=_("Usuario que creó esta relación.")
    )

    # Configuraciones adicionales
    configuracion = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Configuraciones"),
        help_text=_("Configuraciones específicas en formato JSON (e.g., límites personalizados, comisiones).")
    )

    class Meta:
        verbose_name = _("Relación Distribuidor-Vendedor")
        verbose_name_plural = _("Relaciones Distribuidor-Vendedor")
        unique_together = ('distribuidor', 'vendedor')
        indexes = [
            models.Index(fields=['distribuidor', 'vendedor']),
            models.Index(fields=['activo']),
            models.Index(fields=['uuid']),
            models.Index(fields=['fecha_creacion']),
            models.Index(fields=['fecha_asignacion']),
            models.Index(fields=['es_creado_directamente']),
            models.Index(fields=['moneda']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(saldo_disponible__lte=models.F('saldo_asignado')),
                name='saldo_disponible_no_excede_asignado',
                violation_error_message=_("El saldo disponible no puede exceder el saldo asignado.")
            ),
            models.CheckConstraint(
                check=models.Q(saldo_disponible__gte=0),
                name='saldo_disponible_no_negativo',
                violation_error_message=_("El saldo disponible no puede ser negativo.")
            ),
            models.CheckConstraint(
                check=models.Q(saldo_inicial__gte=0),
                name='saldo_inicial_no_negativo',
                violation_error_message=_("El saldo inicial no puede ser negativo.")
            ),
        ]

    def __str__(self):
        return f"{self.vendedor.full_name} ({self.moneda} {self.saldo_disponible}) asignado por {self.distribuidor.full_name}"

    def clean(self):
        """
        Validaciones personalizadas antes de guardar.
        """
        if self.distribuidor == self.vendedor:
            raise ValidationError(_("Un usuario no puede ser su propio distribuidor."), code='self_assignment')
        if self.distribuidor.rol != 'distribuidor':
            raise ValidationError(_("El distribuidor debe tener rol 'distribuidor'."), code='invalid_distribuidor_role')
        if self.vendedor.rol != 'vendedor':
            raise ValidationError(_("El vendedor debe tener rol 'vendedor'."), code='invalid_vendedor_role')
        if self.saldo_disponible > self.saldo_asignado:
            raise ValidationError(
                _("El saldo disponible no puede exceder el saldo asignado."), code='saldo_exceed'
            )
        if self.saldo_disponible < 0:
            raise ValidationError(_("El saldo disponible no puede ser negativo."), code='saldo_negative')
        if self.saldo_inicial < 0:
            raise ValidationError(_("El saldo inicial no puede ser negativo."), code='saldo_inicial_negative')
        if self.correo_contacto and self.correo_contacto == self.vendedor.email:
            raise ValidationError(
                _("El correo de contacto no puede ser igual al correo del vendedor."), code='duplicate_email'
            )
        if self.telefono_contacto and not re.match(r'^\+?1?\d{10,15}$', self.telefono_contacto):
            raise ValidationError(
                _("El número de teléfono de contacto debe ser válido (10-15 dígitos, opcionalmente con +)."),
                code='invalid_phone'
            )

    def save(self, *args, **kwargs):
        """
        Sobrescribe save para ejecutar validaciones y registrar auditoría.
        """
        self.full_clean()
        is_new = self.pk is None
        changes = {}

        if not is_new:
            try:
                old_instance = DistribuidorVendedor.objects.get(pk=self.pk)
                fields_to_track = [
                    'saldo_inicial', 'saldo_asignado', 'saldo_disponible', 'activo', 'moneda',
                    'direccion', 'direccion_contacto', 'telefono_contacto', 'correo_contacto',
                    'nombre_comercial', 'es_creado_directamente'
                ]
                for field in fields_to_track:
                    old_value = getattr(old_instance, field)
                    new_value = getattr(self, field)
                    if old_value != new_value:
                        changes[field] = {"before": str(old_value), "after": str(new_value)}
            except DistribuidorVendedor.DoesNotExist:
                changes = {}

        if not is_new and self.activo is False and old_instance.activo is True:
            self.fecha_desactivacion = timezone.now()
        elif not is_new and self.activo is True and old_instance.activo is False:
            self.fecha_desactivacion = None

        # Initialize saldo_asignado and saldo_disponible with saldo_inicial if new
        if is_new and self.saldo_inicial > 0:
            self.saldo_asignado = self.saldo_inicial
            self.saldo_disponible = self.saldo_inicial

        super().save(*args, **kwargs)

        # Registrar en log de auditoría
        if is_new:
            DistribuidorVendedorChangeLog.objects.create(
                relacion=self,
                changed_by=self.creado_por,
                change_type='create',
                change_description=_("Creación de relación distribuidor-vendedor")
            )
        elif changes:
            DistribuidorVendedorChangeLog.objects.create(
                relacion=self,
                changed_by=self.creado_por,
                change_type='update',
                change_description=_("Actualización de: ") + ', '.join(changes.keys()),
                details=changes
            )

    def asignar_saldo(self, monto, moneda=None, changed_by=None):
        """
        Asigna saldo adicional al vendedor, actualizando moneda si es necesario.
        """
        if monto <= 0:
            raise ValueError(_("El monto debe ser positivo."), code='invalid_monto')
        if moneda and moneda != self.moneda:
            raise ValueError(_("La moneda no coincide con la configurada."), code='moneda_mismatch')

        self.saldo_asignado += Decimal(str(monto))
        self.saldo_disponible += Decimal(str(monto))
        self.save()

        DistribuidorVendedorChangeLog.objects.create(
            relacion=self,
            changed_by=changed_by,
            change_type='update',
            change_description=_("Asignación de saldo"),
            details={"monto": str(monto), "moneda": self.moneda}
        )

    def descontar_saldo(self, monto, moneda=None, changed_by=None):
        """
        Descuenta saldo del vendedor, con validaciones estrictas.
        """
        if monto <= 0:
            raise ValueError(_("El monto debe ser positivo."), code='invalid_monto')
        if moneda and moneda != self.moneda:
            raise ValueError(_("La moneda no coincide con la configurada."), code='moneda_mismatch')
        if monto > self.saldo_disponible:
            raise ValueError(_("Saldo insuficiente."), code='insufficient_saldo')

        self.saldo_disponible -= Decimal(str(monto))
        self.save()

        DistribuidorVendedorChangeLog.objects.create(
            relacion=self,
            changed_by=changed_by,
            change_type='update',
            change_description=_("Descuento de saldo"),
            details={"monto": str(monto), "moneda": self.moneda}
        )

    def desactivar(self, changed_by=None):
        """
        Desactiva la relación, registrando la acción.
        """
        if not self.activo:
            raise ValueError(_("La relación ya está desactivada."), code='already_deactivated')
        self.activo = False
        self.fecha_desactivacion = timezone.now()
        self.save()

        DistribuidorVendedorChangeLog.objects.create(
            relacion=self,
            changed_by=changed_by,
            change_type='deactivate',
            change_description=_("Desactivación de vendedor")
        )

    def reactivar(self, changed_by=None):
        """
        Reactiva la relación, limpiando la fecha de desactivación.
        """
        if self.activo:
            raise ValueError(_("La relación ya está activa."), code='already_active')
        self.activo = True
        self.fecha_desactivacion = None
        self.save()

        DistribuidorVendedorChangeLog.objects.create(
            relacion=self,
            changed_by=changed_by,
            change_type='reactivate',
            change_description=_("Reactivación de vendedor")
        )


class DistribuidorVendedorChangeLog(models.Model):
    """
    Registro de auditoría para cambios en DistribuidorVendedor.
    """
    relacion = models.ForeignKey(
        DistribuidorVendedor,
        on_delete=models.CASCADE,
        related_name='change_logs',
        verbose_name=_("Relación"),
        help_text=_("Relación distribuidor-vendedor asociada.")
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='dist_vend_changes',
        verbose_name=_("Modificado por"),
        help_text=_("Usuario que realizó el cambio.")
    )
    change_type = models.CharField(
        max_length=50,
        choices=[
            ('create', _('Creación')),
            ('update', _('Actualización')),
            ('deactivate', _('Desactivación')),
            ('reactivate', _('Reactivación')),
        ],
        verbose_name=_("Tipo de cambio"),
        help_text=_("Tipo de cambio realizado.")
    )
    change_description = models.TextField(
        verbose_name=_("Descripción"),
        blank=True,
        help_text=_("Descripción del cambio realizado.")
    )
    details = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Detalles"),
        help_text=_("Detalles específicos del cambio en formato JSON.")
    )
    timestamp = models.DateTimeField(
        default=timezone.now,
        verbose_name=_("Fecha"),
        help_text=_("Fecha y hora del cambio.")
    )

    class Meta:
        verbose_name = _("Registro de Cambio Distribuidor-Vendedor")
        verbose_name_plural = _("Registros de Cambios Distribuidor-Vendedor")
        indexes = [
            models.Index(fields=['relacion', 'timestamp']),
            models.Index(fields=['change_type']),
        ]

    def __str__(self):
        return f"{self.change_type} en {self.relacion} ({self.timestamp})"