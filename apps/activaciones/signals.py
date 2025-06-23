"""
signals.py - Señales para auditoría y automatización en el módulo de activaciones de MexaRed.
Registra eventos clave (creación, cambios críticos) y prepara automatizaciones futuras (notificaciones, alertas).
Optimizado para trazabilidad regulatoria, seguridad y escalabilidad en estándares telco internacionales.
"""

import logging
import json
import hashlib
from typing import Optional
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _
from django.utils.timezone import now
from django.conf import settings
from .models import Activacion, AuditLog
from apps.users.models import User
from threading import local

# Configuración de logging para auditoría
logger = logging.getLogger(__name__)

# Almacenamiento local para capturar contexto (e.g., IP, usuario actual)
_request_local = local()

def set_request_context(request):
    """
    Establece el contexto de la solicitud actual (IP, usuario) para las señales.
    Llamar desde vistas o middleware.
    """
    _request_local.request = request

def get_request_context() -> dict:
    """
    Obtiene el contexto de la solicitud actual (IP, usuario).
    """
    request = getattr(_request_local, 'request', None)
    if request:
        return {
            'ip_address': request.META.get('REMOTE_ADDR', 'unknown'),
            'user_agent': request.META.get('HTTP_USER_AGENT', 'unknown'),
            'user': request.user if request.user.is_authenticated else None,
        }
    return {
        'ip_address': '127.0.0.1',
        'user_agent': 'unknown',
        'user': None,
    }

@receiver(post_save, sender=Activacion)
def registrar_creacion_activacion(sender, instance: Activacion, created: bool, **kwargs):
    """
    Registra la creación de una activación en AuditLog.
    Captura contexto de solicitud (IP, user_agent) y genera hash para trazabilidad.
    """
    if created:
        context = get_request_context()
        ip_address = context['ip_address']
        user_agent = context['user_agent']
        user = instance.usuario_solicita or context['user']

        audit_details = {
            'mensaje': str(_('Activación creada')),
            'iccid': instance.iccid,
            'tipo_activacion': instance.tipo_activacion,
            'tipo_producto': instance.tipo_producto,
            'usuario_solicita': instance.usuario_solicita.username if instance.usuario_solicita else None,
            'distribuidor_asignado': instance.distribuidor_asignado.username if instance.distribuidor_asignado else None,
            'estado': instance.estado,
            'ip_address': ip_address,
            'user_agent': user_agent,
        }
        audit_hash = _generate_audit_hash(audit_details)

        AuditLog.objects.create(
            usuario=user,
            accion='CREACION_ACTIVACION',
            entidad='Activacion',
            entidad_id=str(instance.id),
            detalles=audit_details,
            ip_address=ip_address,
            audit_hash=audit_hash
        )

        logger.info(
            f"[CREACION_ACTIVACION] Activación ID={instance.id}, ICCID={instance.iccid}, "
            f"Usuario={user.username if user else 'anonymous'}, IP={ip_address}"
        )

        # Futuro: Enviar notificación (email, Slack, webhook)
        # _send_notification('activacion_creada', instance, audit_details)

@receiver(pre_save, sender=Activacion)
def registrar_cambios_importantes(sender, instance: Activacion, **kwargs):
    """
    Detecta cambios en campos críticos (estado, iccid, distribuidor, precios) antes de guardar.
    Registra los cambios en AuditLog con contexto completo y hash.
    """
    if not instance.pk:  # Ignorar creaciones
        return

    try:
        previous = Activacion.objects.get(pk=instance.pk)
    except Activacion.DoesNotExist:
        return

    context = get_request_context()
    ip_address = context['ip_address']
    user_agent = context['user_agent']
    user = instance.usuario_solicita or context['user']

    cambios = {}
    campos_a_monitorear = [
        'estado',
        'iccid',
        'distribuidor_asignado_id',
        'precio_costo',
        'precio_final',
        'ganancia_calculada',
        'numero_asignado',
        'tipo_activacion',
        'tipo_producto',
    ]

    for campo in campos_a_monitorear:
        valor_anterior = getattr(previous, campo)
        valor_nuevo = getattr(instance, campo)
        if valor_anterior != valor_nuevo:
            cambios[campo] = {
                'anterior': str(valor_anterior),
                'nuevo': str(valor_nuevo)
            }

    if cambios:
        audit_details = {
            'mensaje': str(_('Cambios detectados en activación')),
            'cambios': cambios,
            'iccid': instance.iccid,
            'usuario_solicita': instance.usuario_solicita.username if instance.usuario_solicita else None,
            'ip_address': ip_address,
            'user_agent': user_agent,
        }
        audit_hash = _generate_audit_hash(audit_details)

        AuditLog.objects.create(
            usuario=user,
            accion='CAMBIO_ACTIVACION',
            entidad='Activacion',
            entidad_id=str(instance.id),
            detalles=audit_details,
            ip_address=ip_address,
            audit_hash=audit_hash
        )

        logger.warning(
            f"[CAMBIO_ACTIVACION] Activación ID={instance.id}, ICCID={instance.iccid}, "
            f"Cambios={json.dumps(cambios, ensure_ascii=False)}, "
            f"Usuario={user.username if user else 'anonymous'}, IP={ip_address}"
        )

        # Futuro: Disparar alerta si el cambio es crítico (e.g., estado a 'fallida')
        # if 'estado' in cambios and cambios['estado']['nuevo'] == 'fallida':
        #     _send_alert('activacion_fallida', instance, cambios)

def _generate_audit_hash(details: dict) -> str:
    """
    Genera un hash SHA256 de los detalles de auditoría para verificación regulatoria.
    """
    details_str = json.dumps(details, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(details_str.encode('utf-8')).hexdigest()

# Futuro: Implementar funciones para notificaciones y alertas
# def _send_notification(event_type: str, instance: Activacion, details: dict):
#     # Ejemplo: Enviar email, Slack, o webhook
#     pass
#
# def _send_alert(event_type: str, instance: Activacion, changes: dict):
#     # Ejemplo: Alerta crítica a sistema externo
#     pass