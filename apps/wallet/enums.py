"""
Enumeradores para el módulo de Wallet en MexaRed.
Define los tipos de movimientos financieros soportados por el sistema.
Diseñado para ser robusto, traducible y compatible con auditorías financieras internacionales (PCI DSS, SOC2).
Proporciona validaciones estrictas y soporte para UI/admin en múltiples idiomas.
"""

from enum import Enum
from django.utils.translation import gettext_lazy as _

class TipoMovimiento(Enum):
    """
    Enumerador que define los tipos de movimientos financieros para WalletMovement.
    Las claves (name) se almacenan en la base de datos (WalletMovement.tipo).
    Los valores (value) son textos legibles para interfaces de usuario y auditorías.
    """
    CREDITO = _("Crédito")
    DEBITO = _("Débito")
    AJUSTE_POSITIVO = _("Ajuste Positivo")
    AJUSTE_NEGATIVO = _("Ajuste Negativo")
    TRANSFERENCIA_INTERNA = _("Transferencia Interna")
    BLOQUEO = _("Bloqueo de Fondos")
    DESBLOQUEO = _("Desbloqueo de Fondos")
    REEMBOLSO = _("Reembolso")
    RETIRO = _("Retiro")
    COMPRA_EXTERNA = _("Compra Externa (MercadoPago)")
    CARGO_EXTERNO = _("Cargo Externo (API, Addinteli)")
    BONO_PROMOCIONAL = _("Bono Promocional")
    AJUSTE_MANUAL = _("Ajuste Manual Admin")
    CONCILIACION_BANCARIA = _("Conciliación Bancaria")

    @classmethod
    def values(cls):
        """
        Devuelve una lista de los nombres (claves) de los tipos de movimiento.
        Utilizado para validaciones en WalletMovement.clean().
        """
        return [item.name for item in cls]

    @classmethod
    def choices(cls):
        """
        Devuelve una lista de tuplas (name, value) para usar en campos CharField de Django.
        Convierte explícitamente el valor a str para garantizar compatibilidad con Django ORM.
        Facilita la integración con formularios, admin y serializadores.
        """
        return [(item.name, str(item.value)) for item in cls]


