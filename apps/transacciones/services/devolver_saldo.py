"""
Servicio especializado para la devolución de saldo en MexaRed.
Maneja reversiones de transacciones fallidas o anuladas, devolviendo el saldo al origen de forma segura y atómica.
Incluye auditoría detallada y preparación para integraciones futuras con APIs externas.
Diseñado para entornos internacionales, enfocado en México.
"""

import logging
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.users.models import User, UserChangeLog
from apps.users.services.auth_service import AuthService
from apps.transacciones.models import Transaccion, Moneda, MotivoTransaccion, AuditoriaTransaccion
from apps.transacciones.services.saldo_service import SaldoService
from apps.transacciones.services.validaciones import Validaciones
from apps.vendedores.models import DistribuidorVendedor

# Configuración de logging para monitoreo en producción
logger = logging.getLogger(__name__)

class DevolverSaldoService:
    """
    Servicio para manejar la devolución de saldo por transacciones fallidas o anuladas en MexaRed.
    Orquesta validaciones, reversiones de saldo, creación de transacciones de devolución y auditoría.
    """

    @staticmethod
    @transaction.atomic
    def devolver_saldo_por_error(transaccion_id: int, motivo: str, usuario_admin=None) -> dict:
        """
        Reversa una transacción fallida o errónea, devolviendo el saldo al origen (distribuidor o vendedor).

        Args:
            transaccion_id (int): ID de la transacción a revertir.
            motivo (str): Motivo por el cual se revierte.
            usuario_admin (User, optional): Usuario administrador que ejecuta la reversión (para auditoría).

        Returns:
            dict: Resultado con estado, mensaje, nuevo saldo, ID de transacción original y usuario origen.

        Raises:
            ValidationError: Si la transacción no es válida o no se puede revertir.
        """
        try:
            # 1. Validar existencia y estado de la transacción
            transaccion = Transaccion.objects.select_related('emisor', 'receptor', 'moneda', 'motivo', 'realizado_por')\
                            .get(id=transaccion_id)
            
            if transaccion.estado == 'CANCELADA':
                logger.error(f"Transacción {transaccion_id} ya está cancelada")
                raise ValidationError(_("La transacción ya está cancelada."))
            
            if transaccion.tipo not in ['ASIGNACION', 'CONSUMO_API']:
                logger.error(f"Tipo de transacción no reversible: {transaccion.tipo}")
                raise ValidationError(_("Este tipo de transacción no puede ser revertido."))

            # 2. Validar permisos del usuario administrador (si aplica)
            if usuario_admin:
                Validaciones.validar_permiso_transaccion(usuario_admin, 'can_assign_saldo')
                logger.debug(f"Reversión iniciada por administrador: {usuario_admin.username}")
            else:
                logger.debug(f"Reversión iniciada por sistema")

            # 3. Determinar origen del saldo (emisor)
            if not transaccion.emisor:
                logger.error(f"Transacción {transaccion_id} no tiene emisor definido")
                raise ValidationError(_("No se puede determinar el origen del saldo."))

            origen = transaccion.emisor
            Validaciones.validar_rol_usuario(origen, ['distribuidor', 'vendedor'])

            # 4. Obtener perfil para devolver saldo
            try:
                if origen.has_role('vendedor'):
                    perfil = DistribuidorVendedor.objects.get(vendedor=origen, activo=True)
                else:  # distribuidor
                    perfil = DistribuidorVendedor.objects.get(distribuidor=origen, activo=True)
            except DistribuidorVendedor.DoesNotExist:
                logger.error(f"Perfil DistribuidorVendedor no encontrado para {origen.username}")
                raise ValidationError(_("No se encontró un perfil activo para el usuario origen."))

            # 5. Validar monto y moneda
            monto = transaccion.monto
            Validaciones.validar_monto(monto)
            moneda = Validaciones.validar_moneda('MXN')
            if transaccion.moneda != moneda:
                logger.error(f"Moneda de transacción {transaccion.moneda.codigo} no coincide con MXN")
                raise ValidationError(_("La moneda de la transacción no es MXN."))

            # 6. Crear transacción de devolución
            motivo_obj = None
            if motivo:
                try:
                    motivo_obj = MotivoTransaccion.objects.get(codigo='DEVOLUCION_ERROR', activo=True)
                except MotivoTransaccion.DoesNotExist:
                    logger.warning("Motivo DEVOLUCION_ERROR no encontrado, usando motivo genérico")

            transaccion_devolucion = Transaccion.objects.create(
                tipo='DEVOLUCION',
                monto=monto,
                moneda=moneda,
                receptor=origen,
                motivo=motivo_obj,
                descripcion=f"Devolución por error en transacción {transaccion_id}: {motivo}",
                realizado_por=usuario_admin or transaccion.realizado_por,
                estado='EXITOSA'
            )

            # 7. Devolver saldo al origen
            perfil.saldo_disponible += monto
            perfil.save()

            # 8. Marcar transacción original como cancelada
            transaccion.estado = 'CANCELADA'
            transaccion.save()

            # 9. Registrar auditoría en UserChangeLog
            UserChangeLog.objects.create(
                user=origen,
                changed_by=usuario_admin,
                change_type='update',
                change_description=f"Devolución de saldo por transacción {transaccion_id}",
                details={
                    "transaccion_original_id": transaccion_id,
                    "transaccion_devolucion_id": transaccion_devolucion.id,
                    "monto": str(monto),
                    "moneda": moneda.codigo,
                    "motivo": motivo,
                    "admin": usuario_admin.username if usuario_admin else "Sistema"
                }
            )

            # 10. Registrar auditoría en AuditoriaTransaccion
            AuditoriaTransaccion.objects.create(
                transaccion=transaccion,
                tipo='CANCELACION',
                usuario=usuario_admin,
                detalles={
                    "motivo": motivo,
                    "transaccion_devolucion_id": transaccion_devolucion.id,
                    "monto_devuelto": str(monto)
                }
            )

            # 11. Preparar respuesta
            nuevo_saldo = SaldoService.consultar_saldo(origen)
            logger.info(f"Devolución exitosa para transacción {transaccion_id}: {monto} MXN devuelto a {origen.username}")
            return {
                "success": True,
                "mensaje": _("Devolución procesada exitosamente."),
                "nuevo_saldo": nuevo_saldo,
                "id_transaccion_original": transaccion_id,
                "usuario_origen": origen.username
            }

        except Transaccion.DoesNotExist:
            logger.error(f"Transacción no encontrada: {transaccion_id}")
            raise ValidationError(_("La transacción no existe."))
        except ValidationError as ve:
            logger.error(f"Error de validación al devolver saldo para transacción {transaccion_id}: {str(ve)}")
            raise
        except Exception as e:
            logger.error(f"Error inesperado al devolver saldo para transacción {transaccion_id}: {str(e)}")
            raise ValidationError(_("Error inesperado al procesar la devolución."))