from enum import Enum

class TipoTransaccion(Enum):
    ASIGNACION = 'Asignación'
    RETIRO = 'Retiro'
    DEVOLUCION = 'Devolución'

class EstadoTransaccion(Enum):
    PENDIENTE = 'Pendiente'
    COMPLETADA = 'Completada'
    FALLIDA = 'Fallida'
