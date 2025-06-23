"""
Inicializador del paquete de servicios de transacciones para MexaRed.
Exposición controlada de funciones y clases clave para asignación, consulta y devolución de saldo.
"""

from .asignar_saldo import AsignarSaldoService
from .devolver_saldo import DevolverSaldoService
from .resumen_service import ResumenService
from .saldo_service import SaldoService
from .validaciones import Validaciones
from .transaccion_service import TransaccionService
from .retirar_saldo import RetirarSaldoService

# Exponer funciones clave (facilita imports externos y mantiene consistencia)
asignar_saldo_general = AsignarSaldoService.asignar_saldo_general
devolver_saldo_por_error = DevolverSaldoService.devolver_saldo_por_error
obtener_resumen_saldo = ResumenService.obtener_resumen_saldo
consultar_saldo = SaldoService.consultar_saldo
validar_monto = Validaciones.validar_monto
crear_transaccion = TransaccionService.crear_transaccion
retirar_saldo = RetirarSaldoService.retirar_saldo