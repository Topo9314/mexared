"""
Señales para la app transacciones en MexaRed.
Maneja acciones automáticas y seguras al crear, actualizar o validar objetos de transacción y historial.
Proporciona auditoría detallada, validaciones críticas y hooks para integraciones externas (APIs, notificaciones).
"""

import logging
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils.timezone import now
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.transacciones.models import Transaccion, HistorialSaldo
from apps.users.models import User

# Configuración del logger para auditoría profesional
logger = logging.getLogger(__name__)

@receiver(pre_save, sender=Transaccion)
def validar_transaccion_antes_de_guardar(sender, instance, **kwargs):
    """
    Valida la transacción antes de guardarla para proteger la integridad de los datos.
    
    Args:
        sender: Clase del modelo (Transaccion).
        instance: Instancia de la transacción que se está guardando.
        kwargs: Argumentos adicionales.
    
    Raises:
        ValidationError: Si la transacción no cumple con las validaciones críticas.
    """
    if instance.monto <= 0:
        raise ValidationError(_("El monto debe ser mayor a cero para registrar la transacción."))
    
    # Validar roles de los usuarios involucrados
    if instance.emisor and instance.emisor.rol not in ['admin', 'distribuidor']:
        raise ValidationError(_("El emisor debe ser un administrador o distribuidor."))
    if instance.receptor and instance.receptor.rol not in ['distribuidor', 'vendedor']:
        raise ValidationError(_("El receptor debe ser un distribuidor o vendedor."))
    
    # Verificar que emisor y receptor no sean el mismo usuario
    if instance.emisor and instance.receptor and instance.emisor == instance.receptor:
        raise ValidationError(_("El emisor y el receptor no pueden ser el mismo usuario."))

@receiver(post_save, sender=Transaccion)
def log_transaccion_creada(sender, instance, created, **kwargs):
    """
    Registra un log detallado cuando se crea una nueva transacción.
    
    Args:
        sender: Clase del modelo (Transaccion).
        instance: Instancia de la transacción creada o actualizada.
        created: bool, indica si la transacción fue creada.
        kwargs: Argumentos adicionales.
    """
    if created:
        logger.info(
            f"[{now()}] Nueva transacción registrada: {instance.get_tipo_display()} | "
            f"Monto: {instance.monto} {instance.moneda.codigo} | "
            f"Emisor: {instance.emisor.username if instance.emisor else 'N/A'} | "
            f"Receptor: {instance.receptor.username if instance.receptor else 'N/A'} | "
            f"Estado: {instance.get_estado_display()} | UUID: {instance.uuid}"
        )

@receiver(post_save, sender=Transaccion)
def notificar_api_bancaria(sender, instance, created, **kwargs):
    """
    Hook para notificar a sistemas externos (e.g., APIs bancarias) cuando se crea una transacción
    con referencia externa.
    
    Args:
        sender: Clase del modelo (Transaccion).
        instance: Instancia de la transacción creada o actualizada.
        created: bool, indica si la transacción fue creada.
        kwargs: Argumentos adicionales.
    """
    if created and instance.referencia_externa:
        logger.info(
            f"[{now()}] Transacción {instance.uuid} lista para notificación externa: "
            f"Referencia: {instance.referencia_externa}"
        )
        # Placeholder para integración futura con APIs externas
        # Ejemplo:
        # try:
        #     response = requests.post(
        #         'https://api.banco.com/notificar',
        #         json={'transaccion_id': str(instance.uuid), 'referencia': instance.referencia_externa}
        #     )
        #     logger.info(f"Notificación enviada: {response.status_code}")
        # except Exception as e:
        #     logger.error(f"Error al notificar API bancaria: {str(e)}")

@receiver(post_save, sender=HistorialSaldo)
def auditar_cambios_saldo(sender, instance, created, **kwargs):
    """
    Registra un log detallado cuando se crea un nuevo historial de saldo.
    
    Args:
        sender: Clase del modelo (HistorialSaldo).
        instance: Instancia del historial de saldo creada.
        created: bool, indica si el historial fue creado.
        kwargs: Argumentos adicionales.
    """
    if created:
        logger.info(
            f"[{now()}] Cambio de saldo registrado: "
            f"Usuario: {instance.usuario.username} | "
            f"Antes: {instance.saldo_antes} -> Después: {instance.saldo_despues} | "
            f"Transacción: {instance.transaccion.uuid} | "
            f"Tipo: {instance.transaccion.get_tipo_display()}"
        )