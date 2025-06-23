"""
Modelos de datos para el módulo de Wallet en MexaRed.
Arquitectura blindada para precisión financiera, escalabilidad multinivel,
auditoría bancaria, y cumplimiento de estándares internacionales PCI DSS, SOC2.
Soporta transferencias jerárquicas (Admin → Distribuidor → Vendedor → Cliente),
conciliación bancaria, y trazabilidad completa.
"""

import uuid
from decimal import Decimal
from django.db import models, transaction
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.conf import settings
from apps.users.models import ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR, ROLE_CLIENTE
from apps.wallet.enums import TipoMovimiento

# Referencia al modelo de usuario personalizado
User = get_user_model()

# Límites financieros (puedes mover a settings.py en producción)
MIN_AMOUNT = Decimal('0.01')
MAX_AMOUNT = Decimal('50000.00')

class Wallet(models.Model):
    """
    Modelo central de billetera para usuarios (Admin, Distribuidor, Vendedor).
    Gestiona saldo disponible, saldo bloqueado, y jerarquía financiera.
    Preparado para conciliaciones bancarias y cumplimiento normativo.

    Attributes:
        user: Usuario asociado a la billetera (único).
        balance: Saldo disponible para operaciones financieras.
        blocked_balance: Fondos retenidos (disputas, auditorías, fraudes).
        hierarchy_root: Admin o Distribuidor padre en la jerarquía.
        last_updated: Fecha y hora de la última modificación.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='wallet',
        verbose_name=_("Usuario"),
        help_text=_("Usuario asociado a esta billetera (único).")
    )
    balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name=_("Saldo disponible"),
        help_text=_("Saldo disponible para operaciones financieras.")
    )
    blocked_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name=_("Saldo bloqueado"),
        help_text=_("Fondos retenidos por disputas, auditorías o prevención de fraudes.")
    )
    hierarchy_root = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sub_wallets',
        verbose_name=_("Jerarquía raíz"),
        help_text=_("El administrador o distribuidor padre en la jerarquía."),
        null=True,
        blank=True
    )
    last_updated = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Última actualización"),
        help_text=_("Fecha y hora de la última modificación del saldo.")
    )

    class Meta:
        verbose_name = _("Billetera")
        verbose_name_plural = _("Billeteras")
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['hierarchy_root']),
            models.Index(fields=['balance']),
            models.Index(fields=['blocked_balance']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(balance__gte=0),
                name='non_negative_balance',
                violation_error_message=_("El saldo disponible no puede ser negativo.")
            ),
            models.CheckConstraint(
                check=models.Q(blocked_balance__gte=0),
                name='non_negative_blocked_balance',
                violation_error_message=_("El saldo bloqueado no puede ser negativo.")
            ),
        ]

    def __str__(self):
        return f"Wallet [{self.user.username}] ({self.user.rol}) - Balance: {self.balance} MXN"

    def clean(self):
        """
        Valida saldos, roles, y jerarquía antes de guardar.

        Raises:
            ValidationError: Si los saldos son negativos, el rol es inválido, o la jerarquía no es válida.
        """
        if self.balance < Decimal('0.00'):
            raise ValidationError(_("El saldo disponible no puede ser negativo."), code='negative_balance')
        if self.blocked_balance < Decimal('0.00'):
            raise ValidationError(_("El saldo bloqueado no puede ser negativo."), code='negative_blocked_balance')
        if self.user.rol not in [ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR]:
            raise ValidationError(
                _("Solo los roles Admin, Distribuidor o Vendedor pueden tener una billetera."),
                code='invalid_role'
            )
        self.validate_hierarchy()

    def validate_hierarchy(self):
        """
        Valida la jerarquía de la billetera según el rol del usuario.

        Raises:
            ValidationError: Si la jerarquía es inválida.
        """
        if self.user.rol == ROLE_ADMIN and self.hierarchy_root:
            raise ValidationError(
                _("Un Admin no puede tener un hierarchy_root."),
                code='invalid_hierarchy_admin'
            )
        if self.user.rol in [ROLE_DISTRIBUIDOR, ROLE_VENDEDOR] and not self.hierarchy_root:
            raise ValidationError(
                _("Los Distribuidores y Vendedores deben tener un hierarchy_root."),
                code='missing_hierarchy'
            )
        if self.hierarchy_root:
            if self.hierarchy_root.rol not in [ROLE_ADMIN, ROLE_DISTRIBUIDOR]:
                raise ValidationError(
                    _("El hierarchy_root debe ser un Admin o Distribuidor."),
                    code='invalid_hierarchy_root'
                )
            if self.user == self.hierarchy_root:
                raise ValidationError(
                    _("Un usuario no puede ser su propio hierarchy_root."),
                    code='self_hierarchy'
                )
            # Ensure hierarchical consistency
            if self.user.rol == ROLE_DISTRIBUIDOR and self.hierarchy_root.rol != ROLE_ADMIN:
                raise ValidationError(
                    _("Un Distribuidor debe tener un Admin como hierarchy_root."),
                    code='invalid_distributor_hierarchy'
                )
            if self.user.rol == ROLE_VENDEDOR and self.hierarchy_root.rol != ROLE_DISTRIBUIDOR:
                raise ValidationError(
                    _("Un Vendedor debe tener un Distribuidor como hierarchy_root."),
                    code='invalid_seller_hierarchy'
                )

    def save(self, *args, **kwargs):
        """
        Guarda la billetera con atomicidad y registra auditoría.

        Args:
            *args, **kwargs: Argumentos para el método save.

        Raises:
            ValidationError: Si las validaciones fallan.
        """
        from apps.users.models import UserChangeLog  # Avoid circular import

        with transaction.atomic():
            self.full_clean()
            is_new = self.pk is None
            changes = {}

            if not is_new:
                old_instance = Wallet.objects.select_for_update().get(pk=self.pk)
                fields_to_track = ['balance', 'blocked_balance', 'hierarchy_root']
                for field in fields_to_track:
                    old_value = getattr(old_instance, field)
                    new_value = getattr(self, field)
                    if old_value != new_value:
                        changes[field] = {
                            "before": str(old_value.id if field == 'hierarchy_root' and old_value else old_value),
                            "after": str(new_value.id if field == 'hierarchy_root' and new_value else new_value)
                        }

            super().save(*args, **kwargs)

            if is_new:
                UserChangeLog.objects.create(
                    user=self.user,
                    change_type='create',
                    change_description="Creación de billetera",
                    details={
                        "balance": str(self.balance),
                        "blocked_balance": str(self.blocked_balance),
                        "hierarchy_root": str(self.hierarchy_root.id if self.hierarchy_root else None)
                    }
                )
            elif changes:
                UserChangeLog.objects.create(
                    user=self.user,
                    change_type='update',
                    change_description="Actualización de billetera",
                    details=changes
                )

    def validate_sufficient_balance(self, amount: Decimal, operation: str = 'debit'):
        """
        Verifica saldo suficiente para operaciones de débito o bloqueo.

        Args:
            amount: Monto a validar.
            operation: Tipo de operación ('debit' o 'block').

        Raises:
            ValidationError: Si el saldo es insuficiente.
        """
        with transaction.atomic():
            wallet = Wallet.objects.select_for_update().get(pk=self.pk)
            if operation == 'debit' and wallet.balance < amount:
                raise ValidationError(
                    _("Saldo insuficiente: %(disponible)s MXN disponible, se requieren %(requerido)s MXN"),
                    params={'disponible': wallet.balance, 'requerido': amount},
                    code='insufficient_balance'
                )
            if operation == 'block' and wallet.balance < amount:
                raise ValidationError(
                    _("Saldo insuficiente para bloquear: %(disponible)s MXN disponible, se requieren %(requerido)s MXN"),
                    params={'disponible': wallet.balance, 'requerido': amount},
                    code='insufficient_balance_block'
                )

class WalletMovement(models.Model):
    """
    Modelo de movimientos financieros para billeteras.
    Registra créditos, débitos, transferencias, bloqueos y desbloqueos con auditoría completa.
    Soporta transferencias jerárquicas y referencias externas (e.g., Addinteli).

    Attributes:
        id: Identificador único (UUID).
        wallet: Billetera asociada.
        tipo: Tipo de movimiento (de TipoMovimiento).
        monto: Monto del movimiento.
        referencia: Referencia externa (e.g., MercadoPago, Addinteli).
        operacion_id: ID único de operación.
        fecha: Fecha y hora del movimiento.
        creado_por: Usuario que ejecutó la operación.
        conciliado: Estado de conciliación.
        fecha_conciliacion: Fecha de conciliación.
        actor_ip: IP de origen.
        device_info: Información del dispositivo.
        origen_wallet: Billetera origen para transferencias.
    """
    MIN_AMOUNT = Decimal('0.01')
    MAX_AMOUNT = Decimal('50000.00')

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("ID de movimiento"),
        help_text=_("Identificador único del movimiento.")
    )
    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.CASCADE,
        related_name='movements',
        verbose_name=_("Usuario destino"),
        help_text=_("Billetera asociada al movimiento.")
    )
    tipo = models.CharField(
        max_length=50,
        choices=TipoMovimiento.choices(),
        verbose_name=_("Tipo de movimiento"),
        help_text=_("Tipo de movimiento (crédito, débito, transferencia, etc.).")
    )
    monto = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[
            MinValueValidator(MIN_AMOUNT, message=_("El monto debe ser al menos %(limit_value)s MXN.")),
            MaxValueValidator(MAX_AMOUNT, message=_("El monto no puede exceder %(limit_value)s MXN."))
        ],
        verbose_name=_("Monto"),
        help_text=_("Monto del movimiento financiero.")
    )
    referencia = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("Referencia"),
        help_text=_("Referencia externa, e.g., ID de transacción MercadoPago o API Addinteli.")
    )
    operacion_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("ID de operación"),
        help_text=_("Identificador único de la operación para trazabilidad.")
    )
    fecha = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Fecha"),
        help_text=_("Fecha y hora del movimiento.")
    )
    creado_por = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='movimientos_creados',
        verbose_name=_("Creado por"),
        help_text=_("Usuario que ejecutó la operación.")
    )
    conciliado = models.BooleanField(
        default=False,
        verbose_name=_("Conciliado"),
        help_text=_("Indica si el movimiento ha sido conciliado con registros financieros.")
    )
    fecha_conciliacion = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Fecha de conciliación"),
        help_text=_("Fecha en que el movimiento fue conciliado.")
    )
    actor_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name=_("IP de origen"),
        help_text=_("Dirección IP desde donde se realizó la operación.")
    )
    device_info = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        validators=[
            RegexValidator(
                regex=r'^[\w\s\-\(\):;,.\/\\@#&+=]*$',
                message=_("Información del dispositivo contiene caracteres inválidos.")
            )
        ],
        verbose_name=_("Información del dispositivo"),
        help_text=_("Detalles del dispositivo usado (e.g., User-Agent).")
    )
    origen_wallet = models.ForeignKey(
        Wallet,
        on_delete=models.SET_NULL,
        related_name='movimientos_emitidos',
        null=True,
        blank=True,
        verbose_name=_("Usuario origen"),
        help_text=_("Billetera origen para transferencias.")
    )

    class Meta:
        verbose_name = _("Movimiento de billetera")
        verbose_name_plural = _("Movimientos de billetera")
        ordering = ['-fecha']
        indexes = [
            models.Index(fields=['wallet', 'fecha']),
            models.Index(fields=['tipo']),
            models.Index(fields=['operacion_id']),
            models.Index(fields=['conciliado']),
            models.Index(fields=['monto']),
            models.Index(fields=['fecha_conciliacion']),
            models.Index(fields=['creado_por']),
            models.Index(fields=['origen_wallet']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(monto__gte=Decimal('0.01')) & models.Q(monto__lte=Decimal('50000.00')),
                name='valid_monto_range',
                violation_error_message=_("El monto debe estar entre 0.01 y 50000.00 MXN.")
            ),
        ]

    def __str__(self):
        return f"{self.tipo} - {self.monto} MXN [{self.fecha}]"

    def clean(self):
        """
        Valida el movimiento antes de guardar, asegurando consistencia financiera y jerárquica.

        Raises:
            ValidationError: Si el monto, tipo, conciliación o jerarquía son inválidos.
        """
        if self.monto < self.MIN_AMOUNT or self.monto > self.MAX_AMOUNT:
            raise ValidationError(
                _("El monto debe estar entre %(min)s y %(max)s MXN.") % {
                    'min': self.MIN_AMOUNT, 'max': self.MAX_AMOUNT
                },
                code='invalid_monto_range'
            )
        if self.tipo not in TipoMovimiento.values():
            raise ValidationError(
                _("Tipo de movimiento inválido: %(tipo)s.") % {'tipo': self.tipo},
                code='invalid_tipo'
            )
        if self.conciliado and not self.fecha_conciliacion:
            raise ValidationError(
                _("Un movimiento conciliado debe tener una fecha de conciliación."),
                code='missing_conciliation_date'
            )
        if not self.conciliado and self.fecha_conciliacion:
            raise ValidationError(
                _("No se puede establecer fecha de conciliación sin marcar como conciliado."),
                code='invalid_conciliation_date'
            )
        if self.tipo in ['DEBITO', 'TRANSFERENCIA_INTERNA', 'BLOQUEO']:
            operation = 'debit' if self.tipo in ['DEBITO', 'TRANSFERENCIA_INTERNA'] else 'block'
            self.wallet.validate_sufficient_balance(self.monto, operation)
        if self.tipo == 'TRANSFERENCIA_INTERNA':
            self.validate_transfer_hierarchy()

    def validate_transfer_hierarchy(self):
        """
        Valida la jerarquía para transferencias internas.

        Raises:
            ValidationError: Si la transferencia viola la jerarquía o roles.
        """
        if not self.origen_wallet:
            raise ValidationError(
                _("Las transferencias internas requieren una billetera origen."),
                code='missing_origen_wallet'
            )
        if self.origen_wallet == self.wallet:
            raise ValidationError(
                _("No se puede transferir a la misma billetera."),
                code='self_transfer'
            )
        if self.origen_wallet.hierarchy_root != self.wallet.hierarchy_root:
            raise ValidationError(
                _("Las transferencias solo son permitidas dentro de la misma jerarquía."),
                code='invalid_hierarchy_transfer'
            )
        allowed_transfers = {
            ROLE_ADMIN: [ROLE_DISTRIBUIDOR, ROLE_VENDEDOR],
            ROLE_DISTRIBUIDOR: [ROLE_VENDEDOR, ROLE_CLIENTE],
            ROLE_VENDEDOR: [ROLE_CLIENTE],
            ROLE_CLIENTE: []
        }
        origen_role = self.origen_wallet.user.rol
        destino_role = self.wallet.user.rol
        if destino_role not in allowed_transfers.get(origen_role, []):
            raise ValidationError(
                _("Transferencia no permitida de %(origen)s a %(destino)s.") % {
                    'origen': origen_role, 'destino': destino_role
                },
                code='invalid_role_transfer'
            )

class Moneda(models.Model):
    """
    Modelo de Moneda para el módulo Wallet.
    """
    codigo = models.CharField(max_length=10, unique=True, default="MXN")
    nombre = models.CharField(max_length=100, default="Peso Mexicano")
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Moneda"
        verbose_name_plural = "Monedas"
        ordering = ["codigo"]

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"