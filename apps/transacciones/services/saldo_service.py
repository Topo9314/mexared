"""
Servicio de saldo para MexaRed.
Proporciona funciones para gestionar saldos de usuarios (asignar, descontar, consultar) y obtener resúmenes,
con validaciones de permisos, auditoría detallada y registro de transacciones.
Optimizado para entornos internacionales de alto volumen, enfocado en México.
"""

import logging
from decimal import Decimal
from django.db import transaction
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.users.models import User, UserChangeLog
from apps.users.services.auth_service import AuthService
from apps.transacciones.models import Transaccion, Moneda, MotivoTransaccion
from apps.vendedores.models import DistribuidorVendedor

# Configuración de logging para monitoreo en producción
logger = logging.getLogger(__name__)

class SaldoService:
    """
    Servicio para gestionar saldos de usuarios en MexaRed.
    Incluye asignación, descuento, consulta de saldos y resúmenes, con validaciones y auditoría.
    """

    @staticmethod
    def obtener_resumen_saldo(usuario):
        """
        Obtiene el saldo actual y las últimas transacciones del usuario.

        Args:
            usuario (User): Instancia del modelo User.

        Returns:
            dict: Resumen con saldo actual y últimas 5 transacciones.
        """
        try:
            saldo_actual = SaldoService.consultar_saldo(usuario)
            transacciones = Transaccion.objects.filter(
                Q(emisor=usuario) | Q(receptor=usuario)
            ).select_related('moneda', 'motivo').order_by('-fecha_creacion')[:5]

            logger.debug(f"Resumen de saldo generado para usuario {usuario.username}: {saldo_actual}")
            return {
                "saldo_actual": saldo_actual,
                "ultimas_transacciones": transacciones
            }
        except Exception as e:
            logger.error(f"Error al obtener resumen de saldo para {usuario.username}: {str(e)}")
            return {
                "saldo_actual": Decimal('0.00'),
                "ultimas_transacciones": []
            }

    @staticmethod
    @transaction.atomic
    def asignar_saldo_distribuidor(admin, distribuidor, monto, motivo_codigo=None):
        """
        Asigna saldo a un distribuidor desde un administrador, registrando la transacción.

        Args:
            admin (User): Usuario administrador que realiza la asignación.
            distribuidor (User): Distribuidor que recibe el saldo.
            monto (Decimal): Monto a asignar.
            motivo_codigo (str, optional): Código del motivo de la transacción.

        Returns:
            Transaccion: Instancia de la transacción creada.

        Raises:
            ValidationError: Si no se cumplen las validaciones de permisos o saldo.
        """
        # Validar permisos
        if not AuthService.is_admin(admin):
            logger.error(f"Usuario {admin.username} no tiene permisos para asignar saldo a distribuidor")
            raise ValidationError(_("Solo administradores pueden asignar saldo a distribuidores."))

        # Validar rol del distribuidor
        if not distribuidor.has_role('distribuidor'):
            logger.error(f"Usuario {distribuidor.username} no es distribuidor")
            raise ValidationError(_("El receptor debe ser un distribuidor."))

        # Validar monto
        if not isinstance(monto, Decimal) or monto <= 0:
            logger.error(f"Monto inválido para asignación: {monto}")
            raise ValidationError(_("El monto debe ser mayor a cero."))

        # Obtener moneda MXN
        try:
            moneda = Moneda.objects.get(codigo='MXN')
        except Moneda.DoesNotExist:
            logger.error("Moneda MXN no encontrada")
            raise ValidationError(_("Moneda MXN no configurada."))

        # Obtener motivo (si se proporciona)
        motivo = None
        if motivo_codigo:
            try:
                motivo = MotivoTransaccion.objects.get(codigo=motivo_codigo, activo=True)
            except MotivoTransaccion.DoesNotExist:
                logger.warning(f"Motivo {motivo_codigo} no encontrado o inactivo")

        # Crear transacción
        transaccion = Transaccion.objects.create(
            tipo='ASIGNACION',
            monto=monto,
            moneda=moneda,
            emisor=admin,
            receptor=distribuidor,
            motivo=motivo,
            descripcion=f"Asignación de saldo a distribuidor {distribuidor.username}",
            realizado_por=admin,
            estado='EXITOSA'
        )

        # Actualizar saldo en DistribuidorVendedor (si existe)
        try:
            perfil = DistribuidorVendedor.objects.get(distribuidor=distribuidor)
            perfil.saldo_asignado += monto
            perfil.saldo_disponible += monto
            perfil.save()
            logger.info(f"Saldo asignado a distribuidor {distribuidor.username}: {monto} MXN")
        except DistribuidorVendedor.DoesNotExist:
            logger.warning(f"Perfil DistribuidorVendedor no encontrado para {distribuidor.username}")

        # Registrar en UserChangeLog
        UserChangeLog.objects.create(
            user=distribuidor,
            changed_by=admin,
            change_type='update',
            change_description="Asignación de saldo por administrador",
            details={
                "monto": str(monto),
                "moneda": moneda.codigo,
                "transaccion_id": transaccion.id,
                "admin": admin.username
            }
        )

        return transaccion

    @staticmethod
    @transaction.atomic
    def asignar_saldo_vendedor(distribuidor, vendedor, monto, motivo_codigo=None):
        """
        Asigna saldo a un vendedor desde un distribuidor, registrando la transacción.

        Args:
            distribuidor (User): Distribuidor que asigna el saldo.
            vendedor (User): Vendedor que recibe el saldo.
            monto (Decimal): Monto a asignar.
            motivo_codigo (str, optional): Código del motivo de la transacción.

        Returns:
            Transaccion: Instancia de la transacción creada.

        Raises:
            ValidationError: Si no se cumplen las validaciones de permisos o saldo.
        """
        # Validar permisos
        if not AuthService.can_transfer_saldo(distribuidor):
            logger.error(f"Usuario {distribuidor.username} no tiene permisos para asignar saldo")
            raise ValidationError(_("Solo distribuidores o administradores pueden asignar saldo."))

        # Validar rol del vendedor
        if not vendedor.has_role('vendedor'):
            logger.error(f"Usuario {vendedor.username} no es vendedor")
            raise ValidationError(_("El receptor debe ser un vendedor."))

        # Validar relación Distribuidor-Vendedor
        try:
            relacion = DistribuidorVendedor.objects.get(distribuidor=distribuidor, vendedor=vendedor, activo=True)
        except DistribuidorVendedor.DoesNotExist:
            logger.error(f"No existe relación activa entre {distribuidor.username} y {vendedor.username}")
            raise ValidationError(_("No existe una relación activa entre el distribuidor y el vendedor."))

        # Validar monto
        if not isinstance(monto, Decimal) or monto <= 0:
            logger.error(f"Monto inválido para asignación: {monto}")
            raise ValidationError(_("El monto debe ser mayor a cero."))

        # Verificar saldo suficiente del distribuidor
        saldo_distribuidor = relacion.saldo_disponible
        if saldo_distribuidor < monto:
            logger.error(f"Saldo insuficiente para {distribuidor.username}: {saldo_distribuidor} < {monto}")
            raise ValidationError(_("Saldo insuficiente para realizar la asignación."))

        # Obtener moneda MXN
        try:
            moneda = Moneda.objects.get(codigo='MXN')
        except Moneda.DoesNotExist:
            logger.error("Moneda MXN no encontrada")
            raise ValidationError(_("Moneda MXN no configurada."))

        # Obtener motivo (si se proporciona)
        motivo = None
        if motivo_codigo:
            try:
                motivo = MotivoTransaccion.objects.get(codigo=motivo_codigo, activo=True)
            except MotivoTransaccion.DoesNotExist:
                logger.warning(f"Motivo {motivo_codigo} no encontrado o inactivo")

        # Descontar saldo del distribuidor
        relacion.saldo_disponible -= monto
        relacion.save()

        # Asignar saldo al vendedor
        relacion.saldo_asignado += monto
        relacion.saldo_disponible += monto
        relacion.save()

        # Crear transacción
        transaccion = Transaccion.objects.create(
            tipo='ASIGNACION',
            monto=monto,
            moneda=moneda,
            emisor=distribuidor,
            receptor=vendedor,
            motivo=motivo,
            descripcion=f"Asignación de saldo a vendedor {vendedor.username}",
            realizado_por=distribuidor,
            estado='EXITOSA'
        )

        # Registrar en UserChangeLog
        UserChangeLog.objects.create(
            user=vendedor,
            changed_by=distribuidor,
            change_type='update',
            change_description="Asignación de saldo por distribuidor",
            details={
                "monto": str(monto),
                "moneda": moneda.codigo,
                "transaccion_id": transaccion.id,
                "distribuidor": distribuidor.username
            }
        )

        logger.info(f"Saldo asignado a vendedor {vendedor.username} por {distribuidor.username}: {monto} MXN")
        return transaccion

    @staticmethod
    @transaction.atomic
    def descontar_saldo(usuario, monto, motivo_codigo=None):
        """
        Descuenta saldo de un usuario, registrando la transacción.

        Args:
            usuario (User): Usuario al que se descuenta el saldo.
            monto (Decimal): Monto a descontar.
            motivo_codigo (str, optional): Código del motivo de la transacción.

        Returns:
            Transaccion: Instancia de la transacción creada.

        Raises:
            ValidationError: Si no se cumplen las validaciones de saldo o rol.
        """
        # Validar rol del usuario
        if not (usuario.has_role('vendedor') or usuario.has_role('distribuidor')):
            logger.error(f"Usuario {usuario.username} no es vendedor ni distribuidor")
            raise ValidationError(_("Solo vendedores o distribuidores pueden descontar saldo."))

        # Validar monto
        if not isinstance(monto, Decimal) or monto <= 0:
            logger.error(f"Monto inválido para descuento: {monto}")
            raise ValidationError(_("El monto debe ser mayor a cero."))

        # Obtener perfil DistribuidorVendedor
        try:
            if usuario.has_role('vendedor'):
                perfil = DistribuidorVendedor.objects.get(vendedor=usuario, activo=True)
            else:  # distribuidor
                perfil = DistribuidorVendedor.objects.get(distribuidor=usuario, activo=True)
        except DistribuidorVendedor.DoesNotExist:
            logger.error(f"Perfil DistribuidorVendedor no encontrado para {usuario.username}")
            raise ValidationError(_("No se encontró un perfil activo para el usuario."))

        # Verificar saldo suficiente
        if perfil.saldo_disponible < monto:
            logger.error(f"Saldo insuficiente para {usuario.username}: {perfil.saldo_disponible} < {monto}")
            raise ValidationError(_("Saldo insuficiente para realizar el descuento."))

        # Obtener moneda MXN
        try:
            moneda = Moneda.objects.get(codigo='MXN')
        except Moneda.DoesNotExist:
            logger.error("Moneda MXN no encontrada")
            raise ValidationError(_("Moneda MXN no configurada."))

        # Obtener motivo (si se proporciona)
        motivo = None
        if motivo_codigo:
            try:
                motivo = MotivoTransaccion.objects.get(codigo=motivo_codigo, activo=True)
            except MotivoTransaccion.DoesNotExist:
                logger.warning(f"Motivo {motivo_codigo} no encontrado o inactivo")

        # Descontar saldo
        perfil.saldo_disponible -= monto
        perfil.save()

        # Crear transacción
        transaccion = Transaccion.objects.create(
            tipo='CONSUMO_API',
            monto=monto,
            moneda=moneda,
            emisor=usuario,
            motivo=motivo,
            descripcion=f"Descuento de saldo para {usuario.username}",
            realizado_por=usuario,
            estado='EXITOSA'
        )

        # Registrar en UserChangeLog
        UserChangeLog.objects.create(
            user=usuario,
            changed_by=usuario,
            change_type='update',
            change_description="Descuento de saldo",
            details={
                "monto": str(monto),
                "moneda": moneda.codigo,
                "transaccion_id": transaccion.id
            }
        )

        logger.info(f"Saldo descontado de {usuario.username}: {monto} MXN")
        return transaccion

    @staticmethod
    def consultar_saldo(usuario):
        """
        Consulta el saldo disponible de un usuario.

        Args:
            usuario (User): Instancia del modelo User.

        Returns:
            Decimal: Saldo disponible del usuario.

        Raises:
            ValidationError: Si no se encuentra un perfil activo.
        """
        try:
            if usuario.has_role('vendedor'):
                perfil = DistribuidorVendedor.objects.get(vendedor=usuario, activo=True)
            elif usuario.has_role('distribuidor'):
                perfil = DistribuidorVendedor.objects.get(distribuidor=usuario, activo=True)
            else:
                logger.debug(f"Usuario {usuario.username} no es vendedor ni distribuidor, saldo 0")
                return Decimal('0.00')
            
            saldo = perfil.saldo_disponible
            logger.debug(f"Saldo consultado para {usuario.username}: {saldo}")
            return saldo
        except DistribuidorVendedor.DoesNotExist:
            logger.warning(f"Perfil DistribuidorVendedor no encontrado para {usuario.username}")
            return Decimal('0.00')