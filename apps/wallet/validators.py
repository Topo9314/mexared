"""
Validaciones financieras centralizadas para el módulo Wallet de MexaRed.
Define reglas de negocio puro para operaciones financieras, asegurando integridad, antifraude y cumplimiento.
Consumido por services.py, forms.py y futuros servicios (API, batch jobs, conciliación).
Diseñado para entornos SaaS multinivel, compatible con PCI DSS Level 1, SOC2 Type 2, ISO 27001, y SAT.
"""

import logging
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from apps.users.models import User, ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR, ROLE_CLIENTE
from apps.wallet.models import Wallet, WalletMovement
from apps.wallet.enums import TipoMovimiento
from apps.wallet.exceptions import (
    SaldoInsuficienteException,
    MovimientoInvalidoException,
    LimiteExcedidoException,
    OperacionNoPermitidaException,
    ReferenciaExternaDuplicadaException,
    BloqueoFondosInvalidoException,
)
from apps.wallet.permissions import raise_if_not_allowed

# Configuración de logging para auditoría en producción
logger = logging.getLogger(__name__)

# Constantes de negocio financiero
MIN_AMOUNT = Decimal('0.01')
MAX_AMOUNT = Decimal('1000000.00')
LIMITE_BLOQUEO = Decimal('50000.00')
LIMITE_TRANSFERENCIA_DIARIA = Decimal('100000.00')

class WalletValidator:
    """
    Clase que centraliza las validaciones financieras para operaciones de Wallet.
    Asegura cumplimiento de reglas de negocio, límites antifraude y jerarquías multinivel.
    """

    @staticmethod
    def validar_monto(monto: Decimal) -> None:
        """
        Valida que el monto sea positivo y esté dentro de los límites permitidos.

        Args:
            monto: Monto a validar.

        Raises:
            MovimientoInvalidoException: Si el monto es inválido o fuera de rango.
        """
        if not isinstance(monto, Decimal):
            logger.warning(f"Monto inválido: {monto} (no es Decimal)")
            raise MovimientoInvalidoException(_("El monto debe ser un valor Decimal válido."))
        if monto < MIN_AMOUNT or monto > MAX_AMOUNT:
            logger.warning(f"Monto fuera de rango: {monto} (min: {MIN_AMOUNT}, max: {MAX_AMOUNT})")
            raise MovimientoInvalidoException(
                _("El monto debe estar entre %(min)s y %(max)s MXN.") % {
                    'min': MIN_AMOUNT, 'max': MAX_AMOUNT
                }
            )

    @staticmethod
    def validar_saldo(wallet: Wallet, monto: Decimal) -> None:
        """
        Valida que la billetera tenga saldo suficiente para una operación de débito.

        Args:
            wallet: Billetera a validar.
            monto: Monto requerido para la operación.

        Raises:
            SaldoInsuficienteException: Si el saldo disponible es insuficiente.
        """
        if wallet.balance < monto:
            logger.warning(
                f"Saldo insuficiente para wallet {wallet.id}: disponible {wallet.balance}, requerido {monto}"
            )
            raise SaldoInsuficienteException(
                _("Saldo insuficiente: %(disponible)s MXN disponible, se requieren %(requerido)s MXN.") % {
                    'disponible': wallet.balance, 'requerido': monto
                }
            )

    @staticmethod
    def validar_bloqueo(wallet: Wallet, monto: Decimal) -> None:
        """
        Valida que la billetera pueda bloquear o desbloquear el monto especificado.

        Args:
            wallet: Billetera a validar.
            monto: Monto a bloquear o desbloquear.

        Raises:
            MovimientoInvalidoException: Si el monto es inválido.
            SaldoInsuficienteException: Si el saldo es insuficiente para bloquear.
            BloqueoFondosInvalidoException: Si el saldo bloqueado es insuficiente para desbloquear.
            LimiteExcedidoException: Si el monto excede el límite de bloqueo.
        """
        WalletValidator.validar_monto(monto)
        if monto > LIMITE_BLOQUEO:
            logger.warning(f"Monto de bloqueo excede límite: {monto} > {LIMITE_BLOQUEO}")
            raise LimiteExcedidoException(
                _("El monto de bloqueo excede el límite permitido: %(limite)s MXN.") % {
                    'limite': LIMITE_BLOQUEO
                }
            )
        if wallet.balance < monto:
            logger.warning(
                f"Saldo insuficiente para bloqueo en wallet {wallet.id}: disponible {wallet.balance}, requerido {monto}"
            )
            raise SaldoInsuficienteException(
                _("Saldo insuficiente para bloquear: %(disponible)s MXN disponible, se requieren %(requerido)s MXN.") % {
                    'disponible': wallet.balance, 'requerido': monto
                }
            )
        if wallet.blocked_balance < monto:
            logger.warning(
                f"Saldo bloqueado insuficiente en wallet {wallet.id}: disponible {wallet.blocked_balance}, requerido {monto}"
            )
            raise BloqueoFondosInvalidoException(
                _("Saldo bloqueado insuficiente: %(disponible)s MXN, se requieren %(requerido)s MXN.") % {
                    'disponible': wallet.blocked_balance, 'requerido': monto
                }
            )

    @staticmethod
    def validar_limite_diario(wallet: Wallet, monto: Decimal, tipo: str) -> None:
        """
        Valida que la operación no exceda el límite diario por tipo de movimiento.

        Args:
            wallet: Billetera a validar.
            monto: Monto de la operación.
            tipo: Tipo de movimiento (e.g., TRANSFERENCIA_INTERNA).

        Raises:
            LimiteExcedidoException: Si excede el límite diario.
        """
        if tipo not in TipoMovimiento.values():
            logger.warning(f"Tipo de movimiento inválido: {tipo}")
            raise MovimientoInvalidoException(_("Tipo de movimiento inválido: %(tipo)s.") % {'tipo': tipo})

        movimientos_hoy = WalletMovement.objects.filter(
            wallet=wallet,
            tipo=tipo,
            fecha__date=timezone.now().date()
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

        if movimientos_hoy + monto > LIMITE_TRANSFERENCIA_DIARIA:
            logger.warning(
                f"Límite diario excedido para wallet {wallet.id}, tipo {tipo}: "
                f"actual {movimientos_hoy} + {monto} > {LIMITE_TRANSFERENCIA_DIARIA}"
            )
            raise LimiteExcedidoException(
                _("Límite diario de %(tipo)s excedido: %(limite)s MXN.") % {
                    'tipo': tipo, 'limite': LIMITE_TRANSFERENCIA_DIARIA
                }
            )

    @staticmethod
    def validar_jerarquia_transferencia(origen: User, destino: User) -> None:
        """
        Valida que la transferencia respete la jerarquía de roles (Admin → Distribuidor → Vendedor → Cliente).

        Args:
            origen: Usuario origen de la transferencia.
            destino: Usuario destino de la transferencia.

        Raises:
            OperacionNoPermitidaException: Si la transferencia viola la jerarquía.
        """
        allowed_transfers = {
            ROLE_ADMIN: [ROLE_DISTRIBUIDOR, ROLE_VENDEDOR],
            ROLE_DISTRIBUIDOR: [ROLE_VENDEDOR, ROLE_CLIENTE],
            ROLE_VENDEDOR: [ROLE_CLIENTE],
            ROLE_CLIENTE: []
        }
        if destino.rol not in allowed_transfers.get(origen.rol, []):
            logger.warning(
                f"Transferencia no permitida de {origen.username} (rol: {origen.rol}) a "
                f"{destino.username} (rol: {destino.rol})"
            )
            raise OperacionNoPermitidaException(
                _("Transferencia no permitida de %(origen)s a %(destino)s.") % {
                    'origen': origen.rol, 'destino': destino.rol
                }
            )

        # Verificar que las billeteras compartan la misma jerarquía
        origen_wallet = Wallet.objects.filter(user=origen).first()
        destino_wallet = Wallet.objects.filter(user=destino).first()
        if not origen_wallet or not destino_wallet:
            logger.warning(
                f"Billetera no encontrada para transferencia: origen {origen.username}, destino {destino.username}"
            )
            raise OperacionNoPermitidaException(_("Una de las billeteras no está configurada."))
        if origen_wallet == destino_wallet:
            logger.warning(f"Transferencia a la misma billetera: {origen.username}")
            raise OperacionNoPermitidaException(_("No se puede transferir a la misma billetera."))
        if origen_wallet.hierarchy_root != destino_wallet.hierarchy_root and \
           (origen_wallet.hierarchy_root is not None or destino_wallet.hierarchy_root is not None):
            logger.warning(
                f"Jerarquías no coinciden: origen {origen_wallet.hierarchy_root}, destino {destino_wallet.hierarchy_root}"
            )
            raise OperacionNoPermitidaException(_("Las billeteras no pertenecen a la misma jerarquía."))

    @staticmethod
    def validar_referencia(wallet: Wallet, referencia: str) -> None:
        """
        Valida que la referencia externa no esté duplicada para la billetera.

        Args:
            wallet: Billetera asociada.
            referencia: Referencia externa a validar.

        Raises:
            ReferenciaExternaDuplicadaException: Si la referencia ya existe.
        """
        if referencia and WalletMovement.objects.filter(wallet=wallet, referencia=referencia).exists():
            logger.warning(f"Referencia duplicada para wallet {wallet.id}: {referencia}")
            raise ReferenciaExternaDuplicadaException(
                _("Referencia externa ya procesada: %(referencia)s.") % {'referencia': referencia}
            )

    @staticmethod
    def validar_permiso_operacion(usuario: User, operacion: str) -> None:
        """
        Valida que el usuario tenga permisos para realizar la operación.

        Args:
            usuario: Usuario que realiza la operación.
            operacion: Nombre de la operación (e.g., 'creditar', 'transferir').

        Raises:
            OperacionNoPermitidaException: Si el usuario no tiene permisos.
        """
        raise_if_not_allowed(usuario, f"wallet.{operacion}")