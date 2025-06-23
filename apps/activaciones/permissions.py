"""
permissions.py - Permisos personalizados para el módulo de activaciones en MexaRed.
Define autorizaciones granulares según roles (Admin, Distribuidor, Vendedor) y acciones.
Optimizado para seguridad, trazabilidad, rendimiento y cumplimiento con estándards telco internacionales.
Preparado para ampliaciones como multitenencia, alertas y límites regionales.
"""

import logging
from rest_framework import permissions
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from apps.users.models import User, ROLE_ADMIN, ROLE_DISTRIBUTOR, ROLE_SELLER
from apps.vendedores.models import DistribuidorVendedor
from apps.activaciones.models import AuditLog

# Configuración de logging para auditoría de permisos
logger = logging.getLogger(__name__)

class ActivacionPermission(permissions.BasePermission):
    """
    Permisos personalizados para el módulo de activaciones.
    Controla acceso a acciones (crear, listar, ver, exportar, portabilidad) según rol y relación con la activación.
    Registra intentos de acceso denegado en AuditLog para trazabilidad regulatoria.
    Soporta futuras ampliaciones como multitenencia y límites regionales.
    """

    def has_permission(self, request, view):
        """
        Verifica permisos a nivel de vista para acciones generales.
        - Autenticación requerida.
        - Diferencia entre acciones de creación, listado, personalizadas y modificaciones.
        """
        user = request.user
        if not user or not user.is_authenticated:
            self._log_denied_access(user, request, view, reason="No autenticado")
            return False

        # Denegar explícitamente acciones de modificación o eliminación
        if view.action in ['update', 'partial_update', 'destroy']:
            self._log_denied_access(user, request, view, reason="Acción de modificación o eliminación no permitida")
            return False

        # Acciones personalizadas (exportar, ver portabilidad): solo Admin y Distribuidor
        if view.action in ['exportar_activaciones', 'detalle_portabilidad']:
            allowed = user.rol in [ROLE_ADMIN, ROLE_DISTRIBUTOR]
            if not allowed:
                self._log_denied_access(user, request, view, reason="Rol no permitido para acción personalizada")
            return allowed

        # Creación: Admin, Distribuidor, Vendedor
        if view.action == 'create':
            allowed = user.rol in [ROLE_ADMIN, ROLE_DISTRIBUTOR, ROLE_SELLER]
            if not allowed:
                self._log_denied_access(user, request, view, reason="Rol no permitido para crear activaciones")
            return allowed

        # Listado y detalle: todos los roles autenticados pueden listar/ver (filtrado por get_queryset)
        if view.action in ['list', 'retrieve']:
            return True

        # Otras acciones no definidas: denegar por defecto
        self._log_denied_access(user, request, view, reason="Acción no soportada")
        return False

    def has_object_permission(self, request, view, obj):
        """
        Verifica permisos a nivel de objeto para acciones específicas sobre una activación.
        - Admin: acceso completo.
        - Distribuidor: acceso a sus activaciones o las de sus vendedores.
        - Vendedor: acceso solo a sus propias activaciones.
        """
        user = request.user
        if not user or not user.is_authenticated:
            self._log_denied_access(user, request, view, obj=obj, reason="No autenticado")
            return False

        # Denegar explícitamente modificaciones o eliminaciones
        if view.action in ['update', 'partial_update', 'destroy']:
            self._log_denied_access(user, request, view, obj=obj, reason="Acción de modificación o eliminación no permitida")
            return False

        # Admin tiene acceso completo
        if user.rol == ROLE_ADMIN:
            return True

        # Distribuidor: activaciones asignadas o de sus vendedores
        if user.rol == ROLE_DISTRIBUTOR:
            # Verifica si la activación está asignada al distribuidor
            if obj.distribuidor_asignado == user:
                return True
            # Verifica si el usuario solicitante es un vendedor del distribuidor
            if DistribuidorVendedor.objects.filter(vendedor=obj.usuario_solicita, distribuidor=user).exists():
                return True
            self._log_denied_access(user, request, view, obj=obj, reason="No es distribuidor del vendedor")
            return False

        # Vendedor: solo sus propias activaciones
        if user.rol == ROLE_SELLER:
            allowed = obj.usuario_solicita == user
            if not allowed:
                self._log_denied_access(user, request, view, obj=obj, reason="No es el solicitante")
            return allowed

        # Rol no permitido
        self._log_denied_access(user, request, view, obj=obj, reason="Rol no permitido")
        return False

    @staticmethod
    def _log_denied_access(user, request, view, obj=None, reason="Acceso denegado"):
        """
        Registra intentos de acceso denegado en AuditLog y logger para trazabilidad.
        """
        user_id = user.id if user and user.is_authenticated else None
        username = user.username if user and user.is_authenticated else 'anonymous'
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
        action = view.action if hasattr(view, 'action') else 'unknown'
        obj_id = str(obj.id) if obj else None

        audit_details = {
            'action': action,
            'reason': reason,
            'client_ip': client_ip,
            'user_agent': request.META.get('HTTP_USER_AGENT', 'unknown'),
            'path': request.path,
            'method': request.method,
        }
        if obj_id:
            audit_details['activacion_id'] = obj_id
            audit_details['iccid'] = getattr(obj, 'iccid', 'unknown')

        AuditLog.objects.create(
            usuario_id=user_id,
            accion='ACCESO_DENEGADO',
            entidad='Activacion',
            entidad_id=obj_id,
            detalles=audit_details,
            ip_address=client_ip
        )

        logger.warning(
            f"Acceso denegado: Usuario={username}, Acción={action}, "
            f"Objeto={obj_id or 'N/A'}, Razón={reason}, IP={client_ip}"
        )

        # Futuro: Disparar alerta si hay múltiples accesos denegados
        # Ejemplo: Integrar con sistema de alertas (e.g., enviar a Slack o email)
        # self._trigger_alert_if_needed(user_id, client_ip, action, reason)