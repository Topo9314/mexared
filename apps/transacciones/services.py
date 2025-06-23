"""
Servicios para la gestión de transacciones financieras en MexaRed.
Proporciona una lógica empresarial centralizada, desacoplada y auditable para procesar transacciones,
gestionar saldos y soportar integraciones externas (APIs, blockchain, sistemas bancarios).
"""

from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from decimal import Decimal
import uuid

from apps.transacciones.models import Transaccion, HistorialSaldo, Moneda, MotivoTransaccion

from apps.vendedores.models import DistribuidorVendedor

class TransaccionService:
    """
    Lógica centralizada para procesar transacciones financieras en MexaRed.
    Clase desacoplada con servicios reutilizables, auditables y preparados para escalar.
    Soporta multi-moneda, auditoría completa y validaciones estrictas.
    """
    def __init__(self, *, tipo, monto, moneda, emisor=None, receptor=None, motivo=None,
                 descripcion="", tasa_cambio=None, referencia_externa=None, realizado_por=None):
        """
        Inicializa el servicio de transacción con los parámetros necesarios.
        
        Args:
            tipo (str): Tipo de transacción (e.g., ASIGNACION, CONSUMO_API).
            monto (Decimal): Monto de la transacción.
            moneda (Moneda): Objeto Moneda para la transacción.
            emisor (User, optional): Usuario que inicia la transacción.
            receptor (User, optional): Usuario que recibe la transacción.
            motivo (MotivoTransaccion, optional): Motivo específico de la transacción.
            descripcion (str): Descripción adicional.
            tasa_cambio (Decimal, optional): Tasa de cambio si aplica.
            referencia_externa (str, optional): Identificador externo (e.g., API de pago).
            realizado_por (User, optional): Usuario que ejecuta la transacción.
        """
        self.tipo = tipo
        self.monto = Decimal(str(monto)) if monto else Decimal('0.00')
        self.moneda = moneda
        self.emisor = emisor
        self.receptor = receptor
        self.motivo = motivo
        self.descripcion = descripcion
        self.tasa_cambio = Decimal(str(tasa_cambio)) if tasa_cambio else None
        self.referencia_externa = referencia_externa
        self.realizado_por = realizado_por

    def _validar(self):
        """
        Valida los parámetros de la transacción antes de procesarla.
        """
        if self.monto <= 0:
            raise ValidationError(_("El monto debe ser mayor a cero."))
        if not isinstance(self.moneda, Moneda):
            raise ValidationError(_("Se requiere un objeto Moneda válido."))
        if self.emisor and self.emisor.rol not in ['admin', 'distribuidor']:
            raise ValidationError(_("El emisor debe ser un administrador o distribuidor."))
        if self.receptor and self.receptor.rol not in ['distribuidor', 'vendedor']:
            raise ValidationError(_("El receptor debe ser un distribuidor o vendedor."))
        if self.emisor and self.receptor and self.emisor == self.receptor:
            raise ValidationError(_("El emisor y el receptor no pueden ser el mismo usuario."))
        if self.tipo not in [choice[0] for choice in Transaccion.TIPO_CHOICES]:
            raise ValidationError(_("Tipo de transacción inválido."))
        if self.motivo and not isinstance(self.motivo, MotivoTransaccion):
            raise ValidationError(_("Se requiere un objeto MotivoTransaccion válido."))
        if self.tasa_cambio and self.tasa_cambio <= 0:
            raise ValidationError(_("La tasa de cambio debe ser mayor a cero."))
        if self.realizado_por and self.realizado_por.rol not in ['admin', 'distribuidor']:
            raise ValidationError(_("Solo administradores o distribuidores pueden realizar transacciones."))
        if self.tipo in ['ASIGNACION', 'DEVOLUCION'] and not self.receptor:
            raise ValidationError(_("Se requiere un receptor para asignaciones o devoluciones."))
        if self.tipo == 'RETIRO' and not self.emisor:
            raise ValidationError(_("Se requiere un emisor para retiros."))

    @transaction.atomic
    def procesar(self):
        """
        Procesa la transacción, crea el registro y actualiza historiales de saldo.
        Ejecuta todo dentro de una transacción atómica para garantizar consistencia.

        Returns:
            Transaccion: Objeto de la transacción creada.
        
        Raises:
            ValidationError: Si la transacción no es válida o el saldo es insuficiente.
        """
        self._validar()

        # Crear la transacción
        transaccion = Transaccion.objects.create(
            uuid=uuid.uuid4(),
            tipo=self.tipo,
            monto=self.monto,
            moneda=self.moneda,
            emisor=self.emisor,
            receptor=self.receptor,
            motivo=self.motivo,
            descripcion=self.descripcion,
            tasa_cambio=self.tasa_cambio,
            referencia_externa=self.referencia_externa,
            realizado_por=self.realizado_por,
            estado='EXITOSA'
        )

        # Registrar historial de saldo
        self._registrar_historial(transaccion)

        return transaccion

    def _registrar_historial(self, transaccion):
        """
        Registra el historial de saldo para emisor y receptor según el tipo de transacción.
        
        Args:
            transaccion (Transaccion): Transacción asociada al historial.
        """
        if self.receptor and self.tipo in ['ASIGNACION', 'DEVOLUCION']:
            self._crear_historial(self.receptor, transaccion, incremento=True)
        if self.emisor and self.tipo in ['RETIRO', 'CONSUMO_API', 'AJUSTE_MANUAL']:
            self._crear_historial(self.emisor, transaccion, incremento=False)
        if self.emisor and self.receptor and self.tipo == 'ASIGNACION':
            self._crear_historial(self.emisor, transaccion, incremento=False)

    def _crear_historial(self, usuario, transaccion, incremento=True):
        """
        Crea un registro de historial de saldo para un usuario específico.
        
        Args:
            usuario (User): Usuario cuyo saldo se actualiza.
            transaccion (Transaccion): Transacción asociada.
            incremento (bool): Indica si el monto incrementa o decrementa el saldo.
        
        Raises:
            ValidationError: Si el saldo es insuficiente o la operación no es válida.
        """
        # Obtener el perfil de saldo según el rol
        if usuario.rol == 'distribuidor':
            try:
                perfil = usuario.perfil_distribuidor_rel
                saldo_actual = perfil.saldo_actual
            except PerfilDistribuidor.DoesNotExist:
                raise ValidationError(_("El distribuidor no tiene un perfil asociado."))
        elif usuario.rol == 'vendedor':
            try:
                relacion = DistribuidorVendedor.objects.get(vendedor=usuario, activo=True)
                saldo_actual = relacion.saldo_disponible
            except DistribuidorVendedor.DoesNotExist:
                raise ValidationError(_("El vendedor no tiene una relación activa."))
        else:
            raise ValidationError(_("El usuario debe ser un distribuidor o vendedor."))

        # Calcular nuevo saldo
        nuevo_saldo = saldo_actual + self.monto if incremento else saldo_actual - self.monto

        if nuevo_saldo < 0:
            raise ValidationError(_("Saldo insuficiente para esta operación."))

        # Crear historial
        HistorialSaldo.objects.create(
            usuario=usuario,
            saldo_antes=saldo_actual,
            saldo_despues=nuevo_saldo,
            transaccion=transaccion
        )

        # Actualizar saldo
        if usuario.rol == 'distribuidor':
            perfil.saldo_actual = nuevo_saldo
            perfil.save(update_fields=['saldo_actual'])
        else:
            relacion.saldo_disponible = nuevo_saldo
            relacion.save(update_fields=['saldo_disponible'])

# ============================
# 🔹 FUNCIONES ESPECIALIZADAS
# ============================

@transaction.atomic
def asignar_saldo(distribuidor, vendedor, monto, moneda, realizado_por, motivo=None, descripcion="Asignación de saldo"):
    """
    Asigna saldo de un distribuidor a un vendedor.
    
    Args:
        distribuidor (User): Distribuidor que asigna el saldo.
        vendedor (User): Vendedor que recibe el saldo.
        monto (Decimal): Monto a asignar.
        moneda (Moneda): Moneda de la transacción.
        realizado_por (User): Usuario que realiza la operación.
        motivo (MotivoTransaccion, optional): Motivo de la asignación.
        descripcion (str): Descripción de la operación.
    
    Returns:
        Transaccion: Transacción creada.
    
    Raises:
        ValidationError: Si los parámetros no son válidos o la relación no existe.
    """
    if not DistribuidorVendedor.objects.filter(distribuidor=distribuidor, vendedor=vendedor, activo=True).exists():
        raise ValidationError(_("No existe una relación activa entre el distribuidor y el vendedor."))
    
    return TransaccionService(
        tipo='ASIGNACION',
        monto=monto,
        moneda=moneda,
        emisor=distribuidor,
        receptor=vendedor,
        motivo=motivo,
        descripcion=descripcion,
        realizado_por=realizado_por
    ).procesar()

@transaction.atomic
def retirar_saldo(usuario, monto, moneda, realizado_por, motivo=None, descripcion="Retiro de saldo"):
    """
    Retira saldo de un usuario (distribuidor o vendedor).
    
    Args:
        usuario (User): Usuario cuyo saldo se retira.
        monto (Decimal): Monto a retirar.
        moneda (Moneda): Moneda de la transacción.
        realizado_por (User): Usuario que realiza la operación.
        motivo (MotivoTransaccion, optional): Motivo del retiro.
        descripcion (str): Descripción de la operación.
    
    Returns:
        Transaccion: Transacción creada.
    
    Raises:
        ValidationError: Si los parámetros no son válidos.
    """
    return TransaccionService(
        tipo='RETIRO',
        monto=monto,
        moneda=moneda,
        emisor=usuario,
        motivo=motivo,
        descripcion=descripcion,
        realizado_por=realizado_por
    ).procesar()

@transaction.atomic
def devolver_saldo_por_error(receptor, monto, moneda, realizado_por, motivo=None, descripcion="Devolución por error"):
    """
    Realiza una devolución de saldo a un usuario por error.
    
    Args:
        receptor (User): Usuario que recibe la devolución.
        monto (Decimal): Monto a devolver.
        moneda (Moneda): Moneda de la transacción.
        realizado_por (User): Usuario que realiza la operación.
        motivo (MotivoTransaccion, optional): Motivo de la devolución.
        descripcion (str): Descripción de la operación.
    
    Returns:
        Transaccion: Transacción creada.
    
    Raises:
        ValidationError: Si los parámetros no son válidos.
    """
    return TransaccionService(
        tipo='DEVOLUCION',
        monto=monto,
        moneda=moneda,
        receptor=receptor,
        motivo=motivo,
        descripcion=descripcion,
        realizado_por=realizado_por
    ).procesar()

@transaction.atomic
def consumir_saldo_api(usuario, monto, moneda, referencia_externa, realizado_por=None, motivo=None, descripcion="Consumo vía API"):
    """
    Procesa un consumo de saldo a través de una API externa.
    
    Args:
        usuario (User): Usuario cuyo saldo se consume.
        monto (Decimal): Monto a consumir.
        moneda (Moneda): Moneda de la transacción.
        referencia_externa (str): Identificador de la API externa.
        realizado_por (User, optional): Usuario que realiza la operación.
        motivo (MotivoTransaccion, optional): Motivo del consumo.
        descripcion (str): Descripción de la operación.
    
    Returns:
        Transaccion: Transacción creada.
    
    Raises:
        ValidationError: Si los parámetros no son válidos.
    """
    return TransaccionService(
        tipo='CONSUMO_API',
        monto=monto,
        moneda=moneda,
        emisor=usuario,
        referencia_externa=referencia_externa,
        motivo=motivo,
        descripcion=descripcion,
        realizado_por=realizado_por
    ).procesar()