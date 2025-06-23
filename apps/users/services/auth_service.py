"""
Servicio de autenticación para MexaRed.
Centraliza la lógica de autenticación, validación de usuarios, control de acceso por rol y auditoría.
Proporciona utilidades de normalización para estandarizar datos de entrada.
Diseñado para ser modular, escalable y seguro, con soporte para operaciones internacionales de alto volumen.
"""

import logging
from collections import namedtuple
from django.contrib.auth import authenticate, login
from django.utils.translation import gettext_lazy as _
from apps.users.utils.normalizers import normalize_email, normalize_username
from apps.users.models import User, UserChangeLog, ROLE_ADMIN
from apps.users.utils.routing import get_dashboard_url_for_user
from apps.wallet.permissions import has_permission as wallet_has_permission

# Configuración de logging para auditoría empresarial
logger = logging.getLogger(__name__)

# Estructura para resultados de autenticación
AuthResult = namedtuple('AuthResult', ['success', 'message', 'user', 'redirect_url'])

class AuthService:
    """
    Servicio principal para autenticación y control de acceso de usuarios en MexaRed.
    Proporciona métodos para validar usuarios, roles, permisos, estados de cuenta y normalización de datos.
    Integra permisos financieros delegados al módulo wallet y otorga acceso completo a superusuarios y administradores.
    """

    # ============================
    # 🔹 MÉTODOS DE AUTENTICACIÓN
    # ============================

    @staticmethod
    def process_login(username, password, request):
        """
        Procesa un intento de login, valida credenciales y registra auditoría.

        Args:
            username (str): Nombre de usuario o correo electrónico.
            password (str): Contraseña del usuario.
            request (HttpRequest): Objeto de solicitud HTTP.

        Returns:
            AuthResult: Resultado con éxito, mensaje, usuario y URL de redirección.
        """
        # Normalizar username antes de autenticar
        normalized_username = AuthService.normalize_username(username)
        user = authenticate(request, username=normalized_username, password=password)
        ip_address = request.META.get('REMOTE_ADDR', 'unknown')

        if not user:
            try:
                user = User.objects.get(username=normalized_username)
                UserChangeLog.objects.create(
                    user=user,
                    change_type='update',
                    change_description="Intento de login fallido",
                    details={"username": normalized_username, "ip_address": ip_address}
                )
                logger.warning(f"Intento de login fallido para {normalized_username} desde {ip_address}")
            except User.DoesNotExist:
                logger.warning(f"Intento de login con usuario inexistente: {normalized_username} desde {ip_address}")
            return AuthResult(
                success=False,
                message=_("Credenciales incorrectas"),
                user=None,
                redirect_url=None
            )

        if not user.is_active or user.deleted_at:
            UserChangeLog.objects.create(
                user=user,
                change_type='update',
                change_description="Intento de login con cuenta desactivada",
                details={"username": normalized_username, "ip_address": ip_address}
            )
            logger.warning(f"Intento de login con cuenta desactivada: {normalized_username} desde {ip_address}")
            return AuthResult(
                success=False,
                message=_("Cuenta desactivada. Contacte a soporte."),
                user=None,
                redirect_url=None
            )

        login(request, user)
        UserChangeLog.objects.create(
            user=user,
            change_type='update',
            change_description="Inicio de sesión exitoso",
            details={"ip_address": ip_address}
        )
        redirect_url = get_dashboard_url_for_user(user)
        logger.info(f"Usuario {normalized_username} inició sesión exitosamente desde {ip_address}")
        return AuthResult(
            success=True,
            message=None,
            user=user,
            redirect_url=redirect_url
        )

    # ============================
    # 🔹 VALIDACIONES BÁSICAS DE USUARIO
    # ============================

    @staticmethod
    def is_authenticated(user):
        """
        Verifica si el usuario está autenticado.

        Args:
            user (User): Instancia del modelo User.

        Returns:
            bool: True si el usuario está autenticado, False en caso contrario.
        """
        return user.is_authenticated

    @staticmethod
    def is_active(user):
        """
        Verifica si el usuario está activo y no ha sido eliminado (soft delete).

        Args:
            user (User): Instancia del modelo User.

        Returns:
            bool: True si el usuario está activo, False en caso contrario.
        """
        return user.is_active and user.deleted_at is None

    @staticmethod
    def has_role(user, role):
        """
        Verifica si el usuario tiene un rol específico.

        Args:
            user (User): Instancia del modelo User.
            role (str): Rol a verificar (cliente, vendedor, distribuidor, admin).

        Returns:
            bool: True si el usuario tiene el rol especificado, False en caso contrario.
        """
        return user.has_role(role)

    @staticmethod
    def is_admin(user):
        """
        Verifica si el usuario es administrador.

        Args:
            user (User): Instancia del modelo User.

        Returns:
            bool: True si el usuario es admin, False en caso contrario.
        """
        return user.is_admin()

    # ============================
    # 🔹 CONTROL DE ACCESO POR ROL
    # ============================

    @staticmethod
    def can_access_distribuidor_dashboard(user):
        """
        Verifica si el usuario puede acceder al dashboard de distribuidor.

        Args:
            user (User): Instancia del modelo User.

        Returns:
            bool: True si el usuario tiene acceso, False en caso contrario.
        """
        return AuthService.is_authenticated(user) and AuthService.is_active(user) and user.has_role('distribuidor')

    @staticmethod
    def can_transfer_saldo(user):
        """
        Verifica si el usuario puede transferir saldo (distribuidores o admins).

        Args:
            user (User): Instancia del modelo User.

        Returns:
            bool: True si el usuario tiene permiso, False en caso contrario.
        """
        return AuthService.is_authenticated(user) and AuthService.is_active(user) and (
            user.has_role('distribuidor') or user.is_admin()
        )

    @staticmethod
    def can_assign_vendedores(user):
        """
        Verifica si el usuario puede asignar vendedores (distribuidores o admins).

        Args:
            user (User): Instancia del modelo User.

        Returns:
            bool: True si el usuario tiene permiso, False en caso contrario.
        """
        return AuthService.is_authenticated(user) and AuthService.is_active(user) and (
            user.has_role('distribuidor') or user.is_admin()
        )

    # ============================
    # 🔹 VALIDACIÓN DE PERMISOS ESPECIALES
    # ============================

    @staticmethod
    def has_permission(user, permission):
        """
        Verifica si el usuario tiene permisos tanto generales como financieros.
        Superusuarios y usuarios con rol Administrador tienen acceso completo.
        Delega permisos financieros al módulo wallet para modularidad.

        Args:
            user (User): Instancia del modelo User.
            permission (str): Permiso a verificar (ej. 'can_assign_saldo', 'wallet.creditar').

        Returns:
            bool: True si el usuario tiene el permiso, False en caso contrario.
        """
        if not user or not AuthService.is_authenticated(user):
            logger.debug(f"Permiso {permission} denegado: usuario no autenticado")
            return False

        # Superusuarios y Administradores tienen acceso completo
        if user.is_superuser or user.has_role(ROLE_ADMIN):
            logger.debug(f"Permiso {permission} concedido a superusuario/administrador {user.username}")
            return True

        # Permisos clásicos de AuthService
        permission_map = {
            'can_assign_saldo': AuthService.can_transfer_saldo(user),
            'can_assign_vendedores': AuthService.can_assign_vendedores(user),
            'view_distribuidor_dashboard': AuthService.can_access_distribuidor_dashboard(user),
        }

        if permission in permission_map:
            result = permission_map[permission]
            logger.debug(f"Permiso {permission} {'concedido' if result else 'denegado'} para {user.username} (rol: {user.rol})")
            return result

        # Delegación para permisos financieros centralizados
        result = wallet_has_permission(user, permission)
        logger.debug(f"Permiso financiero {permission} {'concedido' if result else 'denegado'} para {user.username} (rol: {user.rol})")
        return result

    # ============================
    # 🔹 AUTENTICACIÓN AVANZADA (PENDIENTE DE EXPANSIÓN)
    # ============================

    @staticmethod
    def check_multiple_sessions(user, request):
        """
        Verifica si el usuario tiene múltiples sesiones activas (pendiente de implementación).

        Args:
            user (User): Instancia del modelo User.
            request (HttpRequest): Objeto de solicitud HTTP.

        Returns:
            bool: True si se permite la sesión, False si hay conflicto (futuro).
        """
        logger.debug(f"Verificación de múltiples sesiones para {user.username} no implementada")
        return True  # Placeholder para futura implementación

    @staticmethod
    def restrict_ip_access(user, request):
        """
        Restringe acceso por IP (pendiente de implementación).

        Args:
            user (User): Instancia del modelo User.
            request (HttpRequest): Objeto de solicitud HTTP.

        Returns:
            bool: True si el acceso es permitido, False en caso contrario (futuro).
        """
        logger.debug(f"Restricción de acceso por IP para {user.username} no implementada")
        return True  # Placeholder para futura implementación

    # ============================
    # 🔹 MÉTODOS PARA SEÑALES (PENDIENTE DE EXPANSIÓN)
    # ============================

    @staticmethod
    def assign_default_role(user):
        """
        Asigna un rol por defecto al crear un usuario (pendiente de implementación).

        Args:
            user (User): Instancia del modelo User.

        Returns:
            None
        """
        logger.debug(f"Asignación de rol por defecto para {user.username} no implementada")
        # Placeholder para futura implementación con señales

    @staticmethod
    def log_login_event(user, request):
        """
        Registra un evento de login para auditoría avanzada (pendiente de expansión).

        Args:
            user (User): Instancia del modelo User.
            request (HttpRequest): Objeto de solicitud HTTP.

        Returns:
            None
        """
        logger.debug(f"Registro de evento de login para {user.username} ya manejado en process_login")
        # Placeholder para futura implementación con señales

    # ============================
    # 🔧 UTILIDADES DE NORMALIZACIÓN
    # ============================

    @staticmethod
    def normalize_email(email):
        """
        Normaliza un correo electrónico eliminando espacios y convirtiéndolo a minúsculas.

        Args:
            email (str): Correo electrónico ingresado por el usuario.

        Returns:
            str: Correo electrónico limpio y estandarizado.

        Raises:
            ValueError: Si el valor proporcionado no es una cadena válida.
        """
        if not isinstance(email, str):
            logger.error(f"Intento de normalizar email inválido: {email}")
            raise ValueError(_("El valor proporcionado como email no es válido."))
        normalized = email.strip().lower()
        logger.debug(f"Email normalizado: {email} → {normalized}")
        return normalized

    @staticmethod
    def normalize_username(username):
        """
        Normaliza un nombre de usuario eliminando espacios y convirtiéndolo a minúsculas.

        Args:
            username (str): Nombre de usuario ingresado por el usuario.

        Returns:
            str: Nombre de usuario limpio y estandarizado.

        Raises:
            ValueError: Si el valor proporcionado no es una cadena válida.
        """
        if not isinstance(username, str):
            logger.error(f"Intento de normalizar username inválido: {username}")
            raise ValueError(_("El valor proporcionado como username no es válido."))
        normalized = username.strip().lower()
        logger.debug(f"Username normalizado: {username} → {normalized}")
        return normalized