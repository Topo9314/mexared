"""
Formularios personalizados para autenticación y gestión de usuarios en MexaRed.
Proporciona formularios seguros, escalables y optimizados para login, registro y actualización de perfiles.
Incluye validaciones reforzadas, soporte multilenguaje y diseño modular para futura expansión.
Integrado con la app transacciones para evitar redundancias financieras.
"""

from django import forms
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.contrib.auth import password_validation
from django.db.models import Q
from django.utils import timezone
from apps.users.utils.normalizers import normalize_email, normalize_username

from .models import User, UserChangeLog

# ============================
# 🔸 Utilidades
# ============================

def normalize_email(email):
    """Normaliza un correo electrónico a minúsculas y elimina espacios."""
    return email.strip().lower() if email else ''

def normalize_username(username):
    """Normaliza un nombre de usuario a minúsculas y elimina espacios."""
    return username.strip().lower() if username else ''

# ============================
# 🔐 FORMULARIO DE LOGIN
# ============================

class LoginForm(forms.Form):
    """
    Formulario para inicio de sesión de cualquier usuario.
    Permite autenticación con nombre de usuario o correo electrónico.
    Incluye validaciones de estado de cuenta y auditoría de intentos fallidos.
    """
    username = forms.CharField(
        label=_("Usuario o correo"),
        max_length=50,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Usuario o correo"),
            'autofocus': True,
            'autocomplete': 'username'
        }),
        help_text=_("Ingrese su nombre de usuario o correo electrónico.")
    )
    password = forms.CharField(
        label=_("Contraseña"),
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Contraseña"),
            'autocomplete': 'current-password'
        }),
        help_text=_("Ingrese su contraseña.")
    )

    def clean(self):
        """Valida credenciales y estado de la cuenta."""
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')

        if username and password:
            username = normalize_username(username)
            email = normalize_email(username)

            # Buscar usuario por username o email con optimización
            user = User.objects.filter(
                Q(username=username) | Q(email=email)
            ).select_related().first()

            if not user:
                raise ValidationError(
                    _("Usuario o correo no registrado."),
                    code='invalid_credentials'
                )

            if not user.is_active or user.deleted_at:
                UserChangeLog.objects.create(
                    user=user,
                    change_type='update',
                    change_description="Intento de login con cuenta desactivada",
                    details={"input": username}
                )
                raise ValidationError(
                    _("Cuenta desactivada. Contacte a soporte."),
                    code='inactive_account'
                )

            if not user.check_password(password):
                UserChangeLog.objects.create(
                    user=user,
                    change_type='update',
                    change_description="Intento de login fallido",
                    details={"input": username}
                )
                raise ValidationError(
                    _("Contraseña incorrecta."),
                    code='invalid_password'
                )

            cleaned_data['user'] = user
        return cleaned_data

# ============================
# 🧾 FORMULARIO DE REGISTRO DE CLIENTE
# ============================

class ClientRegisterForm(forms.ModelForm):
    """
    Formulario para registro de nuevos clientes finales.
    Valida unicidad, fuerza de contraseña y formato de datos.
    Registra la creación en UserChangeLog con auditoría detallada.
    """
    password1 = forms.CharField(
        label=_("Contraseña"),
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Contraseña"),
            'autocomplete': 'new-password'
        }),
        help_text=_("Mínimo 8 caracteres, con al menos una mayúscula, un número y un carácter especial.")
    )
    password2 = forms.CharField(
        label=_("Confirmar contraseña"),
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Confirmar contraseña"),
            'autocomplete': 'new-password'
        })
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'telefono']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Nombre de usuario"),
                'autocomplete': 'username'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Correo electrónico"),
                'autocomplete': 'email'
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Nombre"),
                'autocomplete': 'given-name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Apellidos"),
                'autocomplete': 'family-name'
            }),
            'telefono': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Teléfono (+521234567890)"),
                'autocomplete': 'tel'
            }),
        }
        labels = {
            'username': _("Nombre de usuario"),
            'email': _("Correo electrónico"),
            'first_name': _("Nombre(s)"),
            'last_name': _("Apellido(s)"),
            'telefono': _("Teléfono"),
        }
        help_texts = {
            'username': _("Único, entre 3 y 30 caracteres, solo letras, números y @/./+/-/_"),
            'email': _("Correo válido para contacto y autenticación."),
            'telefono': _("Formato internacional, opcional (e.g., +521234567890).")
        }

    def clean_username(self):
        """Valida unicidad y formato del nombre de usuario."""
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
        """Valida unicidad del correo electrónico."""
        email = normalize_email(self.cleaned_data['email'])
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError(
                _("Ya existe una cuenta con este correo electrónico."),
                code='unique_email'
            )
        return email

    def clean_telefono(self):
        """Valida el formato del número de teléfono."""
        telefono = self.cleaned_data.get('telefono', '').strip()
        if telefono:
            validator = RegexValidator(
                regex=r'^\+?1?\d{10,15}$',
                message=_("El número de teléfono debe ser válido (10-15 dígitos, opcionalmente con +).")
            )
            validator(telefono)
        return telefono

    def clean_password1(self):
        """Valida la fuerza de la contraseña."""
        password1 = self.cleaned_data.get('password1')
        if password1:
            try:
                password_validation.validate_password(password1, self.instance)
            except ValidationError as error:
                raise ValidationError(error)
        return password1

    def clean(self):
        """Valida coincidencia de contraseñas."""
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')

        if password1 and password2 and password1 != password2:
            raise ValidationError(
                _("Las contraseñas no coinciden."),
                code='password_mismatch'
            )
        return cleaned_data

    def save(self, commit=True):
        """
        Guarda el usuario con contraseña encriptada y rol 'cliente'.
        Registra la creación en UserChangeLog.
        """
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        user.rol = 'cliente'
        if commit:
            user.save()
            UserChangeLog.objects.create(
                user=user,
                change_type='create',
                change_description="Registro de nuevo cliente",
                details={
                    "username": user.username,
                    "email": user.email,
                    "rol": user.rol,
                    "created_at": timezone.now().isoformat()
                }
            )
        return user

# ============================
# 🧑‍💼 FORMULARIO DE ACTUALIZACIÓN DE PERFIL
# ============================

class UserUpdateForm(forms.ModelForm):
    """
    Formulario para actualizar el perfil de usuario.
    Permite edición por el usuario o administradores autorizados.
    Valida unicidad y formato de datos.
    """
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'telefono']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Nombre de usuario"),
                'autocomplete': 'username'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Correo electrónico"),
                'autocomplete': 'email'
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Nombre"),
                'autocomplete': 'given-name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Apellidos"),
                'autocomplete': 'family-name'
            }),
            'telefono': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Teléfono (+521234567890)"),
                'autocomplete': 'tel'
            }),
        }
        labels = {
            'username': _("Nombre de usuario"),
            'email': _("Correo electrónico"),
            'first_name': _("Nombre(s)"),
            'last_name': _("Apellido(s)"),
            'telefono': _("Teléfono"),
        }
        help_texts = {
            'username': _("Único, entre 3 y 30 caracteres, solo letras, números y @/./+/-/_"),
            'email': _("Correo válido para contacto y autenticación."),
            'telefono': _("Formato internacional, opcional (e.g., +521234567890).")
        }

    def clean_username(self):
        """Valida unicidad y formato del nombre de usuario."""
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
        """Valida unicidad del correo electrónico."""
        email = normalize_email(self.cleaned_data['email'])
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError(
                _("Ya existe una cuenta con este correo electrónico."),
                code='unique_email'
            )
        return email

    def clean_telefono(self):
        """Valida el formato del número de teléfono."""
        telefono = self.cleaned_data.get('telefono', '').strip()
        if telefono:
            validator = RegexValidator(
                regex=r'^\+?1?\d{10,15}$',
                message=_("El número de teléfono debe ser válido (10-15 dígitos, opcionalmente con +).")
            )
            validator(telefono)
        return telefono

    def save(self, commit=True):
        """
        Guarda los cambios en el perfil y registra la actualización en UserChangeLog.
        """
        user = super().save(commit=False)
        if commit:
            user.save()
            changes = {}
            old_instance = User.objects.get(pk=user.pk)
            fields_to_track = ['username', 'email', 'first_name', 'last_name', 'telefono']
            for field in fields_to_track:
                old_value = getattr(old_instance, field)
                new_value = getattr(user, field)
                if old_value != new_value:
                    changes[field] = {"before": old_value, "after": new_value}
            if changes:
                UserChangeLog.objects.create(
                    user=user,
                    change_type='update',
                    change_description=f"Actualización de perfil: {', '.join(changes.keys())}",
                    details=changes
                )
        return user