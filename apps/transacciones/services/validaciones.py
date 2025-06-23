"""
Módulo de validaciones para MexaRed.
Centraliza validaciones reutilizables para transacciones y saldos,
asegurando consistencia y reduciendo duplicación de código.
Optimizado para entornos internacionales, enfocado en México.
"""

import logging
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.users.models import User
from apps.users.services.auth_service import AuthService
from apps.transacciones.models import Moneda
from apps.vendedores.models import DistribuidorVendedor

# Configuración de logging para monitoreo en producción
logger = logging.getLogger(__name__)

class Validaciones:
    """
    Clase con validaciones reutilizables para transacciones y saldos.
    Proporciona métodos para validar roles, montos, monedas, fechas y relaciones.
    """

    @staticmethod
    def validar_rol_usuario(usuario, roles_permitidos):
        """
        Valida que el usuario tenga uno de los roles permitidos.

        Args:
            usuario (User): Instancia del modelo User.
            roles_permitidos (list): Lista de roles permitidos (ej. ['admin', 'distribuidor']).

        Raises:
            ValidationError: Si el rol no está permitido.
        """
        if not usuario.has_role(roles_permitidos[0]) and not any(usuario.has_role(rol) for rol in roles_permitidos[1:]):
            logger.error(f"Rol inválido para {usuario.username}: {usuario.rol} no está en {roles_permitidos}")
            raise ValidationError(_("Rol de usuario no permitido para esta operación."))

    @staticmethod
    def validar_monto(monto):
        """
        Valida que el monto sea un Decimal positivo.

        Args:
            monto (Decimal): Monto a validar.

        Raises:
            ValidationError: Si el monto es inválido.
        """
        if not isinstance(monto, Decimal) or monto <= 0:
            logger.error(f"Monto inválido: {monto}")
            raise ValidationError(_("El monto debe ser mayor a cero."))

    @staticmethod
    def validar_moneda(moneda_codigo):
        """
        Valida que la moneda exista y esté activa.

        Args:
            moneda_codigo (str): Código de la moneda (ej. 'MXN').

        Returns:
            Moneda: Instancia del modelo Moneda.

        Raises:
            ValidationError: Si la moneda no existe.
        """
        try:
            moneda = Moneda.objects.get(codigo=moneda_codigo)
            return moneda
        except Moneda.DoesNotExist:
            logger.error(f"Moneda {moneda_codigo} no encontrada")
            raise ValidationError(_("Moneda no configurada."))

    @staticmethod
    def validar_rango_fechas(fecha_inicio, fecha_fin):
        """
        Valida que el rango de fechas sea lógico (inicio ≤ fin).

        Args:
            fecha_inicio (date): Fecha inicial.
            fecha_fin (date): Fecha final.

        Raises:
            ValidationError: Si el rango es inválido.
        """
        if fecha_inicio > fecha_fin:
            logger.error(f"Rango de fechas inválido: {fecha_inicio} > {fecha_fin}")
            raise ValidationError(_("La fecha de inicio no puede ser posterior a la fecha final."))

    @staticmethod
    def validar_relacion_distribuidor_vendedor(distribuidor, vendedor):
        """
        Valida que exista una relación activa entre distribuidor y vendedor.

        Args:
            distribuidor (User): Instancia del modelo User (distribuidor).
            vendedor (User): Instancia del modelo User (vendedor).

        Returns:
            DistribuidorVendedor: Instancia de la relación.

        Raises:
            ValidationError: Si no existe una relación activa.
        """
        try:
            relacion = DistribuidorVendedor.objects.get(
                distribuidor=distribuidor,
                vendedor=vendedor,
                activo=True
            )
            return relacion
        except DistribuidorVendedor.DoesNotExist:
            logger.error(f"No existe relación activa entre {distribuidor.username} y {vendedor.username}")
            raise ValidationError(_("No existe una relación activa entre el distribuidor y el vendedor."))

    @staticmethod
    def validar_permiso_transaccion(usuario, permiso):
        """
        Valida que el usuario tenga el permiso necesario para una transacción.

        Args:
            usuario (User): Instancia del modelo User.
            permiso (str): Permiso a validar (ej. 'can_assign_saldo').

        Raises:
            ValidationError: Si el usuario no tiene el permiso.
        """
        if not AuthService.has_permission(usuario, permiso):
            logger.error(f"Usuario {usuario.username} no tiene permiso: {permiso}")
            raise ValidationError(_("No tienes permiso para realizar esta operación."))