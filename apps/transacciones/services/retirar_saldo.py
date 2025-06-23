"""
Servicio para retirar saldo de un distribuidor en MexaRed.
Permite descontar saldo de forma segura, validando montos y evitando condiciones de carrera.
"""

from django.db import transaction
from apps.transacciones.models import Saldo, Transaccion
from apps.transacciones.enums import TipoTransaccion, EstadoTransaccion
from django.utils import timezone
from decimal import Decimal, InvalidOperation

class RetirarSaldoService:
    @staticmethod
    def retirar_saldo(distribuidor, monto, motivo="Retiro manual de saldo", registrar_transaccion=True):
        """
        Descuenta saldo del distribuidor de forma segura y controlada.

        Args:
            distribuidor: Objeto distribuidor al cual se le descontará el saldo.
            monto: Monto a retirar (positivo).
            motivo: Texto que explica el motivo del retiro.
            registrar_transaccion: Si True, se crea un registro en Transaccion.

        Returns:
            dict con éxito, saldo actualizado y mensaje.
        
        Raises:
            ValueError si el monto es inválido o hay saldo insuficiente.
        """

        try:
            monto = Decimal(monto)
        except (InvalidOperation, TypeError):
            raise ValueError("El monto proporcionado no es válido.")

        if monto <= 0:
            raise ValueError("El monto a retirar debe ser mayor a cero.")

        with transaction.atomic():
            saldo_obj = Saldo.objects.select_for_update().get(distribuidor=distribuidor)

            if saldo_obj.cantidad < monto:
                raise ValueError("Saldo insuficiente para realizar el retiro.")

            saldo_obj.cantidad -= monto
            saldo_obj.save()

            if registrar_transaccion:
                Transaccion.objects.create(
                    distribuidor=distribuidor,
                    monto=-monto,
                    tipo=TipoTransaccion.RETIRO,
                    estado=EstadoTransaccion.COMPLETADA,
                    descripcion=motivo,
                    fecha=timezone.now()
                )

            return {
                "exito": True,
                "saldo_actualizado": float(saldo_obj.cantidad),
                "mensaje": "Saldo retirado exitosamente."
            }
