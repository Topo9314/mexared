"""
Modelos para la gestión de activaciones en MexaRed.
Soporta activaciones de líneas nuevas, portabilidades y productos específicos (MiFi, eSIM, IoT).
Integrado con la API de Addinteli v8.0, jerarquías de usuario, auditoría y control financiero.
Optimizado para escalabilidad internacional, seguridad, rendimiento y cumplimiento normativo (PCI DSS, SOC2, ISO 27001).
"""

import uuid
import logging
import hashlib
import json
from decimal import Decimal
from datetime import timedelta
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import RegexValidator, MinValueValidator
from django.utils import timezone
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import JSONField
from apps.users.models import User, ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR
from apps.ofertas.models import Oferta
from django.core.exceptions import ObjectDoesNotExist

# Configuración de logging para auditoría
logger = logging.getLogger(__name__)

# Constantes y Choices
PRODUCTOS = [
    ("SIM", _("SIM Card")),
    ("MIFI", _("Dispositivo MiFi")),
    ("ESIM", _("eSIM")),
    ("HBB", _("Internet en el Hogar")),
    ("IOT", _("IoT")),
]

TIPOS_ACTIVACION = [
    ("nueva", _("Nueva Línea")),
    ("portabilidad", _("Portabilidad")),
    ("especifica", _("Producto Específico")),
]

ESTADOS = [
    ("pendiente", _("Pendiente")),
    ("en_proceso", _("En Proceso")),
    ("exitosa", _("Exitosa")),
    ("fallida", _("Fallida")),
    ("revertida", _("Revertida")),
]

ORIGENES = [
    ("admin_panel", _("Panel de Administración")),
    ("web_distribuidor", _("Portal Distribuidor")),
    ("web_vendedor", _("Portal Vendedor")),
    ("api", _("API Externa")),
    ("addinteli_webhook", _("Webhook Addinteli")),
]

MODO_PAGO = [
    ("online", _("Pago en Línea")),
    ("manual", _("Pago Manual")),
    ("no_aplica", _("Sin Pago (Distribuidor o Propia Cuenta)")),
]

TIPO_IDENTIFICACION = [
    ("INE", _("INE")),
    ("PASAPORTE", _("Pasaporte")),
    ("OTRO", _("Otro")),
]

ACCIONES_HISTORIAL = [
    ("create", _("Creación")),
    ("update", _("Actualización")),
    ("procesar_activacion", _("Procesamiento de Activación")),
    ("procesar_activacion_fallida", _("Fallo en Procesamiento")),
]

class Activacion(models.Model):
    """
    Modelo principal para gestionar solicitudes de activación de líneas.
    Soporta nuevas líneas, portabilidades y productos específicos, con auditoría y conciliación financiera.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("ID"),
        help_text=_("Identificador único de la activación.")
    )
    usuario_solicita = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='activaciones_solicitadas',
        verbose_name=_("Usuario Solicitante"),
        help_text=_("Usuario que realiza la activación (Admin, Distribuidor, Vendedor).")
    )
    distribuidor_asignado = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activaciones_asignadas',
        limit_choices_to={'rol': ROLE_DISTRIBUIDOR},
        verbose_name=_("Distribuidor Asignado"),
        help_text=_("Distribuidor al que se asigna la activación, si aplica.")
    )
    cliente_nombre = models.CharField(
        max_length=150,
        verbose_name=_("Nombre del Cliente"),
        help_text=_("Nombre completo del cliente final.")
    )
    cliente_email = models.EmailField(
        null=True,
        blank=True,
        verbose_name=_("Email del Cliente"),
        help_text=_("Correo electrónico del cliente final, opcional.")
    )
    telefono_contacto = models.CharField(
        max_length=20,
        validators=[
            RegexValidator(
                regex=r'^\+?\d{10,15}$',
                message=_("El número debe tener 10-15 dígitos, opcionalmente con +.")
            )
        ],
        verbose_name=_("Teléfono de Contacto"),
        help_text=_("Número de contacto del cliente.")
    )
    iccid = models.CharField(
        max_length=22,
        unique=True,
        db_index=True,
        validators=[
            RegexValidator(
                regex=r'^\d{19,22}$',
                message=_("El ICCID debe tener 19-22 dígitos.")
            )
        ],
        verbose_name=_("ICCID"),
        help_text=_("Identificador único de la SIM.")
    )
    proveedor = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name=_("Proveedor"),
        help_text=_("Proveedor de la SIM (e.g., Addinteli).")
    )
    tipo_producto = models.CharField(
        max_length=30,
        choices=PRODUCTOS,
        verbose_name=_("Tipo de Producto"),
        help_text=_("Tipo de producto asociado (SIM, MiFi, eSIM, etc.).")
    )
    tipo_activacion = models.CharField(
        max_length=30,
        choices=TIPOS_ACTIVACION,
        verbose_name=_("Tipo de Activación"),
        help_text=_("Tipo de activación: nueva línea, portabilidad o producto específico.")
    )
    numero_asignado = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        db_index=True,
        validators=[
            RegexValidator(
                regex=r'^\+?\d{10,15}$',
                message=_("El número debe tener 10-15 dígitos, opcionalmente con +.")
            )
        ],
        verbose_name=_("Número Asignado"),
        help_text=_("Número telefónico asignado por Addinteli.")
    )
    estado = models.CharField(
        max_length=20,
        choices=ESTADOS,
        default="pendiente",
        verbose_name=_("Estado"),
        help_text=_("Estado actual de la activación.")
    )
    respuesta_addinteli = JSONField(
        null=True,
        blank=True,
        verbose_name=_("Respuesta de Addinteli"),
        help_text=_("Respuesta cruda de la API de Addinteli para auditoría.")
    )
    precio_costo = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name=_("Precio Costo"),
        help_text=_("Costo base para el usuario que realiza la activación.")
    )
    precio_final = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name=_("Precio Final"),
        help_text=_("Precio de venta al cliente final.")
    )
    oferta = models.ForeignKey(
        Oferta,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activaciones',
        verbose_name=_("Oferta Aplicada"),
        help_text=_("Oferta de Addinteli usada en esta activación.")
    )
    codigo_addinteli = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Código Addinteli"),
        help_text=_("Código de activación generado por Addinteli.")
    )
    modo_pago_cliente = models.CharField(
        max_length=20,
        choices=MODO_PAGO,
        default="no_aplica",
        verbose_name=_("Modo de Pago del Cliente"),
        help_text=_("Método con el que el cliente pagó la activación.")
    )
    addinteli_response_code = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name=_("Código de Respuesta Addinteli"),
        help_text=_("Código de respuesta de la API de Addinteli.")
    )
    mensaje_addinteli = models.TextField(
        null=True,
        blank=True,
        verbose_name=_("Mensaje Addinteli"),
        help_text=_("Mensaje devuelto por la API de Addinteli.")
    )
    ip_solicitud = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name=_("IP de Solicitud"),
        help_text=_("Dirección IP desde donde se generó la activación.")
    )
    pais_origen = models.CharField(
        max_length=3,
        null=True,
        blank=True,
        validators=[
            RegexValidator(
                regex=r'^[A-Z]{3}$',
                message=_("El código de país debe ser un código ISO 3166-1 alpha-3 válido.")
            )
        ],
        verbose_name=_("País de Origen"),
        help_text=_("Código ISO 3166-1 alpha-3 del país de origen.")
    )
    pais_destino = models.CharField(
        max_length=3,
        null=True,
        blank=True,
        validators=[
            RegexValidator(
                regex=r'^[A-Z]{3}$',
                message=_("El código de país debe ser un código ISO 3166-1 alpha-3 válido.")
            )
        ],
        verbose_name=_("País de Destino"),
        help_text=_("Código ISO 3166-1 alpha-3 del país de destino.")
    )
    lote_id = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Lote ID"),
        help_text=_("Identificador de lote si esta activación es parte de una operación masiva.")
    )
    fecha_solicitud = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Fecha de Solicitud"),
        help_text=_("Fecha y hora en que se creó la solicitud.")
    )
    fecha_activacion = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Fecha de Activación"),
        help_text=_("Fecha y hora en que se completó la activación.")
    )

    class Meta:
        verbose_name = _("Activación")
        verbose_name_plural = _("Activaciones")
        indexes = [
            models.Index(fields=['iccid'], name='idx_activacion_iccid'),
            models.Index(fields=['estado'], name='idx_activacion_estado'),
            models.Index(fields=['usuario_solicita', 'fecha_solicitud'], name='idx_activacion_usuario_fecha'),
            models.Index(fields=['distribuidor_asignado'], name='idx_activacion_distribuidor'),
            models.Index(fields=['codigo_addinteli'], name='idx_act_codigo_add'),
            models.Index(fields=['lote_id'], name='idx_activacion_lote_id'),
        ]
        constraints = [
            models.UniqueConstraint(fields=['iccid'], name='unique_iccid'),
            models.CheckConstraint(
                check=models.Q(precio_costo__gte=0),
                name='activacion_non_negative_costo',
                violation_error_message=_("El precio costo no puede ser negativo.")
            ),
            models.CheckConstraint(
                check=models.Q(precio_final__gte=0),
                name='activacion_non_negative_final',
                violation_error_message=_("El precio final no puede ser negativo.")
            ),
        ]

    def __str__(self):
        return f"Activación {self.iccid} - {self.get_estado_display()}"

    @property
    def ganancia(self) -> Decimal:
        """
        Calcula la ganancia como precio_final - precio_costo.
        Returns:
            Decimal: Ganancia calculada.
        """
        return self.precio_final - self.precio_costo if self.precio_final and self.precio_costo else Decimal('0.00')

    def calcular_ganancia(self) -> Decimal:
        """
        Método reutilizable para calcular la ganancia, usado por tareas o servicios.
        Returns:
            Decimal: Ganancia calculada.
        """
        ganancia = self.ganancia
        if ganancia == 0:
            logger.warning(
                f"Activación ID={self.id or 'new'}: ganancia es 0 (precio_final={self.precio_final}, precio_costo={self.precio_costo})"
            )
        return ganancia

    def validar_iccid_con_api(self) -> dict:
        """
        Valida el ICCID contra la API de Addinteli.
        Returns:
            dict: Respuesta de la API.
        Raises:
            ValidationError: Si el ICCID no es válido o falla la validación.
        """
        from .services import ActivacionService
        try:
            service = ActivacionService()
            response = service.validar_iccid_con_addinteli(self.iccid)
            if not response.get('result', {}).get('valid', False):
                raise ValidationError(
                    _("El ICCID no es válido o no pertenece a MexaRed."),
                    code='invalid_iccid'
                )
            return response
        except Exception as e:
            logger.error(f"Error validando ICCID {self.iccid} con Addinteli: {str(e)}", exc_info=True)
            raise ValidationError(_("Error validando ICCID con Addinteli: ") + str(e))

    def clean(self):
        """
        Validaciones personalizadas antes de guardar.
        Raises:
            ValidationError: Si alguna validación falla.
        """
        super().clean()
        # Validar roles del usuario solicitante
        if self.usuario_solicita and self.usuario_solicita.rol not in [ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR]:
            raise ValidationError(
                _("El usuario solicitante debe ser Admin, Distribuidor o Vendedor."),
                code='invalid_role_solicitante'
            )
        # Validar distribuidor asignado
        if self.distribuidor_asignado and self.distribuidor_asignado.rol != ROLE_DISTRIBUIDOR:
            raise ValidationError(
                _("El distribuidor asignado debe tener rol Distribuidor."),
                code='invalid_role_distribuidor'
            )
        # Validar tipo de producto para portabilidad
        if self.tipo_activacion == 'portabilidad' and self.tipo_producto not in ['SIM', 'ESIM']:
            raise ValidationError(
                _("Las portabilidades solo son válidas para SIM o eSIM."),
                code='invalid_product_portability'
            )
        # Validar ICCID duplicado en activaciones activas
        if self.iccid and Activacion.objects.filter(
            iccid=self.iccid
        ).exclude(id=self.id).filter(estado__in=['en_proceso', 'exitosa']).exists():
            raise ValidationError(
                _("Ya existe una activación en proceso o exitosa con este ICCID."),
                code='duplicate_iccid_active'
            )
        # Validar ICCID obligatorio para SIM/ESIM
        if self.tipo_producto in ['SIM', 'ESIM'] and not self.iccid:
            raise ValidationError(
                _("El ICCID es obligatorio para productos SIM o eSIM."),
                code='missing_iccid'
            )
        # Validar precios
        if self.precio_final < self.precio_costo:
            raise ValidationError(
                _("El precio final no puede ser menor que el precio costo."),
                code='invalid_precio_final'
            )
        # Validar códigos de país
        if self.pais_origen and not self.pais_origen.isupper():
            raise ValidationError(
                _("El código de país de origen debe estar en mayúsculas."),
                code='invalid_pais_origen'
            )
        if self.pais_destino and not self.pais_destino.isupper():
            raise ValidationError(
                _("El código de país de destino debe estar en mayúsculas."),
                code='invalid_pais_destino'
            )

    def save(self, *args, **kwargs):
        """
        Sobrescribe save para validaciones y auditoría.
        """
        from django.db import transaction
        with transaction.atomic():
            self.full_clean()
            is_new = self.pk is None
            changes = {}

            if not is_new:
                try:
                    old_instance = Activacion.objects.get(pk=self.pk)
                    fields_to_track = [
                        'estado', 'numero_asignado', 'precio_costo', 'precio_final',
                        'tipo_activacion', 'tipo_producto', 'codigo_addinteli', 'modo_pago_cliente'
                    ]
                    for field in fields_to_track:
                        old_value = getattr(old_instance, field)
                        new_value = getattr(self, field)
                        if old_value != new_value:
                            changes[field] = {"before": str(old_value), "after": str(new_value)}
                except ObjectDoesNotExist:
                    logger.warning(f"No se encontró instancia previa para activación ID={self.id}")

            super().save(*args, **kwargs)

            # Registrar en historial
            HistorialActivacion.objects.create(
                activacion=self,
                accion='create' if is_new else 'update',
                mensaje=_("Activación creada") if is_new else _("Activación actualizada: ") + ', '.join(changes.keys()),
                usuario=self.usuario_solicita,
                details=changes if not is_new else {}
            )

class PortabilidadDetalle(models.Model):
    """
    Detalles específicos para activaciones de tipo portabilidad.
    """
    activacion = models.OneToOneField(
        Activacion,
        on_delete=models.CASCADE,
        related_name='portabilidad_detalle',
        verbose_name=_("Activación"),
        help_text=_("Activación asociada a esta portabilidad.")
    )
    numero_actual = models.CharField(
        max_length=20,
        validators=[
            RegexValidator(
                regex=r'^\+?\d{10,15}$',
                message=_("El número debe tener 10-15 dígitos, opcionalmente con +.")
            )
        ],
        verbose_name=_("Número Actual"),
        help_text=_("Número telefónico que será portado.")
    )
    compañia_origen = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name=_("Compañía Origen"),
        help_text=_("Nombre del operador actual del número, opcional.")
    )
    nip_portabilidad = models.CharField(
        max_length=10,
        validators=[
            RegexValidator(
                regex=r'^\d{4}$',
                message=_("El NIP debe ser un código de 4 dígitos.")
            )
        ],
        verbose_name=_("NIP de Portabilidad"),
        help_text=_("Código NIP para validar la portabilidad.")
    )
    curp = models.CharField(
        max_length=18,
        null=True,
        blank=True,
        validators=[
            RegexValidator(
                regex=r'^[A-Z]{4}\d{6}[A-Z]{6}[A-Z0-9]{2}$',
                message=_("El CURP debe tener un formato válido.")
            )
        ],
        verbose_name=_("CURP"),
        help_text=_("CURP del titular, si aplica por regulación.")
    )
    fecha_nacimiento = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Fecha de Nacimiento"),
        help_text=_("Fecha de nacimiento del titular, opcional según regulación.")
    )
    tipo_identificacion = models.CharField(
        max_length=20,
        choices=TIPO_IDENTIFICACION,
        null=True,
        blank=True,
        verbose_name=_("Tipo de Identificación"),
        help_text=_("Tipo de documento de identificación proporcionado.")
    )
    identificacion_url = models.URLField(
        null=True,
        blank=True,
        verbose_name=_("URL de Identificación"),
        help_text=_("Enlace al documento de identificación cargado (INE, contrato, etc.).")
    )

    class Meta:
        verbose_name = _("Detalle de Portabilidad")
        verbose_name_plural = _("Detalles de Portabilidad")
        indexes = [
            models.Index(fields=['numero_actual'], name='idx_portabilidad_numero'),
        ]

    def __str__(self):
        return f"Portabilidad para {self.numero_actual}"

    def clean(self):
        """
        Validaciones personalizadas para portabilidad.
        """
        super().clean()
        if self.activacion and self.activacion.tipo_activacion != 'portabilidad':
            raise ValidationError(
                _("El detalle de portabilidad solo aplica a activaciones de tipo portabilidad."),
                code='invalid_activacion_type'
            )
        # Auto-archivar portabilidad no completada después de 7 días
        if self.activacion and self.activacion.estado != 'exitosa' and self.activacion.fecha_solicitud:
            if timezone.now() - self.activacion.fecha_solicitud > timedelta(days=7):
                logger.warning(
                    f"Portabilidad para activación {self.activacion.id} no completada tras 7 días."
                )
                # Consider implementing archival logic in a separate task

class HistorialActivacion(models.Model):
    """
    Registro de eventos y auditoría para cada activación.
    """
    activacion = models.ForeignKey(
        Activacion,
        on_delete=models.CASCADE,
        related_name='historial',
        verbose_name=_("Activación"),
        help_text=_("Activación asociada al evento.")
    )
    accion = models.CharField(
        max_length=100,
        choices=ACCIONES_HISTORIAL,
        verbose_name=_("Acción"),
        help_text=_("Acción ejecutada: creación, actualización, procesamiento, etc.")
    )
    mensaje = models.TextField(
        verbose_name=_("Mensaje"),
        help_text=_("Descripción del evento o error.")
    )
    usuario = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='historial_activaciones',
        verbose_name=_("Usuario"),
        help_text=_("Usuario que generó el evento.")
    )
    details = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Detalles"),
        help_text=_("Detalles adicionales en formato JSON.")
    )
    ip_origen = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name=_("IP de Origen"),
        help_text=_("Dirección IP desde donde se generó el evento.")
    )
    fecha = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Fecha"),
        help_text=_("Fecha y hora del evento.")
    )

    class Meta:
        verbose_name = _("Historial de Activación")
        verbose_name_plural = _("Historial de Activaciones")
        indexes = [
            models.Index(fields=['activacion', 'fecha'], name='idx_historial_fecha'),
            models.Index(fields=['accion'], name='idx_historial_accion'),
        ]
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.get_accion_display()} en {self.activacion.iccid} ({self.fecha})"

class ActivacionErrorLog(models.Model):
    """
    Registro de errores críticos relacionados con activaciones.
    """
    iccid = models.CharField(
        max_length=22,
        validators=[
            RegexValidator(
                regex=r'^\d{19,22}$',
                message=_("El ICCID debe tener 19-22 dígitos.")
            )
        ],
        verbose_name=_("ICCID"),
        help_text=_("ICCID asociado al error.")
    )
    error_tipo = models.CharField(
        max_length=50,
        verbose_name=_("Tipo de Error"),
        help_text=_("Tipo de error: conexión API, JSON inválido, etc.")
    )
    codigo_error_addinteli = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name=_("Código de Error Addinteli"),
        help_text=_("Código de error devuelto por la API de Addinteli.")
    )
    detalle = models.TextField(
        verbose_name=_("Detalle"),
        help_text=_("Descripción detallada del error o traceback.")
    )
    activacion = models.ForeignKey(
        Activacion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='errores',
        verbose_name=_("Activación"),
        help_text=_("Activación asociada, si aplica.")
    )
    origin_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name=_("IP de Origen"),
        help_text=_("Dirección IP desde donde se originó el error.")
    )
    user_agent = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("User Agent"),
        help_text=_("Información del agente de usuario que generó el error.")
    )
    fecha = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Fecha"),
        help_text=_("Fecha y hora del error.")
    )

    class Meta:
        verbose_name = _("Log de Error de Activación")
        verbose_name_plural = _("Logs de Errores de Activación")
        indexes = [
            models.Index(fields=['iccid', 'fecha'], name='idx_errorlog_iccid_fecha'),
            models.Index(fields=['error_tipo'], name='idx_errorlog_tipo'),
            models.Index(fields=['codigo_error_addinteli'], name='idx_errorlog_codigo_add'),
        ]
        ordering = ['-fecha']

    def __str__(self):
        return f"Error {self.error_tipo} para ICCID {self.iccid} ({self.fecha})"

class AuditLog(models.Model):
    """
    Registro de auditoría para acciones críticas en el módulo de activaciones.
    Almacena información detallada para trazabilidad y cumplimiento regulatorio.
    """
    usuario = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        verbose_name=_("Usuario"),
        help_text=_("Usuario que realizó la acción.")
    )
    accion = models.CharField(
        max_length=255,
        verbose_name=_("Acción"),
        help_text=_("Descripción de la acción realizada.")
    )
    entidad = models.CharField(
        max_length=255,
        verbose_name=_("Entidad"),
        help_text=_("Entidad afectada (e.g., Activacion, User).")
    )
    entidad_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("ID de Entidad"),
        help_text=_("Identificador de la entidad afectada.")
    )
    detalles = JSONField(
        null=True,
        blank=True,
        verbose_name=_("Detalles"),
        help_text=_("Detalles adicionales en formato JSON.")
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name=_("Dirección IP"),
        help_text=_("Dirección IP del cliente que realizó la acción.")
    )
    origen_api = models.BooleanField(
        default=False,
        verbose_name=_("Origen API"),
        help_text=_("Indica si la acción proviene de una API externa.")
    )
    integridad_verificada = models.BooleanField(
        default=False,
        verbose_name=_("Integridad Verificada"),
        help_text=_("Indica si el hash de auditoría ha sido verificado.")
    )
    fecha = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Fecha"),
        help_text=_("Fecha y hora del evento.")
    )
    audit_hash_stored = models.CharField(
        max_length=64,
        editable=False,
        blank=True,
        null=True,
        verbose_name=_("Hash de Auditoría Almacenado"),
        help_text=_("Hash SHA256 almacenado para verificar integridad del registro.")
    )

    class Meta:
        verbose_name = _("Registro de Auditoría")
        verbose_name_plural = _("Registros de Auditoría")
        ordering = ['-fecha']
        indexes = [
            models.Index(fields=['usuario', 'fecha'], name='idx_auditlog_usuario_fecha'),
            models.Index(fields=['accion'], name='idx_auditlog_accion'),
            models.Index(fields=['entidad', 'entidad_id'], name='idx_auditlog_entidad'),
            models.Index(fields=['origen_api'], name='idx_auditlog_origen_api'),
        ]

    def __str__(self):
        return f"{self.accion} por {self.usuario or 'Anónimo'} en {self.fecha}"

    @property
    def audit_hash(self) -> str:
        """
        Genera un hash SHA256 dinámico para validar la integridad del registro.
        Combina entidad, entidad_id, usuario_id, fecha, detalles y origen_api.
        Returns:
            str: Hash SHA256 generado.
        """
        fecha_str = self.fecha.isoformat() if self.fecha else timezone.now().isoformat()
        base_string = (
            f"{self.entidad}-"
            f"{self.entidad_id or ''}-"
            f"{self.usuario_id or ''}-"
            f"{fecha_str}-"
            f"{json.dumps(self.detalles or {}, sort_keys=True, ensure_ascii=False)}-"
            f"{self.origen_api}"
        )
        return hashlib.sha256(base_string.encode('utf-8')).hexdigest()

    def save(self, *args, **kwargs):
        """
        Sobrescribe save para generar y almacenar el hash de auditoría.
        """
        from django.db import transaction
        with transaction.atomic():
            if not self.fecha:
                self.fecha = timezone.now()
                logger.debug(f"AuditLog ID={self.id or 'new'}: fecha was None, set to {self.fecha}")
            self.audit_hash_stored = self.audit_hash
            super().save(*args, **kwargs)
            logger.debug(
                f"AuditLog guardado: ID={self.id}, Acción={self.accion}, Hash={self.audit_hash_stored}"
            )

    def clean(self):
        """
        Validaciones personalizadas antes de guardar.
        """
        super().clean()
        if not self.accion:
            raise ValidationError(
                _("El campo acción es obligatorio."),
                code='missing_action'
            )
        if not self.entidad:
            raise ValidationError(
                _("El campo entidad es obligatorio."),
                code='missing_entity'
            )

class APIWebhookLog(models.Model):
    """
    Registro de eventos recibidos a través de webhooks de la API de Addinteli.
    Soporta trazabilidad y auditoría de operaciones externas.
    """
    evento = models.CharField(
        max_length=100,
        verbose_name=_("Evento"),
        help_text=_("Nombre del evento recibido (e.g., activacion_completada).")
    )
    payload = JSONField(
        verbose_name=_("Payload"),
        help_text=_("Datos recibidos en el webhook.")
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ("pendiente", _("Pendiente")),
            ("procesado", _("Procesado")),
            ("fallido", _("Fallido")),
        ],
        default="pendiente",
        verbose_name=_("Estado"),
        help_text=_("Estado del procesamiento del webhook.")
    )
    ip_origen = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name=_("IP de Origen"),
        help_text=_("Dirección IP desde donde se recibió el webhook.")
    )
    respuesta = JSONField(
        null=True,
        blank=True,
        verbose_name=_("Respuesta"),
        help_text=_("Respuesta enviada al webhook, si aplica.")
    )
    fecha = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Fecha"),
        help_text=_("Fecha y hora de recepción del webhook.")
    )

    class Meta:
        verbose_name = _("Log Webhook API")
        verbose_name_plural = _("Logs Webhook API")
        indexes = [
            models.Index(fields=['evento', 'fecha'], name='idx_webhooklog_evento_fecha'),
            models.Index(fields=['status'], name='idx_webhooklog_status'),
        ]
        ordering = ['-fecha']

    def __str__(self):
        return f"Webhook {self.evento} ({self.get_status_display()}) - {self.fecha}"
