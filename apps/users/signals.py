"""
Señales para el módulo de usuarios en MexaRed.
Gestiona la creación automática de billeteras, generación de códigos ID únicos y asignación automática de permisos.
Cumple con estándares internacionales (PCI DSS, SOC2, ISO 27001) y garantiza trazabilidad, seguridad y escalabilidad operativa.

Optimizado para rendimiento, manejo de errores avanzado y compatibilidad con módulos relacionados (wallet, transacciones, vendedores).
Incluye validación de permisos y recuperación automática en caso de fallos.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import Permission
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from decimal import Decimal
import logging

from .models import User, UserChangeLog, ROLE_CLIENTE, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR
from apps.wallet.models import Wallet

# Configuración avanzada de logging para auditoría empresarial
logger = logging.getLogger(__name__)

@receiver(post_save, sender=User)
def crear_wallet_y_asignar_permiso(sender, instance, created, **kwargs):
    """
    Signal optimizado para:
    - Crear billetera automáticamente para Distribuidores y Vendedores con jerarquía financiera.
    - Asignar permisos de acceso a billetera (view_dashboard) con manejo de fallos.
    Ejecuta operaciones dentro de transacción atómica para garantizar integridad y consistencia.

    Args:
        sender: Clase que dispara la señal (User).
        instance: Instancia del usuario creado o actualizado.
        created: Booleano indicando si el usuario es nuevo.
        **kwargs: Argumentos adicionales de la señal.

    Raises:
        ValidationError: Si hierarchy_root no está definido para Distribuidores o Vendedores.
        Exception: Para errores críticos que no puedan recuperarse.
    """
    if not created:
        logger.debug(f"Actualización de usuario {instance.username} (rol: {instance.rol}) - Sin acción requerida.")
        return

    if instance.rol not in [ROLE_DISTRIBUIDOR, ROLE_VENDEDOR]:
        logger.debug(f"No se requiere billetera ni permisos para {instance.username} (rol: {instance.rol}).")
        return

    try:
        with transaction.atomic():
            # Verificar y crear billetera si no existe
            if not Wallet.objects.filter(user=instance).exists():
                # Validar que hierarchy_root esté definido
                if not instance.hierarchy_root:
                    logger.error(f"No se puede crear billetera para {instance.username} (rol: {instance.rol}) sin hierarchy_root.")
                    raise ValidationError(
                        _("No se puede crear una billetera sin una raíz de jerarquía definida."),
                        code='missing_hierarchy_root'
                    )
                
                wallet = Wallet.objects.create(
                    user=instance,
                    hierarchy_root=instance.hierarchy_root,
                    balance=Decimal('0.00'),
                    blocked_balance=Decimal('0.00')
                )
                UserChangeLog.objects.create(
                    user=instance,
                    changed_by=None,  # Sistema
                    change_type='create',
                    change_description=_("Billetera creada automáticamente"),
                    details={
                        "wallet_id": str(wallet.id),
                        "rol": instance.rol,
                        "username": instance.username,
                        "hierarchy_root": instance.hierarchy_root.username if instance.hierarchy_root else None,
                        "timestamp": instance.date_joined.isoformat()
                    }
                )
                logger.info(f"Billetera creada para {instance.username} (rol: {instance.rol}, ID: {wallet.id}, hierarchy_root: {instance.hierarchy_root.username}).")

            # Asignar permiso view_dashboard con recuperación automática
            permiso_codename = 'view_dashboard'
            try:
                permiso = Permission.objects.get(codename=permiso_codename)
                if not instance.user_permissions.filter(id=permiso.id).exists():
                    instance.user_permissions.add(permiso)
                    UserChangeLog.objects.create(
                        user=instance,
                        changed_by=None,
                        change_type='update',
                        change_description=_("Permiso 'view_dashboard' asignado"),
                        details={
                            "permission_codename": permiso_codename,
                            "username": instance.username,
                            "rol": instance.rol
                        }
                    )
                    logger.info(f"Permiso '{permiso_codename}' asignado a {instance.username} (rol: {instance.rol}).")
            except Permission.DoesNotExist:
                logger.warning(f"Permiso '{permiso_codename}' no encontrado. Creando permiso dinámicamente...")
                try:
                    from django.contrib.contenttypes.models import ContentType
                    content_type = ContentType.objects.get_for_model(User)
                    Permission.objects.create(
                        codename=permiso_codename,
                        name=_("Puede ver el dashboard"),
                        content_type=content_type
                    )
                    instance.user_permissions.add(Permission.objects.get(codename=permiso_codename))
                    UserChangeLog.objects.create(
                        user=instance,
                        changed_by=None,
                        change_type='update',
                        change_description=_("Permiso 'view_dashboard' creado y asignado dinámicamente"),
                        details={
                            "permission_codename": permiso_codename,
                            "username": instance.username,
                            "rol": instance.rol
                        }
                    )
                    logger.info(f"Permiso '{permiso_codename}' creado y asignado a {instance.username}.")
                except Exception as e:
                    logger.error(f"No se pudo crear el permiso dinámicamente: {str(e)}")
                    raise

    except Exception as e:
        logger.exception(f"Error crítico al procesar señal para {instance.username} (rol: {instance.rol}): {str(e)}")
        raise

@receiver(post_save, sender=User)
def asignar_codigo_id(sender, instance, created, **kwargs):
    """
    Signal optimizado para generar códigos ID únicos basados en el rol del usuario.
    - Clientes: CL000001
    - Distribuidores: D0001
    - Vendedores: V00001
    - Otros: U + PK
    Utiliza transacciones atómicas para consistencia.

    Args:
        sender: Clase que dispara la señal (User).
        instance: Instancia del usuario creado o actualizado.
        created: Booleano indicando si el usuario es nuevo.
        **kwargs: Argumentos adicionales de la señal.

    Raises:
        Exception: Para errores críticos que no puedan recuperarse.
    """
    if not created or instance.codigo_id:
        logger.debug(f"Usuario {instance.username} (rol: {instance.rol}) no requiere nuevo código ID.")
        return

    try:
        with transaction.atomic():
            prefix_map = {
                ROLE_CLIENTE: 'CL',
                ROLE_DISTRIBUIDOR: 'D',
                ROLE_VENDEDOR: 'V',
            }
            prefix = prefix_map.get(instance.rol, 'U')

            # Contar usuarios activos con el mismo rol para generar ID único
            total_users_with_role = User.objects.filter(
                rol=instance.rol,
                deleted_at__isnull=True
            ).select_for_update().count()

            # Formatear ID según rol
            if instance.rol == ROLE_CLIENTE:
                formatted_id = f"{prefix}{total_users_with_role + 1:06d}"  # CL000001
            elif instance.rol == ROLE_DISTRIBUIDOR:
                formatted_id = f"{prefix}{total_users_with_role + 1:04d}"  # D0001
            elif instance.rol == ROLE_VENDEDOR:
                formatted_id = f"{prefix}{total_users_with_role + 1:05d}"  # V00001
            else:
                formatted_id = f"{prefix}{instance.pk:06d}"  # U000001

            # Actualizar código ID de forma segura
            User.objects.filter(pk=instance.pk).update(codigo_id=formatted_id)

            # Registrar auditoría
            UserChangeLog.objects.create(
                user=instance,
                changed_by=None,
                change_type='update',
                change_description=_("Código ID generado automáticamente"),
                details={
                    "codigo_id": formatted_id,
                    "rol": instance.rol,
                    "username": instance.username,
                    "total_users_with_role": total_users_with_role
                }
            )
            logger.info(f"Código ID {formatted_id} generado para {instance.username} (rol: {instance.rol}).")

    except Exception as e:
        logger.exception(f"Error al generar código ID para {instance.username} (rol: {instance.rol}): {str(e)}")
        raise