"""
Señales para el módulo Wallet en MexaRed.
Automatiza la creación de billeteras, sincronización de jerarquías, y auditoría de eventos.
Diseñado para garantizar integridad financiera, trazabilidad, y cumplimiento con PCI DSS, SOC2, ISO 27001.
"""

import logging
from decimal import Decimal
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from apps.users.models import User, UserChangeLog, ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR, ROLE_CLIENTE
from apps.wallet.models import Wallet

# Configuración de logging para auditoría en producción
logger = logging.getLogger(__name__)

@receiver(post_save, sender=User)
def manage_wallet_and_codigo_id(sender, instance, created, **kwargs):
    """
    Signal para gestionar la creación de billeteras, códigos ID únicos, y sincronización de jerarquías.
    Ejecuta operaciones dentro de una transacción atómica para garantizar integridad.

    Args:
        sender: Clase que dispara la señal (User).
        instance: Instancia del usuario creado o actualizado.
        created: Indica si el usuario fue recién creado.
        kwargs: Argumentos adicionales de la señal (e.g., update_fields).

    Behavior:
        - Para usuarios nuevos: Crea billetera (si aplica), asigna hierarchy_root, genera código ID.
        - Para usuarios existentes: Actualiza hierarchy_root si cambia la jerarquía.
        - Registra auditoría en UserChangeLog y logs para trazabilidad.
        - Valida que hierarchy_root no sea None para roles que lo requieren.
    """
    try:
        with transaction.atomic():
            # Determinar hierarchy_root según rol y relaciones
            hierarchy_root = None
            if instance.rol == ROLE_DISTRIBUIDOR:
                # Buscar Admin como raíz
                admin = User.objects.filter(
                    rol=ROLE_ADMIN,
                    deleted_at__isnull=True
                ).select_related('wallet').first()
                if not admin:
                    logger.error(f"No se encontró un Admin activo para asignar como hierarchy_root a Distribuidor {instance.username}")
                    raise ValueError(_("No se encontró un administrador activo para asignar como jerarquía raíz."))
                hierarchy_root = admin
            elif instance.rol in [ROLE_VENDEDOR, ROLE_CLIENTE]:
                # Buscar Distribuidor desde DistribuidorVendedor
                from apps.users.models import DistribuidorVendedor
                dv = DistribuidorVendedor.objects.filter(
                    vendedor=instance,
                    deleted_at__isnull=True
                ).select_related('distribuidor__wallet').first()
                if dv:
                    hierarchy_root = dv.distribuidor
                else:
                    # Asignar Distribuidor predeterminado si no hay relación explícita
                    distribuidor = User.objects.filter(
                        rol=ROLE_DISTRIBUIDOR,
                        deleted_at__isnull=True
                    ).select_related('wallet').first()
                    if not distribuidor:
                        logger.error(f"No se encontró un Distribuidor activo para asignar como hierarchy_root a {instance.username} (rol: {instance.rol})")
                        raise ValueError(_("No se encontró un distribuidor activo para asignar como jerarquía raíz."))
                    hierarchy_root = distribuidor

            # 1. Crear o actualizar billetera para todos los roles que usan wallet
            if instance.rol in [ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR, ROLE_CLIENTE]:
                # Validar hierarchy_root para roles que lo requieren
                if instance.rol in [ROLE_DISTRIBUIDOR, ROLE_VENDEDOR, ROLE_CLIENTE] and not hierarchy_root:
                    logger.error(f"Hierarchy_root no asignado para {instance.username} (rol: {instance.rol})")
                    raise ValueError(_("Se requiere un hierarchy_root para Distribuidores, Vendedores y Clientes."))
                # Protección extrema: NO permitir billeteras con hierarchy_root vacío (excepto Admin)
                if instance.rol != ROLE_ADMIN and hierarchy_root is None:
                    logger.error(f"No se puede crear billetera sin hierarchy_root asignado para usuario {instance.username} (rol: {instance.rol})")
                    raise ValueError(_("No es válido crear billetera sin hierarchy_root para este rol."))
                
                wallet, wallet_created = Wallet.objects.get_or_create(
                    user=instance,
                    defaults={
                        'balance': Decimal('0.00'),
                        'blocked_balance': Decimal('0.00'),
                        'hierarchy_root': hierarchy_root
                    }
                )
                if wallet_created:
                    UserChangeLog.objects.create(
                        user=instance,
                        changed_by=None,  # Sistema
                        change_type='create',
                        change_description=str(_("Billetera creada automáticamente")),
                        details={
                            "wallet_id": str(wallet.id),
                            "rol": instance.rol,
                            "username": instance.username,
                            "hierarchy_root": hierarchy_root.username if hierarchy_root else None
                        }
                    )
                    logger.info(
                        f"Billetera creada para {instance.username} (rol: {instance.rol}, wallet_id: {wallet.id}, "
                        f"hierarchy_root: {hierarchy_root.username if hierarchy_root else 'None'})"
                    )
                elif not created:
                    # 2. Actualizar hierarchy_root si cambió
                    old_hierarchy_root = wallet.hierarchy_root
                    if old_hierarchy_root != hierarchy_root:
                        wallet.hierarchy_root = hierarchy_root
                        wallet.save(update_fields=['hierarchy_root', 'last_updated'])
                        UserChangeLog.objects.create(
                            user=instance,
                            changed_by=None,  # Sistema
                            change_type='update',
                            change_description=str(_("Jerarquía de billetera actualizada")),
                            details={
                                "wallet_id": str(wallet.id),
                                "rol": instance.rol,
                                "username": instance.username,
                                "old_hierarchy_root": old_hierarchy_root.username if old_hierarchy_root else None,
                                "new_hierarchy_root": hierarchy_root.username if hierarchy_root else None
                            }
                        )
                        logger.info(
                            f"Jerarquía actualizada para {instance.username} (wallet_id: {wallet.id}, "
                            f"old_hierarchy_root: {old_hierarchy_root.username if old_hierarchy_root else 'None'}, "
                            f"new_hierarchy_root: {hierarchy_root.username if hierarchy_root else 'None'})"
                        )

            # 3. Generar código ID único (si no existe)
            if not instance.codigo_id:
                prefix_map = {
                    ROLE_CLIENTE: 'CL',
                    ROLE_DISTRIBUIDOR: 'DI',
                    ROLE_VENDEDOR: 'VE',
                    ROLE_ADMIN: 'AD'
                }
                prefix = prefix_map.get(instance.rol, 'US')
                # Usar select_for_update para evitar colisiones
                with transaction.atomic():
                    total = User.objects.filter(
                        rol=instance.rol,
                        deleted_at__isnull=True
                    ).select_for_update().count()
                    formatted_id = f"{prefix}{total:06d}"
                    User.objects.filter(pk=instance.pk).update(codigo_id=formatted_id)
                UserChangeLog.objects.create(
                    user=instance,
                    changed_by=None,  # Sistema
                    change_type='update',
                    change_description=str(_("Código ID generado automáticamente")),
                    details={
                        "codigo_id": formatted_id,
                        "rol": instance.rol,
                        "username": instance.username
                    }
                )
                logger.info(f"Código ID {formatted_id} asignado para {instance.username} (rol: {instance.rol})")

    except Exception as e:
        logger.error(f"Error en post_save para {instance.username} (rol: {instance.rol}): {str(e)}", exc_info=True)
        # No interrumpir creación/actualización del usuario
        return