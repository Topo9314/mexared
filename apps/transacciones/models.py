"""
Modelos para la gestión de transacciones financieras en MexaRed.
Proporciona una estructura robusta para registrar movimientos de saldo, auditoría detallada,
soporte multi-moneda y escalabilidad para integraciones externas (APIs, sistemas bancarios, blockchain).
Incluye auditoría de acciones internas y catálogo de motivos para granularidad avanzada.
"""

import uuid
import logging
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, RegexValidator
from django.core.exceptions import ValidationError

# Configuración de logging para monitoreo en producción
logger = logging.getLogger(__name__)

# ============================
# 🔸 Constantes globales
# ============================

ESTADO_TRANSACCION_CHOICES = [
    ('PENDIENTE', _('Pendiente')),
    ('EXITOSA', _('Exitosa')),
    ('FALLIDA', _('Fallida')),
    ('CANCELADA', _('Cancelada')),
]

TIPO_AUDITORIA_CHOICES = [
    ('CREACION', _('Creación de transacción')),
    ('MODIFICACION', _('Modificación de transacción')),
    ('CANCELACION', _('Cancelación de transacción')),
    ('REINTENTO', _('Reintento de transacción')),
]

# ============================
# 🔹 MODELO DE TRANSACCIÓN
# ============================

class Transaccion(models.Model):
    """
    Registro principal de operaciones económicas en MexaRed.
    Gestiona asignaciones, retiros, consumos API, devoluciones, ajustes y reversos con auditoría completa.
    """
    TIPO_CHOICES = [
        ('ASIGNACION', _('Asignación de saldo')),
        ('RETIRO', _('Retiro de saldo')),
        ('CONSUMO_API', _('Consumo vía API')),
        ('DEVOLUCION', _('Devolución de saldo')),
        ('AJUSTE_MANUAL', _('Ajuste manual')),
        ('CARGA', _('Recarga de saldo')),
        ('REVERSO', _('Reverso de transacción')),
    ]

    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        verbose_name=_("UUID"),
        help_text=_("Identificador único universal para la transacción.")
    )
    tipo = models.CharField(
        _("Tipo de transacción"),
        max_length=30,
        choices=TIPO_CHOICES,
        help_text=_("Clasificación de la transacción (e.g., asignación, consumo API, reverso).")
    )
    motivo = models.ForeignKey(
        'MotivoTransaccion',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transacciones_rel',
        verbose_name=_("Motivo"),
        help_text=_("Motivo específico de la transacción (opcional).")
    )
    descripcion = models.TextField(
        _("Descripción"),
        blank=True,
        help_text=_("Detalles adicionales sobre la transacción.")
    )
    comentario_reverso = models.TextField(
        _("Comentario del reverso"),
        null=True,
        blank=True,
        help_text=_("Comentario obligatorio para transacciones de tipo REVERSO.")
    )
    monto = models.DecimalField(
        _("Monto"),
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
        help_text=_("Cantidad económica de la transacción.")
    )
    moneda = models.ForeignKey(
        'Moneda',
        on_delete=models.PROTECT,
        related_name='transacciones_rel',
        verbose_name=_("Moneda"),
        help_text=_("Moneda de la transacción (e.g., MXN, USD).")
    )
    tasa_cambio = models.DecimalField(
        _("Tasa de cambio"),
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0001)],
        help_text=_("Tasa de cambio aplicada si la moneda no es la base (opcional).")
    )
    emisor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='transacciones_emitidas_rel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Emisor"),
        help_text=_("Usuario que inicia la transacción (e.g., admin, distribuidor).")
    )
    receptor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='transacciones_recibidas_rel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Receptor"),
        help_text=_("Usuario que recibe la transacción (e.g., distribuidor, vendedor).")
    )
    estado = models.CharField(
        _("Estado"),
        max_length=20,
        choices=ESTADO_TRANSACCION_CHOICES,
        default='PENDIENTE',
        help_text=_("Estado actual de la transacción.")
    )
    referencia_externa = models.CharField(
        _("Referencia externa"),
        max_length=100,
        blank=True,
        null=True,
        help_text=_("Identificador de sistemas externos, como APIs de pago.")
    )
    fecha_creacion = models.DateTimeField(
        _("Fecha de creación"),
        auto_now_add=True,
        help_text=_("Fecha y hora en que se creó la transacción.")
    )
    fecha_actualizacion = models.DateTimeField(
        _("Fecha de actualización"),
        auto_now=True,
        help_text=_("Fecha y hora de la última actualización.")
    )
    realizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='acciones_transacciones_rel',
        verbose_name=_("Realizado por"),
        help_text=_("Usuario que ejecutó la transacción (admin o sistema).")
    )

    class Meta:
        verbose_name = _("Transacción")
        verbose_name_plural = _("Transacciones")
        ordering = ['-fecha_creacion']
        indexes = [
            models.Index(fields=['tipo', 'estado'], name='idx_transaccion_tipo_estado'),
            models.Index(fields=['fecha_creacion'], name='idx_transaccion_fecha_creacion'),
            models.Index(fields=['emisor'], name='idx_transaccion_emisor'),
            models.Index(fields=['receptor'], name='idx_transaccion_receptor'),
            models.Index(fields=['moneda'], name='idx_transaccion_moneda'),
            models.Index(fields=['uuid'], name='idx_transaccion_uuid'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(monto__gt=0),
                name='transaccion_monto_positivo'
            ),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.monto} {self.moneda.codigo} - {self.get_estado_display()}"

    def clean(self):
        """
        Validaciones personalizadas para la transacción.
        """
        super().clean()
        if self.emisor and self.emisor.rol not in ['admin', 'distribuidor']:
            logger.error(f"Emisor {self.emisor.username} no es administrador ni distribuidor")
            raise ValidationError(_("El emisor debe ser un administrador o distribuidor."))
        if self.receptor and self.receptor.rol not in ['distribuidor', 'vendedor']:
            logger.error(f"Receptor {self.receptor.username} no es distribuidor ni vendedor")
            raise ValidationError(_("El receptor debe ser un distribuidor o vendedor."))
        if self.tipo in ['ASIGNACION', 'DEVOLUCION', 'REVERSO'] and not self.receptor:
            logger.error(f"Receptor requerido para tipo {self.tipo}")
            raise ValidationError(_("Se requiere un receptor para asignaciones, devoluciones o reversos."))
        if self.tipo == 'RETIRO' and not self.emisor:
            logger.error("Emisor requerido para RETIRO")
            raise ValidationError(_("Se requiere un emisor para retiros."))
        if self.tasa_cambio and self.tasa_cambio <= 0:
            logger.error(f"Tasa de cambio inválida: {self.tasa_cambio}")
            raise ValidationError(_("La tasa de cambio debe ser mayor a cero."))
        if self.realizado_por and self.realizado_por.rol not in ['admin', 'distribuidor']:
            logger.error(f"Realizado por {self.realizado_por.username} no es administrador ni distribuidor")
            raise ValidationError(_("Solo administradores o distribuidores pueden realizar transacciones."))
        if self.emisor and self.receptor and self.emisor == self.receptor:
            logger.error(f"Emisor y receptor no pueden ser el mismo: {self.emisor.username}")
            raise ValidationError(_("El emisor y el receptor no pueden ser el mismo usuario."))
        if self.tipo == 'REVERSO':
            if not self.comentario_reverso or len(self.comentario_reverso.strip()) < 5:
                logger.error(f"Comentario de reverso inválido: {self.comentario_reverso}")
                raise ValidationError(_("El comentario de reverso es obligatorio y debe tener al menos 5 caracteres."))

    def save(self, *args, **kwargs):
        """
        Ejecuta validaciones, registra la transacción en UserChangeLog y crea auditoría interna.
        """
        from apps.users.models import UserChangeLog  # Importación tardía para evitar dependencias circulares

        self.full_clean()
        is_new = self.pk is None
        changes = {}
        if not is_new:
            try:
                old_instance = Transaccion.objects.get(pk=self.pk)
                fields_to_track = ['tipo', 'monto', 'moneda', 'estado', 'descripcion', 'comentario_reverso']
                for field in fields_to_track:
                    old_value = getattr(old_instance, field)
                    new_value = getattr(self, field)
                    if old_value != new_value:
                        changes[field] = {"before": str(old_value), "after": str(new_value)}
            except Transaccion.DoesNotExist:
                changes = {}

        super().save(*args, **kwargs)

        # Registrar en UserChangeLog para el emisor o receptor
        user = self.receptor or self.emisor
        if user:
            UserChangeLog.objects.create(
                user=user,
                changed_by=self.realizado_por,
                change_type='update',
                change_description=f"Transacción {self.get_tipo_display()} ({self.monto} {self.moneda.codigo})",
                details={
                    "tipo": self.tipo,
                    "monto": str(self.monto),
                    "moneda": self.moneda.codigo,
                    "estado": self.estado,
                    "emisor": self.emisor.username if self.emisor else None,
                    "receptor": self.receptor.username if self.receptor else None,
                    "referencia_externa": self.referencia_externa,
                    "motivo": self.motivo.descripcion if self.motivo else None,
                    "comentario_reverso": self.comentario_reverso
                }
            )

        # Registrar en AuditoriaTransaccion
        AuditoriaTransaccion.objects.create(
            transaccion=self,
            tipo='CREACION' if is_new else 'MODIFICACION',
            usuario=self.realizado_por,
            detalles=changes if not is_new else {"evento": "Creación de transacción"}
        )

# ============================
# 🔹 HISTORIAL DE SALDO
# ============================

class HistorialSaldo(models.Model):
    """
    Registro del historial de saldos de usuarios tras cada transacción.
    Proporciona auditoría detallada de cambios en el saldo.
    """
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='historial_saldos_rel',
        verbose_name=_("Usuario"),
        help_text=_("Usuario cuyo saldo cambió.")
    )
    saldo_antes = models.DecimalField(
        _("Saldo antes"),
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.00)],
        help_text=_("Saldo del usuario antes de la transacción.")
    )
    saldo_despues = models.DecimalField(
        _("Saldo después"),
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.00)],
        help_text=_("Saldo del usuario después de la transacción.")
    )
    transaccion = models.ForeignKey(
        Transaccion,
        on_delete=models.CASCADE,
        related_name='historiales_rel',
        verbose_name=_("Transacción"),
        help_text=_("Transacción que generó el cambio de saldo.")
    )
    fecha = models.DateTimeField(
        _("Fecha"),
        auto_now_add=True,
        help_text=_("Fecha y hora del cambio de saldo.")
    )

    class Meta:
        verbose_name = _("Historial de Saldo")
        verbose_name_plural = _("Historiales de Saldo")
        ordering = ['-fecha']
        indexes = [
            models.Index(fields=['usuario', 'fecha'], name='idx_histsaldo_usuario_fecha'),
            models.Index(fields=['transaccion'], name='idx_histsaldo_transaccion'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(saldo_antes__gte=0),
                name='histsaldo_saldo_antes_no_negativo'
            ),
            models.CheckConstraint(
                check=models.Q(saldo_despues__gte=0),
                name='histsaldo_saldo_despues_no_negativo'
            ),
        ]

    def __str__(self):
        return f"Saldo {self.saldo_despues} para {self.usuario.username} ({self.fecha})"

    def clean(self):
        """
        Validaciones personalizadas para el historial de saldo.
        """
        if self.usuario.rol not in ['distribuidor', 'vendedor']:
            logger.error(f"Usuario {self.usuario.username} no es distribuidor ni vendedor")
            raise ValidationError(_("El usuario debe ser un distribuidor o vendedor."))
        if self.saldo_antes < 0 or self.saldo_despues < 0:
            logger.error(f"Saldos negativos detectados: antes={self.saldo_antes}, después={self.saldo_despues}")
            raise ValidationError(_("Los saldos antes y después no pueden ser negativos."))
        if self.transaccion.estado not in ['EXITOSA', 'PENDIENTE']:
            logger.error(f"Transacción {self.transaccion.id} no está en estado EXITOSA o PENDIENTE")
            raise ValidationError(_("Solo transacciones exitosas o pendientes pueden registrar historial de saldo."))

# ============================
# 🔹 MONEDA
# ============================

class Moneda(models.Model):
    """
    Registro de monedas soportadas para transacciones internacionales.
    Permite gestionar códigos ISO 4217, nombres, símbolos y tasas de cambio.
    """
    codigo = models.CharField(
        _("Código"),
        max_length=3,
        unique=True,
        validators=[
            RegexValidator(
                regex=r'^[A-Z]{3}$',
                message=_("El código debe ser un código ISO 4217 válido (e.g., MXN, USD).")
            )
        ],
        help_text=_("Código ISO 4217 de la moneda (e.g., MXN, USD, EUR).")
    )
    nombre = models.CharField(
        _("Nombre"),
        max_length=50,
        help_text=_("Nombre completo de la moneda (e.g., Peso Mexicano).")
    )
    simbolo = models.CharField(
        _("Símbolo"),
        max_length=5,
        help_text=_("Símbolo de la moneda (e.g., $, €).")
    )
    tasa_cambio_usd = models.DecimalField(
        _("Tasa de cambio a USD"),
        max_digits=10,
        decimal_places=4,
        validators=[MinValueValidator(0.0001)],
        help_text=_("Tasa de cambio respecto al dólar estadounidense (1 unidad = X USD).")
    )
    fecha_actualizacion = models.DateTimeField(
        _("Fecha de actualización"),
        auto_now=True,
        help_text=_("Fecha de la última actualización de la tasa de cambio.")
    )

    class Meta:
        verbose_name = _("Moneda")
        verbose_name_plural = _("Monedas")
        ordering = ['codigo']
        indexes = [
            models.Index(fields=['codigo'], name='idx_moneda_codigo'),
        ]

    def __str__(self):
        return f"{self.codigo} ({self.simbolo})"

    def clean(self):
        """
        Validaciones personalizadas para la moneda.
        """
        if self.tasa_cambio_usd <= 0:
            logger.error(f"Tasa de cambio a USD inválida: {self.tasa_cambio_usd}")
            raise ValidationError(_("La tasa de cambio a USD debe ser mayor a cero."))

# ============================
# 🔹 MOTIVO DE TRANSACCIÓN
# ============================

class MotivoTransaccion(models.Model):
    """
    Catálogo de motivos para transacciones, permite granularidad en la clasificación.
    Ejemplo: 'Retiro por error de sistema', 'Asignación automática semanal'.
    """
    codigo = models.CharField(
        _("Código"),
        max_length=20,
        unique=True,
        validators=[
            RegexValidator(
                regex=r'^[A-Z0-9_]+$',
                message=_("El código debe contener solo letras mayúsculas, números y guiones bajos.")
            )
        ],
        help_text=_("Código único para identificar el motivo (e.g., ERROR_SISTEMA).")
    )
    descripcion = models.CharField(
        _("Descripción"),
        max_length=150,
        help_text=_("Descripción detallada del motivo de la transacción.")
    )
    activo = models.BooleanField(
        _("Activo"),
        default=True,
        help_text=_("Indica si el motivo está disponible para nuevas transacciones.")
    )
    fecha_creacion = models.DateTimeField(
        _("Fecha de creación"),
        auto_now_add=True
    )

    class Meta:
        verbose_name = _("Motivo de Transacción")
        verbose_name_plural = _("Motivos de Transacción")
        ordering = ['codigo']
        indexes = [
            models.Index(fields=['codigo'], name='idx_motivotrans_codigo'),
            models.Index(fields=['activo'], name='idx_motivotrans_activo'),
        ]

    def __str__(self):
        return f"{self.codigo}: {self.descripcion}"

    def clean(self):
        """
        Validaciones personalizadas para el motivo.
        """
        if not self.codigo:
            logger.error("Código de motivo vacío")
            raise ValidationError(_("El código es obligatorio."))

# ============================
# 🔹 AUDITORÍA DE TRANSACCIÓN
# ============================

class AuditoriaTransaccion(models.Model):
    """
    Registro de auditoría para acciones internas sobre transacciones.
    Rastrea creaciones, modificaciones, cancelaciones y reintentos.
    """
    transaccion = models.ForeignKey(
        Transaccion,
        on_delete=models.CASCADE,
        related_name='auditorias_rel',
        verbose_name=_("Transacción"),
        help_text=_("Transacción asociada a la acción.")
    )
    tipo = models.CharField(
        _("Tipo de auditoría"),
        max_length=20,
        choices=TIPO_AUDITORIA_CHOICES,
        help_text=_("Tipo de acción realizada sobre la transacción.")
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='auditorias_transacciones_rel',
        verbose_name=_("Usuario"),
        help_text=_("Usuario que realizó la acción (admin o sistema).")
    )
    detalles = models.JSONField(
        _("Detalles"),
        default=dict,
        blank=True,
        help_text=_("Detalles de la acción en formato JSON (e.g., cambios realizados).")
    )
    fecha = models.DateTimeField(
        _("Fecha"),
        auto_now_add=True,
        help_text=_("Fecha y hora de la acción.")
    )

    class Meta:
        verbose_name = _("Auditoría de Transacción")
        verbose_name_plural = _("Auditorías de Transacciones")
        ordering = ['-fecha']
        indexes = [
            models.Index(fields=['transaccion', 'fecha'], name='idx_audtrans_transaccion_fecha'),
            models.Index(fields=['tipo'], name='idx_audtrans_tipo'),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} en {self.transaccion} ({self.fecha})"

    def clean(self):
        """
        Validaciones personalizadas para la auditoría.
        """
        if self.usuario and self.usuario.rol not in ['admin', 'distribuidor']:
            logger.error(f"Usuario {self.usuario.username} no es administrador ni distribuidor")
            raise ValidationError(_("El usuario debe ser un administrador o distribuidor."))

# ============================
# 🔹 SALDO
# ============================

class Saldo(models.Model):
    """
    Registro del saldo disponible para un usuario con rol distribuidor.
    Gestiona el saldo asociado a cada distribuidor para transacciones financieras.
    """
    distribuidor = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='saldo',
        verbose_name=_("Distribuidor"),
        help_text=_("Usuario con rol distribuidor asociado al saldo."),
        limit_choices_to={'rol': 'distribuidor'}
    )
    cantidad = models.DecimalField(
        _("Cantidad"),
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text=_("Saldo disponible del distribuidor.")
    )
    fecha_actualizacion = models.DateTimeField(
        _("Fecha de actualización"),
        auto_now=True,
        help_text=_("Fecha y hora de la última actualización del saldo.")
    )

    class Meta:
        verbose_name = _("Saldo")
        verbose_name_plural = _("Saldos")
        indexes = [
            models.Index(fields=['distribuidor'], name='idx_saldo_distribuidor'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(cantidad__gte=0),
                name='saldo_cantidad_no_negativa'
            ),
        ]

    def __str__():
        return f"Saldo de {self.distribuidor.username}: ${self.cantidad}"

    def clean(self):
        """
        Validaciones personalizadas para el saldo.
        """
        if self.distribuidor.rol != 'distribuidor':
            logger.error(f"Usuario {self.distribuidor.username} no es distribuidor")
            raise ValidationError(_("El usuario asociado debe tener el rol de distribuidor."))
        if self.cantidad < 0:
            logger.error(f"Saldo negativo detectado: {self.cantidad}")
            raise ValidationError(_("El saldo no puede ser negativo."))