"""
Servicio especializado de asignación de saldo en MexaRed.
Orquesta el proceso de transferencia entre usuarios con validaciones, seguridad y trazabilidad.
Diseñado para integraciones futuras con APIs externas y lógica antifraude.
"""

import logging
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.transacciones.services.saldo_service import SaldoService
from apps.transacciones.services.validaciones import Validaciones
from apps.users.services.auth_service import AuthService

# Configuración de logging para monitoreo en producción
logger = logging.getLogger(__name__)

class AsignarSaldoService:
    """
    Servicio para orquestar la asignación de saldo entre usuarios en MexaRed.
    Centraliza validaciones, permisos y auditoría para transferencias seguras y trazables.
    """

    @staticmethod
    def asignar_saldo_general(emisor, receptor, monto, motivo_codigo=None):
        """
        Función orquestadora para asignar saldo entre usuarios con diferentes roles.

        Args:
            emisor (User): Usuario que transfiere saldo (admin o distribuidor).
            receptor (User): Usuario que recibe saldo (distribuidor o vendedor).
            monto (Decimal): Monto a transferir.
            motivo_codigo (str, optional): Código del motivo para la auditoría.

        Returns:
            Transaccion: Transacción registrada exitosamente.

        Raises:
            ValidationError: Si ocurre alguna violación de reglas o permisos.
        """
        # Validar tipo de monto
        Validaciones.validar_monto(monto)

        # Validar autenticación y permisos del emisor
        if not AuthService.is_authenticated(emisor) or not AuthService.is_active(emisor):
            logger.error(f"Emisor {emisor.username} no está autenticado o activo")
            raise ValidationError(_("El emisor debe estar autenticado y activo."))

        # Validar permisos para la transacción
        Validaciones.validar_permiso_transaccion(emisor, 'can_assign_saldo')

        # Validar combinación de roles
        if emisor.has_role('admin') and receptor.has_role('distribuidor'):
            logger.debug(f"[ADMIN] {emisor.username} asignando saldo a {receptor.username}")
            transaccion = SaldoService.asignar_saldo_distribuidor(emisor, receptor, monto, motivo_codigo)
        elif emisor.has_role('distribuidor') and receptor.has_role('vendedor'):
            logger.debug(f"[DISTRIBUIDOR] {emisor.username} asignando saldo a {receptor.username}")
            transaccion = SaldoService.asignar_saldo_vendedor(emisor, receptor, monto, motivo_codigo)
        else:
            logger.warning(f"Intento no permitido de asignación de saldo entre {emisor.rol} → {receptor.rol}")
            raise ValidationError(_("Asignación de saldo no permitida entre estos roles."))

        logger.info(f"Saldo asignado exitosamente: {monto} MXN de {emisor.username} a {receptor.username} (Transacción ID: {transaccion.id})")
        return transaccion

    @staticmethod
    def puede_asignar_saldo(emisor, receptor):
        """
        Verifica si la asignación de saldo está permitida entre los roles de emisor y receptor.

        Args:
            emisor (User): Usuario que intenta asignar saldo.
            receptor (User): Usuario que recibiría el saldo.

        Returns:
            bool: True si la asignación es permitida, False en caso contrario.
        """
        try:
            if not AuthService.is_authenticated(emisor) or not AuthService.is_active(emisor):
                logger.debug(f"Emisor {emisor.username} no autenticado o inactivo")
                return False

            if emisor.has_role('admin') and receptor.has_role('distribuidor'):
                logger.debug(f"Permiso válido: {emisor.username} (admin) → {receptor.username} (distribuidor)")
                return True
            if emisor.has_role('distribuidor') and receptor.has_role('vendedor'):
                logger.debug(f"Permiso válido: {emisor.username} (distribuidor) → {receptor.username} (vendedor)")
                return True

            logger.debug(f"Permiso denegado: {emisor.rol} → {receptor.rol}")
            return False
        except Exception as e:
            logger.error(f"Error al verificar permisos de asignación para {emisor.username} → {receptor.username}: {str(e)}")
            return False