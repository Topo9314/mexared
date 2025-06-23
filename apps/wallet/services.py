import uuid
import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.db.models import Sum
from apps.users.models import User, UserChangeLog, ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR, ROLE_CLIENTE  # Importación corregida
from apps.users.services.auth_service import AuthService
from apps.wallet.models import Moneda, Wallet, WalletMovement, MIN_AMOUNT, MAX_AMOUNT
from apps.vendedores.models import DistribuidorVendedor
from .enums import TipoMovimiento
from .exceptions import (
    SaldoInsuficienteException,
    LimiteExcedidoException,
    OperacionNoPermitidaException,
    MovimientoInvalidoException,
    BloqueoFondosInvalidoException,
    ConciliacionInvalidaException,
    ReferenciaExternaDuplicadaException,
)

# Configuración avanzada de logging para auditoría empresarial
logger = logging.getLogger(__name__)

class WalletService:
    """
    Servicio centralizado para operaciones financieras en el módulo Wallet de MexaRed.
    Gestiona saldos con atomicidad, seguridad y trazabilidad completa, diseñado para entornos SaaS multinivel.
    Cumple con PCI-DSS Level 1, SOC2 Type 2, ISO 27001, y requisitos fiscales (SAT).

    Attributes:
        LIMITE_TRANSFERENCIA_DIARIA: Límite diario para transferencias (MXN).
        LIMITE_BLOQUEO: Límite máximo para bloqueo de fondos (MXN).
    """
    LIMITE_TRANSFERENCIA_DIARIA = Decimal('100000.00')
    LIMITE_BLOQUEO = Decimal('50000.00')

    @staticmethod
    def _validar_monto(monto: Decimal) -> None:
        """
        Valida que el monto sea positivo y esté dentro de los límites permitidos.

        Args:
            monto: Monto a validar.

        Raises:
            MovimientoInvalidoException: Si el monto es inválido o fuera de rango.
        """
        if not isinstance(monto, Decimal) or monto < MIN_AMOUNT or monto > MAX_AMOUNT:
            logger.warning(f"Monto inválido detectado: {monto} (rango permitido: {MIN_AMOUNT} a {MAX_AMOUNT})")
            raise MovimientoInvalidoException(
                _("El monto debe estar entre %(min)s y %(max)s MXN.") % {
                    'min': MIN_AMOUNT, 'max': MAX_AMOUNT
                }
            )

    @staticmethod
    def _validar_referencia(referencia: str, wallet: Wallet) -> None:
        """
        Valida que la referencia externa no esté duplicada para la billetera.

        Args:
            referencia: Referencia externa a validar.
            wallet: Billetera asociada.

        Raises:
            ReferenciaExternaDuplicadaException: Si la referencia ya existe.
        """
        if referencia and WalletMovement.objects.filter(wallet=wallet, referencia=referencia).exists():
            logger.warning(f"Referencia duplicada detectada: {referencia} para wallet {wallet.id}")
            raise ReferenciaExternaDuplicadaException()

    @staticmethod
    def _registrar_auditoria(wallet: Wallet, tipo: str, monto: Decimal, referencia: str, creado_por: User, actor_ip: str, device_info: str, detalles: dict) -> None:
        """
        Registra la operación en UserChangeLog para auditoría con detalles completos.

        Args:
            wallet: Billetera asociada.
            tipo: Tipo de movimiento.
            monto: Monto de la operación.
            referencia: Referencia externa.
            creado_por: Usuario que realiza la operación.
            actor_ip: IP de origen.
            device_info: Información del dispositivo.
            detalles: Detalles adicionales para auditoría.
        """
        audit_details = {
            "tipo": tipo,
            "monto": str(monto),
            "referencia": referencia or "",
            "actor_ip": actor_ip or "unknown",
            "device_info": device_info or "unknown",
            **detalles
        }
        UserChangeLog.objects.create(
            user=wallet.user,
            changed_by=creado_por,
            change_type='update',
            change_description=f"Operación financiera: {tipo}",
            details=audit_details
        )
        logger.info(f"Operación {tipo} registrada para {wallet.user.username}: {monto} MXN, ref: {referencia or 'N/A'}")

    @staticmethod
    def _validar_moneda(moneda_codigo: str) -> Moneda:
        """
        Valida que la moneda esté configurada y activa.

        Args:
            moneda_codigo: Código de moneda (e.g., 'MXN').

        Returns:
            Moneda: Instancia del modelo Moneda.

        Raises:
            MovimientoInvalidoException: Si la moneda no está configurada.
        """
        try:
            return Moneda.objects.get(codigo=moneda_codigo)
        except Moneda.DoesNotExist:
            logger.error(f"Moneda no encontrada: {moneda_codigo}")
            raise MovimientoInvalidoException(_("Moneda no configurada: %(codigo)s.") % {'codigo': moneda_codigo})

    @staticmethod
    def _validar_permiso_operacion(usuario: User, operacion: str) -> None:
        """
        Valida que el usuario tenga permisos para realizar la operación.

        Args:
            usuario: Usuario que realiza la operación.
            operacion: Nombre de la operación (e.g., 'creditar', 'transferir').

        Raises:
            OperacionNoPermitidaException: Si el usuario no tiene permisos.
        """
        if not AuthService.has_permission(usuario, f"wallet.{operacion}"):
            logger.warning(f"Permiso denegado para {operacion} a usuario {usuario.username} (rol: {usuario.rol})")
            raise OperacionNoPermitidaException(
                _("Usuario %(username)s no tiene permiso para %(operacion)s.") % {
                    'username': usuario.username, 'operacion': operacion
                }
            )

    @staticmethod
    def validate_transfer_hierarchy(origen_wallet: Wallet, destino_wallet: Wallet) -> None:
        """
        Valida que la transferencia cumpla con las reglas jerárquicas multinivel.

        Args:
            origen_wallet: Billetera origen.
            destino_wallet: Billetera destino.

        Raises:
            OperacionNoPermitidaException: Si la transferencia viola la jerarquía.
        """
        if origen_wallet == destino_wallet:
            logger.warning(f"Intento de transferencia a la misma billetera: {origen_wallet.user.username}")
            raise OperacionNoPermitidaException(_("No se puede transferir a la misma billetera."))
        # Permitir null hierarchy_root para Admin, pero validar jerarquía para otros
        if origen_wallet.hierarchy_root != destino_wallet.hierarchy_root and \
           (origen_wallet.hierarchy_root is not None or destino_wallet.hierarchy_root is not None):
            if origen_wallet.user.rol == ROLE_DISTRIBUIDOR and destino_wallet.user.rol == ROLE_VENDEDOR:
                if not DistribuidorVendedor.objects.filter(
                    distribuidor=origen_wallet.user,
                    vendedor=destino_wallet.user,
                    activo=True
                ).exists():
                    logger.warning(
                        f"Transferencia denegada: Vendedor {destino_wallet.user.username} no subordinado a {origen_wallet.user.username}"
                    )
                    raise OperacionNoPermitidaException(_("El vendedor no está subordinado al distribuidor."))
            else:
                logger.warning(
                    f"Jerarquías no coinciden: Origen {origen_wallet.user.username} (root: {origen_wallet.hierarchy_root_id}), "
                    f"Destino {destino_wallet.user.username} (root: {destino_wallet.hierarchy_root_id})"
                )
                raise OperacionNoPermitidaException(_("Las billeteras no pertenecen a la misma jerarquía."))

        allowed_transfers = {
            ROLE_ADMIN: [ROLE_DISTRIBUIDOR, ROLE_VENDEDOR, ROLE_CLIENTE],
            ROLE_DISTRIBUIDOR: [ROLE_VENDEDOR, ROLE_CLIENTE],
            ROLE_VENDEDOR: [ROLE_CLIENTE],
            ROLE_CLIENTE: []
        }
        origen_role = origen_wallet.user.rol
        destino_role = destino_wallet.user.rol
        if destino_role not in allowed_transfers.get(origen_role, []):
            logger.warning(f"Transferencia no permitida de {origen_role} a {destino_role}")
            raise OperacionNoPermitidaException(
                _("Transferencia no permitida de %(origen)s a %(destino)s.") % {
                    'origen': origen_role, 'destino': destino_role
                }
            )

    @staticmethod
    @transaction.atomic
    def deposit(
        wallet: Wallet,
        amount: Decimal,
        creado_por: User = None,
        referencia: str = None,
        actor_ip: str = None,
        device_info: str = None,
        moneda_codigo: str = 'MXN'
    ) -> WalletMovement:
        """
        Realiza un depósito en la billetera con auditoría y validaciones estrictas.

        Args:
            wallet: Billetera destino.
            amount: Monto a depositar.
            creado_por: Usuario que realiza la operación (opcional).
            referencia: Referencia externa (e.g., MercadoPago ID).
            actor_ip: IP de origen (opcional).
            device_info: Información del dispositivo (opcional).
            moneda_codigo: Código de moneda (default: MXN).

        Returns:
            WalletMovement: Movimiento registrado.

        Raises:
            MovimientoInvalidoException: Si el monto o moneda es inválido.
            ReferenciaExternaDuplicadaException: Si la referencia ya existe.
            OperacionNoPermitidaException: Si el usuario no tiene permisos.
        """
        WalletService._validar_monto(amount)
        WalletService._validar_referencia(referencia, wallet)
        WalletService._validar_moneda(moneda_codigo)
        if creado_por:
            WalletService._validar_permiso_operacion(creado_por, 'creditar')

        with transaction.atomic():
            wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
            wallet.balance += amount
            wallet.save(update_fields=['balance', 'last_updated'])

            movimiento = WalletMovement.objects.create(
                wallet=wallet,
                tipo=TipoMovimiento.CREDITO.name,
                monto=amount,
                referencia=referencia,
                creado_por=creado_por,
                actor_ip=actor_ip or 'unknown',
                device_info=device_info or 'unknown'
            )

            WalletService._registrar_auditoria(
                wallet, TipoMovimiento.CREDITO.name, amount, referencia, creado_por,
                actor_ip or 'unknown', device_info or 'unknown',
                {"moneda": moneda_codigo, "movimiento_id": str(movimiento.id)}
            )

        return movimiento

    @staticmethod
    @transaction.atomic
    def withdraw(
        wallet: Wallet,
        amount: Decimal,
        creado_por: User = None,
        referencia: str = None,
        actor_ip: str = None,
        device_info: str = None,
        moneda_codigo: str = 'MXN'
    ) -> WalletMovement:
        """
        Realiza un retiro de la billetera con auditoría y validaciones estrictas.

        Args:
            wallet: Billetera origen.
            amount: Monto a retirar.
            creado_por: Usuario que realiza la operación (opcional).
            referencia: Referencia externa (e.g., Addinteli ID).
            actor_ip: IP de origen (opcional).
            device_info: Información del dispositivo (opcional).
            moneda_codigo: Código de moneda (default: MXN).

        Returns:
            WalletMovement: Movimiento registrado.

        Raises:
            SaldoInsuficienteException: Si el saldo es insuficiente.
            MovimientoInvalidoException: Si el monto o moneda es inválido.
            ReferenciaExternaDuplicadaException: Si la referencia ya existe.
            OperacionNoPermitidaException: Si el usuario no tiene permisos.
        """
        WalletService._validar_monto(amount)
        WalletService._validar_referencia(referencia, wallet)
        WalletService._validar_moneda(moneda_codigo)
        if creado_por:
            WalletService._validar_permiso_operacion(creado_por, 'debitar')
        wallet.validate_sufficient_balance(amount, operation='debit')

        with transaction.atomic():
            wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
            wallet.balance -= amount
            wallet.save(update_fields=['balance', 'last_updated'])

            movimiento = WalletMovement.objects.create(
                wallet=wallet,
                tipo=TipoMovimiento.DEBITO.name,
                monto=amount,
                referencia=referencia,
                creado_por=creado_por,
                actor_ip=actor_ip or 'unknown',
                device_info=device_info or 'unknown'
            )

            WalletService._registrar_auditoria(
                wallet, TipoMovimiento.DEBITO.name, amount, referencia, creado_por,
                actor_ip or 'unknown', device_info or 'unknown',
                {"moneda": moneda_codigo, "movimiento_id": str(movimiento.id)}
            )

        return movimiento

    @staticmethod
    @transaction.atomic
    def transfer(
        origen_wallet: Wallet,
        destino_wallet: Wallet,
        amount: Decimal,
        creado_por: User = None,
        referencia: str = None,
        actor_ip: str = None,
        device_info: str = None,
        moneda_codigo: str = 'MXN'
    ) -> tuple[WalletMovement, WalletMovement]:
        """
        Realiza una transferencia entre billeteras con validación jerárquica y auditoría.

        Args:
            origen_wallet: Billetera origen.
            destino_wallet: Billetera destino.
            amount: Monto a transferir.
            creado_por: Usuario que realiza la operación (opcional).
            referencia: Referencia externa.
            actor_ip: IP de origen (opcional).
            device_info: Información del dispositivo (opcional).
            moneda_codigo: Código de moneda (default: MXN).

        Returns:
            tuple: Movimientos de débito (origen) y crédito (destino).

        Raises:
            OperacionNoPermitidaException: Si la transferencia viola jerarquías.
            SaldoInsuficienteException: Si el saldo es insuficiente.
            MovimientoInvalidoException: Si el monto o moneda es inválido.
            LimiteExcedidoException: Si excede límites antifraude.
            ReferenciaExternaDuplicadaException: Si la referencia ya existe.
        """
        WalletService._validar_monto(amount)
        WalletService._validar_referencia(referencia, origen_wallet)
        WalletService._validar_moneda(moneda_codigo)
        if creado_por:
            WalletService._validar_permiso_operacion(creado_por, 'transferir')
        WalletService.validate_transfer_hierarchy(origen_wallet, destino_wallet)
        origen_wallet.validate_sufficient_balance(amount, operation='debit')

        # Validar límite antifraude diario
        movimientos_hoy = WalletMovement.objects.filter(
            wallet=origen_wallet,
            tipo=TipoMovimiento.TRANSFERENCIA_INTERNA.name,
            fecha__date=timezone.now().date()
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
        if movimientos_hoy + amount > WalletService.LIMITE_TRANSFERENCIA_DIARIA:
            logger.warning(f"Límite diario excedido: {movimientos_hoy + amount} > {WalletService.LIMITE_TRANSFERENCIA_DIARIA}")
            raise LimiteExcedidoException(_("Límite diario de transferencias excedido: %(limite)s MXN.") % {
                'limite': WalletService.LIMITE_TRANSFERENCIA_DIARIA
            })

        with transaction.atomic():
            origen_wallet = Wallet.objects.select_for_update().get(pk=origen_wallet.pk)
            destino_wallet = Wallet.objects.select_for_update().get(pk=destino_wallet.pk)

            debito = WalletMovement.objects.create(
                wallet=origen_wallet,
                tipo=TipoMovimiento.TRANSFERENCIA_INTERNA.name,
                monto=amount,
                referencia=referencia,
                creado_por=creado_por,
                actor_ip=actor_ip or 'unknown',
                device_info=device_info or 'unknown',
                origen_wallet=origen_wallet
            )
            credito = WalletMovement.objects.create(
                wallet=destino_wallet,
                tipo=TipoMovimiento.TRANSFERENCIA_INTERNA.name,
                monto=amount,
                referencia=referencia,
                creado_por=creado_por,
                actor_ip=actor_ip or 'unknown',
                device_info=device_info or 'unknown',
                origen_wallet=origen_wallet
            )

            origen_wallet.balance -= amount
            destino_wallet.balance += amount
            origen_wallet.save(update_fields=['balance', 'last_updated'])
            destino_wallet.save(update_fields=['balance', 'last_updated'])

            WalletService._registrar_auditoria(
                origen_wallet, TipoMovimiento.TRANSFERENCIA_INTERNA.name, amount, referencia, creado_por,
                actor_ip or 'unknown', device_info or 'unknown',
                {
                    "destino": destino_wallet.user.username,
                    "moneda": moneda_codigo,
                    "debito_id": str(debito.id),
                    "credito_id": str(credito.id)
                }
            )

        return debito, credito

    @staticmethod
    @transaction.atomic
    def block_funds(
        wallet: Wallet,
        amount: Decimal,
        creado_por: User = None,
        referencia: str = None,
        actor_ip: str = None,
        device_info: str = None,
        moneda_codigo: str = 'MXN'
    ) -> WalletMovement:
        """
        Bloquea fondos en la billetera para disputas o prevención de fraude.

        Args:
            wallet: Billetera a bloquear.
            amount: Monto a bloquear.
            creado_por: Usuario que realiza la operación (opcional).
            referencia: Referencia externa.
            actor_ip: IP de origen (opcional).
            device_info: Información del dispositivo (opcional).
            moneda_codigo: Código de moneda (default: MXN).

        Returns:
            WalletMovement: Movimiento registrado.

        Raises:
            SaldoInsuficienteException: Si el saldo es insuficiente.
            MovimientoInvalidoException: Si el monto o moneda es inválido.
            LimiteExcedidoException: Si excede el límite de bloqueo.
            ReferenciaExternaDuplicadaException: Si la referencia ya existe.
            OperacionNoPermitidaException: Si el usuario no tiene permisos.
        """
        WalletService._validar_monto(amount)
        WalletService._validar_referencia(referencia, wallet)
        WalletService._validar_moneda(moneda_codigo)
        if creado_por:
            WalletService._validar_permiso_operacion(creado_por, 'bloquear')
        wallet.validate_sufficient_balance(amount, operation='block')

        if amount > WalletService.LIMITE_BLOQUEO:
            logger.warning(f"Monto de bloqueo excede límite: {amount} > {WalletService.LIMITE_BLOQUEO}")
            raise LimiteExcedidoException(
                _("Límite de bloqueo excedido: %(limite)s MXN.") % {'limite': WalletService.LIMITE_BLOQUEO}
            )

        with transaction.atomic():
            wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
            wallet.balance -= amount
            wallet.blocked_balance += amount
            wallet.save(update_fields=['balance', 'blocked_balance', 'last_updated'])

            movimiento = WalletMovement.objects.create(
                wallet=wallet,
                tipo=TipoMovimiento.BLOQUEO.name,
                monto=amount,
                referencia=referencia,
                creado_por=creado_por,
                actor_ip=actor_ip or 'unknown',
                device_info=device_info or 'unknown'
            )

            WalletService._registrar_auditoria(
                wallet, TipoMovimiento.BLOQUEO.name, amount, referencia, creado_por,
                actor_ip or 'unknown', device_info or 'unknown',
                {"moneda": moneda_codigo, "movimiento_id": str(movimiento.id)}
            )

        return movimiento

    @staticmethod
    @transaction.atomic
    def unblock_funds(
        wallet: Wallet,
        amount: Decimal,
        creado_por: User = None,
        referencia: str = None,
        actor_ip: str = None,
        device_info: str = None,
        moneda_codigo: str = 'MXN'
    ) -> WalletMovement:
        """
        Desbloquea fondos previamente bloqueados en la billetera.

        Args:
            wallet: Billetera a desbloquear.
            amount: Monto a desbloquear.
            creado_por: Usuario que realiza la operación (opcional).
            referencia: Referencia externa.
            actor_ip: IP de origen (opcional).
            device_info: Información del dispositivo (opcional).
            moneda_codigo: Código de moneda (default: MXN).

        Returns:
            WalletMovement: Movimiento registrado.

        Raises:
            BloqueoFondosInvalidoException: Si el saldo bloqueado es insuficiente.
            MovimientoInvalidoException: Si el monto o moneda es inválido.
            ReferenciaExternaDuplicadaException: Si la referencia ya existe.
            OperacionNoPermitidaException: Si el usuario no tiene permisos.
        """
        WalletService._validar_monto(amount)
        WalletService._validar_referencia(referencia, wallet)
        WalletService._validar_moneda(moneda_codigo)
        if creado_por:
            WalletService._validar_permiso_operacion(creado_por, 'desbloquear')

        with transaction.atomic():
            wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
            if wallet.blocked_balance < amount:
                logger.warning(f"Saldo bloqueado insuficiente: {wallet.blocked_balance} < {amount}")
                raise BloqueoFondosInvalidoException(
                    _("Saldo bloqueado insuficiente: %(disponible)s MXN, se requieren %(requerido)s MXN.") % {
                        'disponible': wallet.blocked_balance, 'requerido': amount
                    }
                )
            wallet.blocked_balance -= amount
            wallet.balance += amount
            wallet.save(update_fields=['balance', 'blocked_balance', 'last_updated'])

            movimiento = WalletMovement.objects.create(
                wallet=wallet,
                tipo=TipoMovimiento.DESBLOQUEO.name,
                monto=amount,
                referencia=referencia,
                creado_por=creado_por,
                actor_ip=actor_ip or 'unknown',
                device_info=device_info or 'unknown'
            )

            WalletService._registrar_auditoria(
                wallet, TipoMovimiento.DESBLOQUEO.name, amount, referencia, creado_por,
                actor_ip or 'unknown', device_info or 'unknown',
                {"moneda": moneda_codigo, "movimiento_id": str(movimiento.id)}
            )

        return movimiento

    @staticmethod
    @transaction.atomic
    def manual_adjustment(
        wallet: Wallet,
        amount: Decimal,
        creado_por: User = None,
        referencia: str = None,
        actor_ip: str = None,
        device_info: str = None,
        moneda_codigo: str = 'MXN'
    ) -> WalletMovement:
        """
        Realiza un ajuste manual administrativo en la billetera (positivo o negativo).

        Args:
            wallet: Billetera a ajustar.
            amount: Monto del ajuste (positivo o negativo).
            creado_por: Usuario que realiza la operación (opcional).
            referencia: Referencia externa.
            actor_ip: IP de origen (opcional).
            device_info: Información del dispositivo (opcional).
            moneda_codigo: Código de moneda (default: MXN).

        Returns:
            WalletMovement: Movimiento registrado.

        Raises:
            MovimientoInvalidoException: Si el monto o moneda es inválido.
            SaldoInsuficienteException: Si el ajuste negativo excede el saldo.
            ReferenciaExternaDuplicadaException: Si la referencia ya existe.
            OperacionNoPermitidaException: Si el usuario no tiene permisos.
        """
        if not isinstance(amount, Decimal):
            logger.error(f"Monto no válido: {amount} (no es Decimal)")
            raise MovimientoInvalidoException(_("El monto debe ser un valor Decimal válido."))
        if abs(amount) < MIN_AMOUNT or abs(amount) > MAX_AMOUNT:
            logger.warning(f"Monto fuera de rango: {amount} (rango: {MIN_AMOUNT} a {MAX_AMOUNT})")
            raise MovimientoInvalidoException(
                _("El monto absoluto debe estar entre %(min)s y %(max)s MXN.") % {
                    'min': MIN_AMOUNT, 'max': MAX_AMOUNT
                }
            )
        WalletService._validar_referencia(referencia, wallet)
        WalletService._validar_moneda(moneda_codigo)
        if creado_por:
            WalletService._validar_permiso_operacion(creado_por, 'ajuste_manual')
        if amount < 0:
            wallet.validate_sufficient_balance(abs(amount), operation='debit')

        with transaction.atomic():
            wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
            wallet.balance += amount
            wallet.save(update_fields=['balance', 'last_updated'])

            movimiento = WalletMovement.objects.create(
                wallet=wallet,
                tipo=TipoMovimiento.AJUSTE_MANUAL.name,
                monto=abs(amount),
                referencia=referencia,
                creado_por=creado_por,
                actor_ip=actor_ip or 'unknown',
                device_info=device_info or 'unknown'
            )

            WalletService._registrar_auditoria(
                wallet, TipoMovimiento.AJUSTE_MANUAL.name, amount, referencia, creado_por,
                actor_ip or 'unknown', device_info or 'unknown',
                {"moneda": moneda_codigo, "movimiento_id": str(movimiento.id)}
            )

        return movimiento

    @staticmethod
    @transaction.atomic
    def conciliar(
        wallet: Wallet,
        movimiento_id: uuid.UUID,
        referencia_externa: str,
        creado_por: User = None,
        actor_ip: str = None,
        device_info: str = None
    ) -> WalletMovement:
        """
        Marca un movimiento como conciliado con una referencia externa.

        Args:
            wallet: Billetera asociada.
            movimiento_id: ID del movimiento a conciliar.
            referencia_externa: Referencia del sistema externo.
            creado_por: Usuario que realiza la operación (opcional).
            actor_ip: IP de origen (opcional).
            device_info: Información del dispositivo (opcional).

        Returns:
            WalletMovement: Movimiento actualizado.

        Raises:
            ConciliacionInvalidaException: Si el movimiento no existe o ya está conciliado.
            OperacionNoPermitidaException: Si el usuario no tiene permisos.
        """
        if creado_por:
            WalletService._validar_permiso_operacion(creado_por, 'conciliar')
        WalletService._validar_referencia(referencia_externa, wallet)

        with transaction.atomic():
            try:
                movimiento = WalletMovement.objects.select_for_update().get(
                    id=movimiento_id, wallet=wallet
                )
            except WalletMovement.DoesNotExist:
                logger.error(f"Movimiento no encontrado: {movimiento_id} para wallet {wallet.id}")
                raise ConciliacionInvalidaException(_("Movimiento no encontrado: %(id)s.") % {'id': movimiento_id})

            if movimiento.conciliado:
                logger.warning(f"Movimiento ya conciliado: {movimiento_id}")
                raise ConciliacionInvalidaException(_("El movimiento ya está conciliado."))

            movimiento.conciliado = True
            movimiento.fecha_conciliacion = timezone.now()
            movimiento.referencia = referencia_externa
            movimiento.save(update_fields=['conciliado', 'fecha_conciliacion', 'referencia'])

            WalletService._registrar_auditoria(
                wallet, "CONCILIACION", Decimal('0.00'), referencia_externa, creado_por,
                actor_ip or 'unknown', device_info or 'unknown',
                {"movimiento_id": str(movimiento.id), "referencia_externa": referencia_externa}
            )

        return movimiento