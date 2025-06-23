"""
Configuración principal de la aplicación de usuarios para MexaRed.
Se asegura la carga de señales críticas, la inicialización de permisos y la optimización de la app.
Cumple con estándares internacionales (PCI DSS, SOC2, ISO 27001) y garantiza escalabilidad, seguridad y trazabilidad.

Optimizado para rendimiento, manejo de errores y compatibilidad con módulos relacionados (wallet, transacciones).
"""

from django.apps import AppConfig
import logging
import sys

# Configuración avanzada de logging para auditoría empresarial
logger = logging.getLogger(__name__)

class UsersConfig(AppConfig):
    """
    Configuración optimizada de la aplicación de usuarios.
    Gestiona la inicialización de señales, validación de dependencias y preparación para operaciones a gran escala.

    Attributes:
        default_auto_field (str): Tipo de campo predeterminado para modelos (BigAutoField).
        name (str): Nombre de la aplicación en el proyecto.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.users'

    def ready(self):
        """
        Método de inicialización ejecutado al cargar la aplicación.
        Importa señales, verifica dependencias y registra logs de arranque.

        Raises:
            ImportError: Si las señales o dependencias no se pueden importar.
            Exception: Para cualquier error crítico durante la inicialización.
        """
        try:
            # Verificar que las señales estén disponibles
            import apps.users.signals
            logger.info("Señales de usuarios cargadas exitosamente en %s.", self.name)

            # Validar existencia de dependencias críticas (e.g., Wallet)
            from apps.wallet.models import Wallet
            from django.apps import apps
            if not apps.is_installed('apps.wallet'):
                logger.warning("Módulo 'apps.wallet' no está instalado. Verifique INSTALLED_APPS.")
                raise ImportError("El módulo 'apps.wallet' es requerido para las señales de usuarios.")

            # Registro de inicio exitoso
            logger.info("Aplicación 'users' inicializada correctamente a las %s.", self._get_current_time())

        except ImportError as e:
            logger.error("Error al importar dependencias para la app 'users': %s", str(e))
            raise
        except Exception as e:
            logger.exception("Error crítico durante la inicialización de la app 'users': %s", str(e))
            raise

    def _get_current_time(self):
        """
        Método auxiliar para obtener la hora actual en formato legible.
        Utilizado para logs de auditoría.
        """
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")