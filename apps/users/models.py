"""
Modelos de usuarios para MexaRed.
Define un sistema de usuarios robusto y escalable con roles (Cliente, Vendedor, Distribuidor, Admin)
y relaciones jerárquicas entre distribuidores y vendedores. Incluye auditoría avanzada y soporte para eliminación suave.
Optimizado para operación nacional en México con validaciones específicas (RFC, teléfono) y escalabilidad futura.
"""

import uuid
import logging
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinLengthValidator, RegexValidator
from django.core.exceptions import ValidationError
from django.db.models.functions import Lower

# Configuración de logging para monitoreo en producción
logger = logging.getLogger(__name__)

# ============================
# 🔸 Constantes globales
# ============================

ROLE_CLIENTE = 'cliente'
ROLE_VENDEDOR = 'vendedor'
ROLE_DISTRIBUIDOR = 'distribuidor'
ROLE_ADMIN = 'admin'

ROLE_CHOICES = [
    (ROLE_CLIENTE, 'Cliente Final'),
    (ROLE_VENDEDOR, 'Vendedor'),
    (ROLE_DISTRIBUIDOR, 'Distribuidor'),
    (ROLE_ADMIN, 'Administrador'),
]

# ============================
# 🔹 GESTOR PERSONALIZADO
# ============================

class UserManager(BaseUserManager):
    """
    Gestor personalizado para el modelo User.
    Maneja la creación de usuarios y superusuarios con validaciones estrictas y soporte para eliminación suave.
    """
    def get_queryset(self):
        """
        Excluye usuarios eliminados por defecto (soft delete).
        """
        return super().get_queryset().filter(deleted_at__isnull=True)

    def _create_user(self, username, email, password=None, **extra_fields):
        """
        Método base para crear usuarios con validaciones comunes.
        """
        if not username:
            raise ValueError(_("El nombre de usuario es obligatorio"))
        if not email:
            raise ValueError(_("El correo electrónico es obligatorio"))

        rol = extra_fields.get('rol', ROLE_CLIENTE)
        valid_roles = [choice[0] for choice in ROLE_CHOICES]
        if rol not in valid_roles:
            raise ValueError(_("Rol inválido"))

        email = self.normalize_email(email)
        username = username.strip().lower()
        user = self.model(username=username, email=email, **extra_fields)

        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.save(using=self._db)
        return user

    def create_user(self, username, email, password=None, **extra_fields):
        """
        Crea un usuario regular con el rol especificado (por defecto 'cliente').
        """
        extra_fields.setdefault('rol', ROLE_CLIENTE)
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        extra_fields.setdefault('activo', True)
        extra_fields.setdefault('is_active', True)
        return self._create_user(username, email, password, **extra_fields)

    def create_superuser(self, username, email, password=None, **extra_fields):
        """
        Crea un superusuario con rol 'admin' y permisos completos.
        """
        extra_fields.setdefault('rol', ROLE_ADMIN)
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('activo', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_("El superusuario debe tener is_staff=True"))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_("El superusuario debe tener is_superuser=True"))

        return self._create_user(username, email, password, **extra_fields)

# ============================
# 🔹 MODELO DE USUARIO
# ============================

class User(AbstractBaseUser, PermissionsMixin):
    """
    Modelo personalizado de usuario para MexaRed.
    Soporta roles (Cliente, Vendedor, Distribuidor, Admin), eliminación suave, y auditoría avanzada.
    Incluye validaciones específicas para México (RFC, teléfono), jerarquías financieras, y campos para escalabilidad futura.
    """
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    codigo_id = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        editable=False,
        verbose_name=_("Código ID")
    )
    username = models.CharField(
        _("Nombre de usuario"),
        max_length=30,
        unique=True,
        validators=[
            MinLengthValidator(3),
            RegexValidator(
                regex=r'^[\w.@+-]+$',
                message=_("El nombre de usuario solo puede contener letras, números y @/./+/-/_")
            )
        ]
    )
    email = models.EmailField(_("Correo electrónico"), unique=True)
    first_name = models.CharField(_("Nombre(s)"), max_length=50)
    last_name = models.CharField(_("Apellido(s)"), max_length=50)
    telefono = models.CharField(
        _("Teléfono"),
        max_length=13,
        blank=True,
        null=True,
        validators=[
            RegexValidator(
                regex=r'^\+52\d{10}$',
                message=_("Debe incluir lada nacional mexicana (+52) y tener 10 dígitos")
            )
        ]
    )
    rfc = models.CharField(
        _("RFC"),
        max_length=13,
        blank=True,
        null=True,
        validators=[
            RegexValidator(
                regex=r'^([A-ZÑ&]{3,4})\d{6}[A-Z0-9]{3}$',
                message=_("Debe ser un RFC válido")
            )
        ]
    )
    tipo_documento = models.CharField(
        _("Tipo de documento"),
        max_length=20,
        blank=True,
        choices=[
            ('INE', 'INE'),
            ('Pasaporte', 'Pasaporte'),
            ('Otro', 'Otro')
        ]
    )
    numero_documento = models.CharField(
        _("Número de documento"),
        max_length=30,
        blank=True
    )
    rol = models.CharField(
        _("Rol"),
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_CLIENTE
    )
    hierarchy_root = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subordinates',
        verbose_name=_("Raíz de jerarquía"),
        help_text=_("Usuario superior jerárquico (Distribuidor o Admin).")
    )
    activo = models.BooleanField(_("Activo"), default=True)
    is_staff = models.BooleanField(_("Acceso al panel"), default=False)
    is_active = models.BooleanField(_("Cuenta activa"), default=True)
    deleted_at = models.DateTimeField(_("Fecha de eliminación"), null=True, blank=True)
    date_joined = models.DateTimeField(_("Fecha de registro"), default=timezone.now)
    last_updated = models.DateTimeField(_("Última actualización"), auto_now=True)
    created_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_users',
        verbose_name=_("Creado por")
    )

    objects = UserManager()

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email', 'first_name', 'last_name']

    class Meta:
        verbose_name = _("Usuario")
        verbose_name_plural = _("Usuarios")
        indexes = [
            models.Index(fields=['username', 'email']),
            models.Index(fields=['rol']),
            models.Index(fields=['uuid']),
            models.Index(fields=['codigo_id']),
            models.Index(fields=['rfc']),
            models.Index(fields=['hierarchy_root']),  # Índice para consultas jerárquicas
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(rol__in=[choice[0] for choice in ROLE_CHOICES]),
                name='valid_rol'
            ),
            models.UniqueConstraint(
                Lower('email'),
                name='unique_email_case_insensitive'
            )
        ]

    def __str__(self):
        return f"{self.username} ({self.get_rol_display()})"

    def clean(self):
        """
        Validaciones personalizadas antes de guardar.
        """
        super().clean()
        if self.rol == ROLE_ADMIN and not (self.is_staff and self.is_superuser):
            raise ValidationError(_("Los administradores deben tener is_staff=True y is_superuser=True"))
        if self.is_superuser and self.rol != ROLE_ADMIN:
            raise ValidationError(_("Los superusuarios deben tener rol 'admin'"))
        if self.created_by and self.created_by.rol not in [ROLE_DISTRIBUIDOR, ROLE_ADMIN]:
            raise ValidationError(_("Solo distribuidores o administradores pueden crear usuarios"))
        if self.rol == ROLE_CLIENTE and self.is_staff:
            raise ValidationError(_("Los clientes no pueden tener acceso al panel (is_staff=True)"))
        if self.rol not in [choice[0] for choice in ROLE_CHOICES]:
            raise ValidationError(_("Rol inválido"))
        if self.hierarchy_root:
            if self.hierarchy_root == self:
                raise ValidationError(_("Un usuario no puede ser su propia raíz de jerarquía"))
            if self.rol == ROLE_DISTRIBUIDOR and self.hierarchy_root.rol != ROLE_ADMIN:
                raise ValidationError(_("El hierarchy_root de un Distribuidor debe ser un Administrador"))
            if self.rol == ROLE_VENDEDOR and self.hierarchy_root.rol != ROLE_DISTRIBUIDOR:
                raise ValidationError(_("El hierarchy_root de un Vendedor debe ser un Distribuidor"))
        elif self.rol in [ROLE_DISTRIBUIDOR, ROLE_VENDEDOR]:
            raise ValidationError(_("Los Distribuidores y Vendedores deben tener una raíz de jerarquía asignada"))

    def save(self, *args, **kwargs):
        """
        Normaliza campos, ejecuta validaciones, genera codigo_id si está vacío y registra cambios en UserChangeLog.
        """
        self.username = self.username.strip().lower()
        self.email = self.email.strip().lower()
        if self.rfc:
            self.rfc = self.rfc.strip().upper()
        if not self.codigo_id:
            self.codigo_id = f"MX-{uuid.uuid4().hex[:10].upper()}"

        self.full_clean()

        is_new = self.pk is None
        changes = {}
        if not is_new:
            try:
                old_instance = User.objects.get(pk=self.pk)
                fields_to_track = ['username', 'email', 'first_name', 'last_name', 'telefono', 'rfc', 'tipo_documento', 'numero_documento', 'rol', 'activo', 'hierarchy_root']
                for field in fields_to_track:
                    old_value = getattr(old_instance, field)
                    new_value = getattr(self, field)
                    if field == 'hierarchy_root':
                        old_value = old_instance.hierarchy_root.username if old_instance.hierarchy_root else None
                        new_value = self.hierarchy_root.username if self.hierarchy_root else None
                    if old_value != new_value:
                        changes[field] = {"before": old_value, "after": new_value}
            except User.DoesNotExist:
                changes = {}

        super().save(*args, **kwargs)

        if is_new:
            UserChangeLog.objects.create(
                user=self,
                changed_by=self.created_by,
                change_type='create',
                change_description="Creación de usuario"
            )
            logger.info(f"Usuario creado: {self.username} ({self.rol}) con código ID: {self.codigo_id}")
        elif changes:
            UserChangeLog.objects.create(
                user=self,
                changed_by=self.created_by,
                change_type='update',
                change_description=f"Actualización de {', '.join(changes.keys())}",
                details=changes
            )
            logger.info(f"Usuario actualizado: {self.username} ({self.rol}), cambios: {changes}")

    def soft_delete(self, deleted_by=None):
        """
        Marca el usuario como eliminado (soft delete) y registra el cambio.
        """
        if self.deleted_at is None:
            self.deleted_at = timezone.now()
            self.activo = False
            self.is_active = False
            self.save()
            UserChangeLog.objects.create(
                user=self,
                changed_by=deleted_by,
                change_type='deactivate',
                change_description="Usuario marcado como eliminado",
                details={"deleted_by": deleted_by.username if deleted_by else "Sistema"}
            )
            logger.info(f"Usuario desactivado: {self.username} por {deleted_by.username if deleted_by else 'Sistema'}")

    @property
    def full_name(self):
        """
        Retorna el nombre completo del usuario.
        """
        return f"{self.first_name} {self.last_name}".strip()

    def has_role(self, role):
        """
        Verifica si el usuario tiene un rol específico.
        """
        return self.rol == role

    def is_admin(self):
        """
        Verifica si el usuario es administrador.
        """
        return self.rol == ROLE_ADMIN and self.is_staff and self.is_superuser

    def get_short_name(self):
        """
        Devuelve el nombre corto del usuario para uso en el admin de Django.

        Returns:
            str: Primer nombre del usuario o username si no hay nombre.
        """
        return self.first_name or self.username

# ============================
# 🔹 RELACIÓN JERÁRQUICA
# ============================

class DistribuidorVendedor(models.Model):
    """
    Modelo para asignar vendedores a distribuidores.
    Mantiene la relación jerárquica con unicidad, auditoría y validaciones robustas.
    """
    distribuidor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='vendedores_asignados',
        limit_choices_to={'rol': ROLE_DISTRIBUIDOR},
        verbose_name=_("Distribuidor")
    )
    vendedor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='distribuidor_asignado',
        limit_choices_to={'rol': ROLE_VENDEDOR},
        verbose_name=_("Vendedor")
    )
    fecha_asignacion = models.DateTimeField(_("Fecha de asignación"), default=timezone.now)
    activo = models.BooleanField(_("Activo"), default=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='distribuidor_vendedor_creations',
        verbose_name=_("Creado por")
    )

    class Meta:
        unique_together = ('distribuidor', 'vendedor')
        verbose_name = _("Asignación de Vendedor")
        verbose_name_plural = _("Asignaciones de Vendedores")
        indexes = [
            models.Index(fields=['distribuidor', 'vendedor']),
            models.Index(fields=['activo']),
            models.Index(fields=['fecha_asignacion']),
        ]

    def __str__(self):
        return f"{self.distribuidor.username} → {self.vendedor.username}"

    def clean(self):
        """
        Validaciones personalizadas para la relación.
        """
        if self.distribuidor.rol != ROLE_DISTRIBUIDOR:
            raise ValidationError(_("El distribuidor debe tener rol 'distribuidor'"))
        if self.vendedor.rol != ROLE_VENDEDOR:
            raise ValidationError(_("El vendedor debe tener rol 'vendedor'"))
        if self.distribuidor == self.vendedor:
            raise ValidationError(_("Un usuario no puede ser su propio distribuidor"))
        if self.created_by and self.created_by.rol not in [ROLE_DISTRIBUIDOR, ROLE_ADMIN]:
            raise ValidationError(_("Solo distribuidores o administradores pueden crear asignaciones"))

    def save(self, *args, **kwargs):
        """
        Ejecuta validaciones, asegura roles correctos y registra la creación en UserChangeLog.
        """
        self.full_clean()
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new:
            UserChangeLog.objects.create(
                user=self.vendedor,
                changed_by=self.created_by,
                change_type='update',
                change_description=f"Asignado a distribuidor {self.distribuidor.username}",
                details={"distribuidor": self.distribuidor.username}
            )
            logger.info(f"Relación creada: {self.distribuidor.username} → {self.vendedor.username}")

# ============================
# 🔹 HISTORIAL DE CAMBIOS (AUDITORÍA)
# ============================

class UserChangeLog(models.Model):
    """
    Modelo para registrar cambios en usuarios (auditoría).
    Soporta detalles en formato JSON para trazabilidad avanzada.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='change_logs',
        verbose_name=_("Usuario")
    )
    changed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='changes_made',
        verbose_name=_("Modificado por")
    )
    change_type = models.CharField(
        _("Tipo de cambio"),
        max_length=50,
        choices=[
            ('create', _('Creación')),
            ('update', _('Actualización')),
            ('deactivate', _('Desactivación')),
            ('reactivate', _('Reactivación')),
        ]
    )
    change_description = models.TextField(_("Descripción"), blank=True)
    details = models.JSONField(
        _("Detalles del cambio"),
        blank=True,
        null=True,
        help_text=_("Cambios específicos en formato JSON, por ejemplo, valores antes y después")
    )
    timestamp = models.DateTimeField(_("Fecha"), default=timezone.now)

    class Meta:
        verbose_name = _("Registro de cambio de usuario")
        verbose_name_plural = _("Registros de cambios de usuarios")
        indexes = [
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['change_type']),
            models.Index(fields=['changed_by']),
        ]

    def __str__(self):
        return f"{self.change_type} en {self.user.username} ({self.timestamp})"