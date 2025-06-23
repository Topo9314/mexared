"""
Excepciones personalizadas para el módulo de Wallet en MexaRed.
Define errores de negocio financiero críticos para garantizar seguridad operacional,
integridad financiera y cumplimiento con regulaciones internacionales (PCI DSS, SOC2).
Diseñado para ser invocado por services.py y proporcionar mensajes claros para auditorías y UI.
"""

from django.utils.translation import gettext_lazy as _

class WalletException(Exception):
    """
    Excepción base para todas las operaciones del módulo de Wallet.
    Sirve como raíz para excepciones específicas, permitiendo captura genérica en servicios.
    """
    def __init__(self, mensaje=_("Error en la operación de la billetera.")):
        self.mensaje = mensaje
        super().__init__(str(mensaje))

class SaldoInsuficienteException(WalletException):
    """
    Lanzada cuando el usuario intenta debitar más de su saldo disponible.
    Usada para proteger contra operaciones que comprometan la integridad financiera.
    """
    def __init__(self, mensaje=_("Saldo insuficiente para realizar la operación.")):
        super().__init__(mensaje)

class LimiteExcedidoException(WalletException):
    """
    Lanzada cuando una operación excede un límite permitido (por política interna).
    Ejemplo: transferencias que superan umbrales antifraude o regulatorios.
    """
    def __init__(self, mensaje=_("Límite de operación excedido.")):
        super().__init__(mensaje)

class OperacionNoPermitidaException(WalletException):
    """
    Lanzada cuando se intenta una operación no autorizada.
    Ejemplo: transferencias entre roles no permitidos (e.g., Vendedor → Distribuidor).
    """
    def __init__(self, mensaje=_("Operación no permitida para este usuario o flujo.")):
        super().__init__(mensaje)

class MovimientoInvalidoException(WalletException):
    """
    Lanzada cuando el tipo de movimiento financiero no es reconocido.
    Protege contra operaciones con tipos no definidos en TipoMovimiento (enums.py).
    """
    def __init__(self, mensaje=_("Tipo de movimiento financiero inválido.")):
        super().__init__(mensaje)

class BloqueoFondosInvalidoException(WalletException):
    """
    Lanzada cuando se intenta bloquear o desbloquear fondos de manera inválida.
    Ejemplo: intentar desbloquear más fondos de los bloqueados.
    """
    def __init__(self, mensaje=_("Operación de bloqueo o desbloqueo de fondos inválida.")):
        super().__init__(mensaje)

class ConciliacionInvalidaException(WalletException):
    """
    Lanzada cuando una operación de conciliación bancaria falla.
    Ejemplo: intentar conciliar un movimiento con datos inconsistentes.
    """
    def __init__(self, mensaje=_("Error en la conciliación bancaria.")):
        super().__init__(mensaje)

class ReferenciaExternaDuplicadaException(WalletException):
    """
    Lanzada cuando se detecta una referencia externa duplicada.
    Ejemplo: intentar procesar dos transacciones con el mismo ID de MercadoPago o Addinteli.
    """
    def __init__(self, mensaje=_("Referencia externa ya procesada.")):
        super().__init__(mensaje)