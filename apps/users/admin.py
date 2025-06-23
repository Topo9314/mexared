"""
Panel de administración para la aplicación de usuarios en MexaRed.
Proporciona gestión avanzada de usuarios, relaciones jerárquicas y auditoría,
con soporte para internacionalización, escalabilidad, seguridad y multilingüismo.
Optimizado para operaciones a gran escala con visualización clara y filtros avanzados.
"""

import logging
import json
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from django.db.models import Q
from django.utils.html import format_html
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django import forms
from .models import User, DistribuidorVendedor, UserChangeLog
from .utils.normalizers import normalize_email, normalize_username

# Configuración de logging para monitoreo en producción
logger = logging.getLogger(__name__)

# ============================
# 🔹 PERSONALIZACIÓN VISUAL
# ============================

admin.site.site_title = _("Administración MexaRed")
admin.site.site_header = _("Panel de Administración MexaRed")
admin.site.index_title = _("Bienvenido al Panel de Control MexaRed")

# ============================
# 🔹 FORMULARIOS PERSONALIZADOS
# ============================

class CustomUserCreationForm(forms.ModelForm):
    """
    Formulario personalizado para la creación de usuarios en el Admin.
    Incluye campos para establecer la jerarquía y contraseñas.
    """
    password1 = forms.CharField(
        label=_("Contraseña"),
        widget=forms.PasswordInput,
        required=True,
        help_text=_("Ingrese la contraseña para el nuevo usuario.")
    )
    password2 = forms.CharField(
        label=_("Confirmar contraseña"),
        widget=forms.PasswordInput,
        required=True,
        help_text=_("Repita la contraseña para confirmarla.")
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'telefono', 'rol', 'hierarchy_root')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Configurar opciones dinámicas para hierarchy_root según el rol
        self.fields['hierarchy_root'].queryset = User.objects.filter(
            rol__in=['admin', 'distribuidor']
        ).select_related('wallet')
        self.fields['hierarchy_root'].required = False  # Validación en clean()

    def clean_username(self):
        username = normalize_username(self.cleaned_data['username'])
        if len(username) < 3:
            raise ValidationError(
                _("El nombre de usuario debe tener al menos 3 caracteres."),
                code='min_length'
            )
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError(
                _("El nombre de usuario ya está en uso."),
                code='unique_username'
            )
        return username

    def clean_email(self):
        email = normalize_email(self.cleaned_data['email'])
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError(
                _("Ya existe una cuenta con este correo electrónico."),
                code='unique_email'
            )
        return email

    def clean_telefono(self):
        telefono = self.cleaned_data.get('telefono', '').strip()
        if telefono:
            validator = RegexValidator(
                regex=r'^\+?1?\d{10,15}$',
                message=_("El número de teléfono debe ser válido (10-15 dígitos, opcionalmente con + o +1).")
            )
            validator(telefono)
        return telefono

    def clean_hierarchy_root(self):
        hierarchy_root = self.cleaned_data.get('hierarchy_root')
        rol = self.cleaned_data.get('rol')
        if rol in ['distribuidor', 'vendedor'] and not hierarchy_root:
            raise ValidationError(
                _("Los Distribuidores y Vendedores deben tener una raíz de jerarquía asignada.")
            )
        if rol == 'admin' and hierarchy_root:
            raise ValidationError(
                _("Un Admin no puede tener una raíz de jerarquía.")
            )
        if hierarchy_root:
            if hierarchy_root.rol == 'distribuidor' and rol != 'vendedor':
                raise ValidationError(
                    _("Un Distribuidor solo puede ser raíz de un Vendedor.")
                )
            if hierarchy_root.rol == 'admin' and rol != 'distribuidor':
                raise ValidationError(
                    _("Un Admin solo puede ser raíz de un Distribuidor.")
                )
        return hierarchy_root

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            raise ValidationError(
                _("Las contraseñas no coinciden."),
                code='password_mismatch'
            )
        return password2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
        return user

class UserAdminForm(forms.ModelForm):
    """
    Formulario personalizado para la edición de usuarios en el Admin.
    Permite actualizar contraseñas y otros campos con validaciones consistentes.
    """
    password1 = forms.CharField(
        label=_("Contraseña"),
        widget=forms.PasswordInput,
        required=False,
        help_text=_("Deje en blanco para mantener la contraseña actual.")
    )
    password2 = forms.CharField(
        label=_("Confirmar contraseña"),
        widget=forms.PasswordInput,
        required=False,
        help_text=_("Repita la contraseña para confirmarla.")
    )

    class Meta:
        model = User
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['hierarchy_root'].queryset = User.objects.filter(
            rol__in=['admin', 'distribuidor']
        ).select_related('wallet')
        self.fields['hierarchy_root'].required = False

    def clean_username(self):
        username = normalize_username(self.cleaned_data['username'])
        if len(username) < 3:
            raise ValidationError(
                _("El nombre de usuario debe tener al menos 3 caracteres."),
                code='min_length'
            )
        if User.objects.filter(username__iexact=username).exclude(pk=self.instance.pk).exists():
            raise ValidationError(
                _("El nombre de usuario ya está en uso."),
                code='unique_username'
            )
        return username

    def clean_email(self):
        email = normalize_email(self.cleaned_data['email'])
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError(
                _("Ya existe una cuenta con este correo electrónico."),
                code='unique_email'
            )
        return email

    def clean_telefono(self):
        telefono = self.cleaned_data.get('telefono', '').strip()
        if telefono:
            validator = RegexValidator(
                regex=r'^\+?1?\d{10,15}$',
                message=_("El número de teléfono debe ser válido (10-15 dígitos, opcionalmente con + o +1).")
            )
            validator(telefono)
        return telefono

    def clean_hierarchy_root(self):
        hierarchy_root = self.cleaned_data.get('hierarchy_root')
        rol = self.cleaned_data.get('rol')
        if rol in ['distribuidor', 'vendedor'] and not hierarchy_root:
            raise ValidationError(
                _("Los Distribuidores y Vendedores deben tener una raíz de jerarquía asignada.")
            )
        if rol == 'admin' and hierarchy_root:
            raise ValidationError(
                _("Un Admin no puede tener una raíz de jerarquía.")
            )
        if hierarchy_root:
            if hierarchy_root.rol == 'distribuidor' and rol != 'vendedor':
                raise ValidationError(
                    _("Un Distribuidor solo puede ser raíz de un Vendedor.")
                )
            if hierarchy_root.rol == 'admin' and rol != 'distribuidor':
                raise ValidationError(
                    _("Un Admin solo puede ser raíz de un Distribuidor.")
                )
        return hierarchy_root

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')

        if password1 or password2:
            if password1 != password2:
                raise ValidationError(
                    _("Las contraseñas no coinciden."),
                    code='password_mismatch'
                )
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password1 = self.cleaned_data.get('password1')
        if password1:
            user.set_password(password1)
        if commit:
            user.save()
        return user

# ============================
# 🔹 INLINES PARA RELACIONES
# ============================

class DistribuidorVendedorInlineAsDistrib(admin.TabularInline):
    """
    Inline para mostrar vendedores asignados a un distribuidor.
    """
    model = DistribuidorVendedor
    fk_name = 'distribuidor'
    fields = ('vendedor', 'fecha_asignacion', 'activo')
    readonly_fields = ('fecha_asignacion',)
    extra = 0
    autocomplete_fields = ['vendedor']
    verbose_name = _("Vendedor Asignado")
    verbose_name_plural = _("Vendedores Asignados")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('vendedor').prefetch_related('vendedor__created_users')

class DistribuidorVendedorInlineAsVendedor(admin.TabularInline):
    """
    Inline para mostrar el distribuidor asignado a un vendedor.
    """
    model = DistribuidorVendedor
    fk_name = 'vendedor'
    fields = ('distribuidor', 'fecha_asignacion', 'activo')
    readonly_fields = ('fecha_asignacion',)
    extra = 0
    autocomplete_fields = ['distribuidor']
    verbose_name = _("Distribuidor Asignado")
    verbose_name_plural = _("Distribuidores Asignados")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('distribuidor')

# ============================
# 🔹 ADMIN PARA USER
# ============================

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Administración personalizada para el modelo User.
    Gestiona usuarios con roles, auditoría y relaciones jerárquicas.
    Optimizada para gran escala con visualización clara y filtros avanzados.
    """
    form = UserAdminForm
    add_form = CustomUserCreationForm
    list_display = (
        'username',
        'full_name',
        'email_link',
        'telefono',
        'rol',
        'hierarchy_root_display',
        'status_badge',
        'creado_por',
        'ultima_actividad',
        'date_activacion',
    )
    list_filter = ('rol', 'activo', 'is_superuser', 'date_joined')
    search_fields = ('username', 'email', 'telefono', 'first_name', 'last_name', 'rfc')
    readonly_fields = ('uuid', 'date_joined', 'last_updated', 'email_link', 'ultima_actividad')
    ordering = ('-last_login', '-date_joined')
    list_per_page = 25
    autocomplete_fields = ['created_by', 'hierarchy_root']
    list_select_related = ('created_by', 'hierarchy_root')

    fieldsets = (
        (_("Identificación"), {
            'fields': ('username', 'email', 'email_link', 'telefono', 'rfc')
        }),
        (_("Nombre Completo"), {
            'fields': ('first_name', 'last_name')
        }),
        (_("Rol y Estado"), {
            'fields': ('rol', 'hierarchy_root', 'activo', 'is_active', 'is_staff', 'is_superuser')
        }),
        (_("Auditoría"), {
            'fields': ('uuid', 'date_joined', 'last_updated', 'created_by', 'deleted_at')
        }),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'username', 'email', 'first_name', 'last_name', 'telefono', 'rfc',
                'rol', 'hierarchy_root', 'password1', 'password2', 'activo', 'is_active', 'is_staff', 'is_superuser', 'created_by'
            ),
        }),
    )

    inlines = [DistribuidorVendedorInlineAsDistrib, DistribuidorVendedorInlineAsVendedor]
    actions = ['deactivate_users', 'reactivate_users']

    def hierarchy_root_display(self, obj):
        """
        Muestra el username y rol del hierarchy_root, o '-' si no existe.
        """
        if obj.hierarchy_root:
            return format_html(
                '<a href="/admin/users/user/{}/change/">{} ({})</a>',
                obj.hierarchy_root.id, obj.hierarchy_root.username, obj.hierarchy_root.get_rol_display()
            )
        return "-"
    hierarchy_root_display.short_description = _("Jerarquía Superior")

    def status_badge(self, obj):
        """
        Muestra un indicador visual del estado del usuario (activo/inactivo).
        """
        color = "green" if obj.is_active else "red"
        label = _("Activo") if obj.is_active else _("Inactivo")
        return format_html(
            '<span style="color: {}; font-weight: bold; padding: 2px 8px; border-radius: 4px;">{}</span>',
            color, label
        )
    status_badge.short_description = _("Estado")

    def full_name(self, obj):
        """
        Concatena nombre y apellido para mostrar en la lista.
        """
        return obj.full_name
    full_name.short_description = _("Nombre Completo")

    def email_link(self, obj):
        """
        Muestra el correo como enlace clicable para enviar emails.
        """
        if obj.email:
            return format_html('<a href="mailto:{}">{}</a>', obj.email, obj.email)
        return "-"
    email_link.short_description = _("Correo")

    def ultima_actividad(self, obj):
        """
        Muestra la fecha del último login del usuario.
        """
        return obj.last_login if obj.last_login else "-"
    ultima_actividad.short_description = _("Último Login")

    def creado_por(self, obj):
        """
        Muestra el username del creador como enlace al perfil o 'Sistema' si no existe.
        """
        if obj.created_by:
            return format_html(
                '<a href="/admin/users/user/{}/change/">{}</a>',
                obj.created_by.id, obj.created_by.username
            )
        return _("Sistema")
    creado_por.short_description = _("Creado Por")

    def date_activacion(self, obj):
        """
        Muestra la fecha de activación del usuario.
        """
        return obj.date_joined
    date_activacion.short_description = _("Fecha de Activación")

    def deactivate_users(self, request, queryset):
        """
        Acción para desactivar usuarios (soft delete) con retroalimentación clara.
        """
        if not request.user.is_superuser:
            raise PermissionError(_("Solo superusuarios pueden desactivar usuarios"))
        count = 0
        for user in queryset:
            if user.is_active and not user.deleted_at:
                user.soft_delete(deleted_by=request.user)
                count += 1
        self.message_user(request, f"{count} usuario(s) desactivado(s) correctamente.", level=messages.SUCCESS)
        logger.info(f"{request.user.username} desactivó {count} usuario(s).")

    def reactivate_users(self, request, queryset):
        """
        Acción para reactivar usuarios con retroalimentación clara.
        """
        if not request.user.is_superuser:
            raise PermissionError(_("Solo superusuarios pueden reactivar usuarios"))
        count = 0
        for user in queryset:
            if not user.is_active and user.deleted_at:
                user.is_active = True
                user.activo = True
                user.deleted_at = None
                user.save()
                UserChangeLog.objects.create(
                    user=user,
                    changed_by=request.user,
                    change_type='reactivate',
                    change_description="Usuario reactivado desde admin",
                    details={"reactivated_by": request.user.username}
                )
                count += 1
        self.message_user(request, f"{count} usuario(s) reactivado(s) correctamente.", level=messages.SUCCESS)
        logger.info(f"{request.user.username} reactivó {count} usuario(s).")

    def get_search_results(self, request, queryset, search_term):
        """
        Permite búsqueda por nombre completo, teléfono y otros campos.
        """
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        if search_term:
            queryset |= self.model.objects.filter(
                Q(first_name__icontains=search_term) |
                Q(last_name__icontains=search_term) |
                Q(telefono__icontains=search_term) |
                Q(rfc__icontains=search_term)
            )
        return queryset, use_distinct

    def get_readonly_fields(self, request, obj=None):
        """
        Restringe is_superuser y is_staff para no superusuarios.
        """
        readonly = list(self.readonly_fields)
        if not request.user.is_superuser:
            readonly.extend(['is_superuser', 'is_staff', 'password1', 'password2'])
        if obj:  # En edición, la contraseña no es editable directamente
            readonly.append('password')
        return readonly

    def get_queryset(self, request):
        """
        Optimiza consultas con select_related, defer y only para gran escala.
        Permite ver usuarios eliminados si es superusuario.
        """
        qs = super().get_queryset(request).select_related('created_by', 'hierarchy_root')\
            .defer('password')\
            .only(
                'id', 'username', 'first_name', 'last_name', 'email', 'telefono', 'rfc', 'rol',
                'hierarchy_root__username', 'created_by__username', 'last_login', 'is_active',
                'activo', 'date_joined', 'last_updated'
            )
        if request.user.is_superuser and request.GET.get('show_deleted'):
            return self.model._base_manager.all().select_related('created_by', 'hierarchy_root')
        return qs

# ============================
# 🔹 ADMIN PARA DISTRIBUIDORVENDEDOR
# ============================

@admin.register(DistribuidorVendedor)
class DistribuidorVendedorAdmin(admin.ModelAdmin):
    """
    Administración para la relación distribuidor-vendedor.
    Gestiona asignaciones con búsqueda y filtros eficientes.
    """
    list_display = ('distribuidor', 'vendedor', 'fecha_asignacion', 'activo')
    list_filter = ('activo',)
    search_fields = ('distribuidor__username', 'vendedor__username', 'distribuidor__email', 'vendedor__email')
    autocomplete_fields = ['distribuidor', 'vendedor']
    date_hierarchy = 'fecha_asignacion'
    list_per_page = 25
    readonly_fields = ('fecha_asignacion',)
    ordering = ('-fecha_asignacion',)
    list_select_related = ('distribuidor', 'vendedor', 'created_by')

    def get_queryset(self, request):
        """
        Optimiza consultas con select_related.
        """
        return super().get_queryset(request).select_related('distribuidor', 'vendedor', 'created_by')

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """
        Restringe opciones según rol.
        """
        if db_field.name == 'distribuidor':
            kwargs['queryset'] = User.objects.filter(rol='distribuidor')
        elif db_field.name == 'vendedor':
            kwargs['queryset'] = User.objects.filter(rol='vendedor')
        elif db_field.name == 'created_by':
            kwargs['queryset'] = User.objects.filter(rol__in=['distribuidor', 'admin'])
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

# ============================
# 🔹 ADMIN PARA USERCHANGELOG
# ============================

@admin.register(UserChangeLog)
class UserChangeLogAdmin(admin.ModelAdmin):
    """
    Administración para registros de auditoría.
    Todos los campos son de solo lectura para proteger la integridad.
    """
    list_display = ('change_type', 'user', 'changed_by', 'details_preview', 'timestamp')
    list_filter = ('change_type',)
    search_fields = ('user__username', 'user__email', 'changed_by__username')
    readonly_fields = ('change_type', 'user', 'changed_by', 'change_description', 'details', 'timestamp')
    list_per_page = 50
    date_hierarchy = 'timestamp'

    def details_preview(self, obj):
        """
        Muestra una vista previa legible de los detalles JSON.
        """
        if obj.details:
            try:
                details_str = json.dumps(obj.details, indent=2, ensure_ascii=False)
                return format_html('<pre style="margin: 0; font-size: 12px;">{}</pre>', details_str[:200] + '...' if len(details_str) > 200 else details_str)
            except Exception:
                return str(obj.details)
        return "-"
    details_preview.short_description = _("Detalles")

    def has_add_permission(self, request):
        """
        Impide agregar registros manualmente.
        """
        return False

    def has_change_permission(self, request, obj=None):
        """
        Impide modificar registros de auditoría.
        """
        return False

    def get_queryset(self, request):
        """
        Optimiza consultas con select_related.
        """
        return super().get_queryset(request).select_related('user', 'changed_by')