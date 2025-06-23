"""
Modelos para el módulo Central de Gestión de Líneas en MexaRed.
Define la entidad Linea para gestionar SIMs (físicas y eSIMs) con trazabilidad, auditoría organizada y soporte para jerarquías.
Cumple con estándares internacionales (PCI DSS, SOC2, ISO 27001) y está optimizado para alto volumen, búsquedas rápidas y auditorías financieras.
Integrado con apps.users, apps.vendedores, apps.wallet y apps.activaciones para operaciones de jerarquía, pagos y activaciones.
"""

import logging
import uuid
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _
from django.core.validators import RegexValidator, MinValueValidator
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal
from apps.users.models import User, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR
from apps.vendedores.models import DistribuidorVendedor
from apps.activaciones.models import Activacion

# Configuración de logging para auditoría en producción
logger = logging.getLogger(__name__)

# Enumeradores para estandarización y claridad
TIPO_SIM = (
    ('physical', _('SIM Física')),
    ('esim', _('eSIM')),
)

CATEGORIAS_SERVICIO = (
    ('movilidad', _('Movilidad')),
    ('mifi', _('MiFi')),
    ('iot', _('IoT')),
    ('hbb', _('Internet en el Hogar')),
)

ESTADO_LINEA = (
    ('idle', _('Nunca Activada')),
    ('assigned', _('Asignada y Activa')),
    ('suspended', _('Suspendida')),
    ('cancelled', _('Cancelada')),
    ('port-out', _('Portada Fuera')),
    ('processing', _('Portabilidad en Proceso')),
)

PORTABILIDAD_STATUS = (
    ('pending', _('Pendiente')),
    ('processing', _('Procesando')),
    ('completed', _('Completada')),
    ('rejected', _('Rechazada')),
)

class Linea(models.Model):
    """
    Modelo central para gestionar líneas telefónicas (SIMs) en MexaRed.
    Soporta SIMs físicas y eSIMs, con auditoría, jerarquías y métricas de consumo.
    Integrado con Addinteli API para estados y recargas en tiempo real.
    Optimizado para búsquedas rápidas, auditorías financieras y escalabilidad multinivel.
    """
    uuid = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("UUID"),
        help_text=_("Identificador único universal para la línea.")
    )
    msisdn = models.CharField(
        max_length=15,
        unique=True,
        validators=[
            RegexValidator(
                regex=r'^\+?\d{10,15}$',
                message=_("El MSISDN debe ser un número telefónico válido (10-15 dígitos, opcionalmente con +).")
            )
        ],
        verbose_name=_("Número Telefónico (MSISDN)"),
        help_text=_("Número telefónico asociado a la SIM (e.g., +521234567890).")
    )
    iccid = models.CharField(
        max_length=22,
        unique=True,
        db_index=True,
        validators=[
            RegexValidator(
                regex=r'^\d{19,22}$',
                message=_("El ICCID debe ser un número de 19 a 22 dígitos.")
            )
        ],
        verbose_name=_("ICCID"),
        help_text=_("Identificador único de la SIM (19-22 dígitos).")
    )
    tipo_sim = models.CharField(
        max_length=10,
        choices=TIPO_SIM,
        default='physical',
        verbose_name=_("Tipo de SIM"),
        help_text=_("Indica si la SIM es física o eSIM.")
    )
    categoria_servicio = models.CharField(
        max_length=20,
        choices=CATEGORIAS_SERVICIO,
        default='movilidad',
        verbose_name=_("Categoría de Servicio"),
        help_text=_("Categoría de servicio asociado (Movilidad, MiFi, IoT, HBB).")
    )
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_LINEA,
        default='idle',
        verbose_name=_("Estado de la Línea"),
        help_text=_("Estado actual de la línea (e.g., asignada, suspendida, portada).")
    )

    # Relaciones jerárquicas
    distribuidor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lineas_distribuidor',
        limit_choices_to={'rol': ROLE_DISTRIBUIDOR},
        verbose_name=_("Distribuidor"),
        help_text=_("Distribuidor responsable de la línea.")
    )
    vendedor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lineas_vendedor',
        limit_choices_to={'rol': ROLE_VENDEDOR},
        verbose_name=_("Vendedor"),
        help_text=_("Vendedor asignado a la línea.")
    )

    # Fechas de auditoría
    fecha_activacion = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Fecha de Activación"),
        help_text=_("Fecha en que la línea fue activada.")
    )
    fecha_suspension = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Fecha de Suspensión"),
        help_text=_("Fecha en que la línea fue suspendida.")
    )
    fecha_baja = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Fecha de Baja"),
        help_text=_("Fecha en que la línea fue dada de baja permanentemente.")
    )
    fecha_registro = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Fecha de Registro"),
        help_text=_("Fecha de creación del registro en el sistema.")
    )
    fecha_actualizacion = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Fecha de Actualización"),
        help_text=_("Fecha de la última actualización del registro.")
    )

    # Portabilidad
    portability_status = models.CharField(
        max_length=20,
        choices=PORTABILIDAD_STATUS,
        null=True,
        blank=True,
        verbose_name=_("Estado de Portabilidad"),
        help_text=_("Estado del proceso de portabilidad (e.g., pendiente, procesando).")
    )
    port_in_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Fecha de Port-in"),
        help_text=_("Fecha en que la línea fue portada hacia la plataforma.")
    )
    port_out_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Fecha de Port-out"),
        help_text=_("Fecha en que la línea fue portada fuera de la plataforma.")
    )

    # Consumo y beneficios
    fecha_ultima_recarga = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Fecha de Última Recarga"),
        help_text=_("Fecha de la última recarga registrada.")
    )
    fecha_vencimiento_plan = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Fecha de Vencimiento del Plan"),
        help_text=_("Fecha de vencimiento del plan actual.")
    )
    dias_disponibles = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name=_("Días Disponibles"),
        help_text=_("Días restantes de vigencia del plan actual.")
    )
    datos_consumidos = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name=_("Datos Consumidos (MB)"),
        help_text=_("Cantidad de datos consumidos en el plan actual (en MB).")
    )
    datos_disponibles = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name=_("Datos Disponibles (MB)"),
        help_text=_("Cantidad de datos disponibles en el plan actual (en MB).")
    )
    minutos_consumidos = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name=_("Minutos Consumidos"),
        help_text=_("Minutos de voz consumidos en el plan actual.")
    )
    minutos_disponibles = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name=_("Minutos Disponibles"),
        help_text=_("Minutos de voz disponibles en el plan actual.")
    )
    sms_consumidos = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name=_("SMS Consumidos"),
        help_text=_("Mensajes SMS consumidos en el plan actual.")
    )
    sms_disponibles = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name=_("SMS Disponibles"),
        help_text=_("Mensajes SMS disponibles en el plan actual.")
    )

    # Auditoría
    creado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lineas_creadas',
        verbose_name=_("Creado Por"),
        help_text=_("Usuario que creó el registro de la línea.")
    )
    actualizado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lineas_actualizadas',
        verbose_name=_("Actualizado Por"),
        help_text=_("Usuario que realizó la última actualización.")
    )

    class Meta:
        verbose_name = _("Línea de Servicio")
        verbose_name_plural = _("Líneas de Servicio")
        indexes = [
            models.Index(fields=['msisdn'], name='linea_msisdn_idx'),
            models.Index(fields=['iccid'], name='linea_iccid_idx'),
            models.Index(fields=['estado'], name='linea_estado_idx'),
            models.Index(fields=['distribuidor', 'estado'], name='linea_distribuidor_estado_idx'),
            models.Index(fields=['vendedor', 'estado'], name='linea_vendedor_estado_idx'),
            models.Index(fields=['fecha_vencimiento_plan'], name='linea_vencimiento_idx'),
            models.Index(fields=['portability_status'], name='linea_portability_idx'),
            models.Index(fields=['fecha_activacion'], name='linea_activacion_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(dias_disponibles__gte=0),
                name='linea_non_negative_dias',
                violation_error_message=_("Los días disponibles no pueden ser negativos.")
            ),
            models.UniqueConstraint(
                fields=['msisdn'],
                name='linea_unique_msisdn',
                violation_error_message=_("El MSISDN ya está registrado.")
            ),
            models.UniqueConstraint(
                fields=['iccid'],
                name='linea_unique_iccid',
                violation_error_message=_("El ICCID ya está registrado.")
            ),
        ]

    def __str__(self):
        return f"{self.msisdn} ({self.get_estado_display()})"

    def clean(self):
        """
        Valida la integridad de los datos antes de guardar.
        Asegura consistencia en jerarquías, estados, métricas de consumo y transiciones de estado.
        """
        super().clean()
        # Validar relación distribuidor-vendedor
        if self.vendedor and self.distribuidor:
            if not DistribuidorVendedor.objects.filter(
                distribuidor=self.distribuidor,
                vendedor=self.vendedor,
                activo=True
            ).exists():
                raise ValidationError(
                    _("El vendedor no está asignado al distribuidor especificado."),
                    code='invalid_distribuidor_vendedor'
                )
        # Validar fechas coherentes
        if self.fecha_suspension and self.fecha_activacion and self.fecha_suspension < self.fecha_activacion:
            raise ValidationError(
                _("La fecha de suspensión no puede ser anterior a la fecha de activación."),
                code='invalid_suspension_date'
            )
        if self.fecha_baja and self.fecha_activacion and self.fecha_baja < self.fecha_activacion:
            raise ValidationError(
                _("La fecha de baja no puede ser anterior a la fecha de activación."),
                code='invalid_baja_date'
            )
        # Validar estado y portability_status
        if self.estado == 'processing' and not self.portability_status:
            raise ValidationError(
                _("Una línea en estado 'processing' debe tener un estado de portabilidad definido."),
                code='missing_portability_status'
            )
        if self.portability_status and self.estado != 'processing':
            raise ValidationError(
                _("El estado de portabilidad solo puede definirse si el estado es 'processing'."),
                code='invalid_portability_status'
            )
        # Validar métricas de consumo
        if self.datos_consumidos > self.datos_disponibles:
            raise ValidationError(
                _("Los datos consumidos no pueden exceder los datos disponibles."),
                code='invalid_datos_consumidos'
            )
        if self.minutos_consumidos > self.minutos_disponibles:
            raise ValidationError(
                _("Los minutos consumidos no pueden exceder los minutos disponibles."),
                code='invalid_minutos_consumidos'
            )
        if self.sms_consumidos > self.sms_disponibles:
            raise ValidationError(
                _("Los SMS consumidos no pueden exceder los SMS disponibles."),
                code='invalid_sms_consumidos'
            )
        # Validar estado 'assigned' requiere activación exitosa
        if self.estado == 'assigned':
            if not Activacion.objects.filter(
                iccid=self.iccid,
                estado='exitosa'
            ).exists():
                raise ValidationError(
                    _("El estado 'assigned' requiere una activación exitosa registrada."),
                    code='invalid_assigned_state'
                )
            if not self.fecha_activacion:
                raise ValidationError(
                    _("El estado 'assigned' requiere una fecha de activación definida."),
                    code='missing_fecha_activacion'
                )

    def save(self, *args, **kwargs):
        """
        Sobrescribe save para ejecutar validaciones y registrar auditoría.
        Integra con UserChangeLog para trazabilidad completa.
        Detecta creaciones de forma robusta para DRF, Admin, Shell y cargas masivas.
        """
        from apps.users.models import UserChangeLog  # Evitar importación circular
        with transaction.atomic():
            self.full_clean()
            is_new = self._state.adding or self.pk is None
            changes = {}

            if not is_new:
                try:
                    old_instance = type(self)._default_manager.select_for_update().filter(pk=self.pk).first()
                    if old_instance:
                        fields_to_track = [
                            'msisdn', 'iccid', 'tipo_sim', 'categoria_servicio', 'estado',
                            'distribuidor', 'vendedor', 'fecha_activacion', 'fecha_suspension',
                            'fecha_baja', 'portability_status', 'fecha_ultima_recarga',
                            'fecha_vencimiento_plan', 'dias_disponibles', 'datos_consumidos',
                            'datos_disponibles', 'minutos_consumidos', 'minutos_disponibles',
                            'sms_consumidos', 'sms_disponibles'
                        ]
                        for field in fields_to_track:
                            old_value = getattr(old_instance, field)
                            new_value = getattr(self, field)
                            if field in ['distribuidor', 'vendedor'] and old_value:
                                old_value = old_value.username if old_value else None
                            if field in ['distribuidor', 'vendedor'] and new_value:
                                new_value = new_value.username if new_value else None
                            if old_value != new_value:
                                changes[field] = {"before": str(old_value), "after": str(new_value)}
                except Exception as e:
                    logger.warning(
                        f"Error leyendo old_instance para auditoría de línea {self.msisdn} (pk: {self.pk}): {str(e)}"
                    )

            super().save(*args, **kwargs)

            # Registrar auditoría
            if is_new:
                UserChangeLog.objects.create(
                    user=self.distribuidor or self.vendedor or self.creado_por,
                    changed_by=self.creado_por,
                    change_type='create',
                    change_description=_("Creación de línea"),
                    details={
                        "msisdn": self.msisdn,
                        "iccid": self.iccid,
                        "estado": self.estado,
                        "distribuidor": self.distribuidor.username if self.distribuidor else None,
                        "vendedor": self.vendedor.username if self.vendedor else None,
                        "timestamp": timezone.now().isoformat()
                    }
                )
                logger.info(f"Línea creada: {self.msisdn} (ICCID: {self.iccid}, estado: {self.estado})")
            elif changes:
                UserChangeLog.objects.create(
                    user=self.distribuidor or self.vendedor or self.actualizado_por,
                    changed_by=self.actualizado_por,
                    change_type='update',
                    change_description=_("Actualización de línea: ") + ', '.join(changes.keys()),
                    details={
                        **changes,
                        "timestamp": timezone.now().isoformat()
                    }
                )
                logger.info(f"Línea actualizada: {self.msisdn} (ICCID: {self.iccid}, cambios: {changes})")

class AsignacionBackup(models.Model):
    """
    Modelo para almacenar respaldos de asignaciones previas de líneas a distribuidores.
    Proporciona trazabilidad para auditorías y recuperación de asignaciones.
    """
    linea = models.ForeignKey(
        "Linea",
        on_delete=models.CASCADE,
        related_name="backups",
        verbose_name=_("Línea"),
        help_text=_("Línea asociada al respaldo.")
    )
    distribuidor_anterior = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'rol': ROLE_DISTRIBUIDOR},
        related_name="lineas_respaldo",
        verbose_name=_("Distribuidor Anterior"),
        help_text=_("Distribuidor previamente asignado a la línea.")
    )
    fecha_respaldo = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Fecha de Respaldo"),
        help_text=_("Fecha en que se creó el respaldo.")
    )
    creado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="respaldos_creados",
        verbose_name=_("Creado Por"),
        help_text=_("Usuario que creó el respaldo.")
    )

    class Meta:
        verbose_name = _("Respaldo de Asignación")
        verbose_name_plural = _("Respaldos de Asignaciones")
        indexes = [
            models.Index(fields=['linea', 'fecha_respaldo'], name='asign_backup_lf_idx'),
            models.Index(fields=['distribuidor_anterior'], name='asign_backup_d_idx'),
        ]

    def __str__(self):
        return f"{self.linea.msisdn} respaldada el {self.fecha_respaldo.strftime('%Y-%m-%d %H:%M')}"