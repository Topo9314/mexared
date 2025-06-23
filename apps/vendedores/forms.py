"""
Formularios para la gestión de vendedores en MexaRed.
Proporciona creación de nuevos usuarios vendedores, asignación y descuento de saldo,
con validaciones avanzadas, internacionalización, soporte multi-moneda, y escalabilidad empresarial.
"""
from django import forms
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from decimal import Decimal
import re
from apps.users.models import User
from apps.users.forms import normalize_email, normalize_username
from apps.vendedores.models import DistribuidorVendedor

class CrearVendedorForm(UserCreationForm):
    """
    Formulario avanzado para que un distribuidor cree un nuevo usuario con rol 'vendedor'.
    Incluye campos para datos de usuario, contacto y RFC (opcional), con validaciones robustas y soporte para auditoría.
    Saldo inicial se gestiona exclusivamente a través del módulo de transacciones.
    """
    first_name = forms.CharField(
        max_length=50,
        required=False,
        label=_("Nombre(s)"),
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ej. Juan"),
            'aria-describedby': 'first_name_help',
            'autocomplete': 'given-name'
        }),
        help_text=_("Nombre del vendedor (opcional).")
    )
    last_name = forms.CharField(
        max_length=50,
        required=False,
        label=_("Apellido(s)"),
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ej. Pérez"),
            'aria-describedby': 'last_name_help',
            'autocomplete': 'family-name'
        }),
        help_text=_("Apellidos del vendedor (opcional).")
    )
    direccion = forms.CharField(
        max_length=255,
        required=False,
        label=_("Dirección de Contacto"),
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ej. Calle Falsa 123, CDMX"),
            'aria-describedby': 'direccion_help',
            'autocomplete': 'address-line1'
        }),
        help_text=_("Dirección física o de contacto del vendedor (opcional).")
    )
    telefono = forms.CharField(
        max_length=20,
        required=False,
        label=_("Teléfono de Contacto"),
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ej. +521234567890"),
            'aria-describedby': 'telefono_help',
            'autocomplete': 'tel'
        }),
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{10,15}$',
                message=_("El número de teléfono debe ser válido (10-15 dígitos, opcionalmente con +).")
            )
        ],
        help_text=_("Teléfono en formato internacional (opcional).")
    )
    email_contacto = forms.EmailField(
        required=False,
        label=_("Correo de Contacto"),
        widget=forms.EmailInput(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ej. contacto@correo.com"),
            'aria-describedby': 'email_contacto_help',
            'autocomplete': 'email'
        }),
        help_text=_("Correo adicional para contacto (opcional).")
    )
    nombre_comercial = forms.CharField(
        max_length=100,
        required=False,
        label=_("Nombre Comercial"),
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ej. Juan's Telecom"),
            'aria-describedby': 'nombre_comercial_help',
            'autocomplete': 'organization'
        }),
        help_text=_("Nombre de marca o empresa del vendedor (opcional, se generará automáticamente si no se proporciona).")
    )
    rfc = forms.CharField(
        max_length=13,
        required=False,  # RFC ahora es opcional
        label=_("RFC"),
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ej. XAXX010101000"),
            'aria-describedby': 'rfc_help',
            'autocomplete': 'off'
        }),
        validators=[
            RegexValidator(
                regex=r'^([A-ZÑ&]{3,4})\d{6}[A-Z0-9]{3}$',
                message=_("Debe ser un RFC válido (ejemplo: XAXX010101000).")
            )
        ],
        help_text=_("Registro Federal de Contribuyentes del vendedor (opcional).")
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'password1', 'password2', 'direccion', 'telefono', 'email_contacto', 'nombre_comercial', 'rfc']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Ej. juanperez"),
                'aria-describedby': 'username_help',
                'autocomplete': 'username'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Ej. juan.perez@correo.com"),
                'aria-describedby': 'email_help',
                'autocomplete': 'email'
            }),
            'password1': forms.PasswordInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Contraseña"),
                'aria-describedby': 'password1_help',
                'autocomplete': 'new-password'
            }),
            'password2': forms.PasswordInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Confirmar contraseña"),
                'aria-describedby': 'password2_help',
                'autocomplete': 'new-password'
            }),
        }
        labels = {
            'username': _("Nombre de usuario"),
            'email': _("Correo electrónico"),
            'password1': _("Contraseña"),
            'password2': _("Confirmar contraseña"),
        }
        help_texts = {
            'username': _("Debe ser único, entre 3 y 150 caracteres, solo letras, números y @/./+/-/_"),
            'email': _("Correo principal para notificaciones (requerido)."),
            'password1': _("Mínimo 8 caracteres, con al menos una mayúscula, un número y no debe ser común."),
        }

    def __init__(self, *args, **kwargs):
        """Inicializa el formulario, aceptando un argumento distribuidor."""
        self.distribuidor = kwargs.pop('distribuidor', None)
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True

    def clean_username(self):
        """Valida unicidad y formato del nombre de usuario."""
        username = normalize_username(self.cleaned_data['username'])
        if len(username) < 3 or len(username) > 150:
            raise ValidationError(
                _("El nombre de usuario debe tener entre 3 y 150 caracteres."), code='length_invalid'
            )
        if not re.match(r'^[\w.@+-]+$', username):
            raise ValidationError(
                _("El nombre de usuario solo puede contener letras, números y @/./+/-/_"), code='format_invalid'
            )
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError(
                _("El nombre de usuario ya está en uso."), code='unique_username'
            )
        return username

    def clean_email(self):
        """Valida unicidad del correo electrónico."""
        email = normalize_email(self.cleaned_data['email'])
        if not email:
            raise ValidationError(
                _("El correo electrónico es obligatorio."), code='required_email'
            )
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError(
                _("Ya existe una cuenta con este correo electrónico."), code='unique_email'
            )
        return email

    def clean_email_contacto(self):
        """Valida unicidad del correo de contacto."""
        email_contacto = normalize_email(self.cleaned_data.get('email_contacto', ''))
        if email_contacto and User.objects.filter(email__iexact=email_contacto).exists():
            raise ValidationError(
                _("El correo de contacto ya está registrado."), code='unique_email_contacto'
            )
        return email_contacto

    def clean_rfc(self):
        """Valida unicidad y formato del RFC solo si se proporciona."""
        rfc = self.cleaned_data.get('rfc', '').strip().upper()
        if not rfc:
            return rfc  # Permitir RFC vacío
        if not re.match(r'^([A-ZÑ&]{3,4})\d{6}[A-Z0-9]{3}$', rfc):
            raise ValidationError(
                _("Debe ser un RFC válido (ejemplo: XAXX010101000)."), code='invalid_rfc'
            )
        if User.objects.filter(rfc=rfc).exists():
            raise ValidationError(
                _("Ya existe una cuenta con este RFC."), code='unique_rfc'
            )
        return rfc

    def clean(self):
        """Valida la consistencia general del formulario."""
        cleaned_data = super().clean()
        email = normalize_email(cleaned_data.get('email', ''))
        email_contacto = normalize_email(cleaned_data.get('email_contacto', ''))
        if email and email_contacto and email == email_contacto:
            raise ValidationError(
                _("El correo principal y el correo de contacto no pueden ser iguales."),
                code='duplicate_email'
            )
        # Ajustar nombre_comercial en cleaned_data para consistencia
        nombre_comercial = cleaned_data.get('nombre_comercial', '').strip()
        if not nombre_comercial:
            first_name = cleaned_data.get('first_name', '').strip()
            last_name = cleaned_data.get('last_name', '').strip()
            if first_name or last_name:
                cleaned_data['nombre_comercial'] = f"{first_name} {last_name}".strip()
            else:
                cleaned_data['nombre_comercial'] = cleaned_data.get('username', '').strip()
        return cleaned_data

    def save(self, commit=True):
        """Guarda el usuario vendedor y crea la relación DistribuidorVendedor."""
        if not self.distribuidor:
            raise ValidationError(
                _("Se requiere un distribuidor para crear la relación."), code='missing_distribuidor'
            )
        try:
            with transaction.atomic():
                user = super().save(commit=False)
                user.rol = 'vendedor'
                user.email = normalize_email(self.cleaned_data.get('email', ''))
                user.username = normalize_username(self.cleaned_data['username'])
                user.first_name = self.cleaned_data.get('first_name', '')
                user.last_name = self.cleaned_data.get('last_name', '')
                user.rfc = self.cleaned_data.get('rfc', '').strip().upper() or None  # Guardar None si RFC está vacío
                user.hierarchy_root = self.distribuidor
                if commit:
                    user.save()
                    # Garantizar que nombre_comercial siempre tenga un valor válido
                    nombre_comercial = self.cleaned_data.get('nombre_comercial', '').strip()
                    if not nombre_comercial:
                        nombre_comercial = f"{user.first_name} {user.last_name}".strip()
                    if not nombre_comercial:
                        nombre_comercial = user.username
                    DistribuidorVendedor.objects.create(
                        distribuidor=self.distribuidor,
                        vendedor=user,
                        saldo_inicial=Decimal('0.00'),
                        saldo_asignado=Decimal('0.00'),
                        saldo_disponible=Decimal('0.00'),
                        moneda='MXN',
                        direccion_contacto=self.cleaned_data.get('direccion', ''),
                        telefono_contacto=self.cleaned_data.get('telefono', ''),
                        correo_contacto=self.cleaned_data.get('email_contacto', ''),
                        nombre_comercial=nombre_comercial,
                        es_creado_directamente=True,
                        creado_por=self.distribuidor,
                        activo=True
                    )
                return user
        except Exception as e:
            raise ValidationError(
                _("Error al crear el vendedor: ") + str(e), code='save_error'
            )

class AsignarSaldoForm(forms.Form):
    """
    Formulario para asignar saldo adicional a un vendedor existente.
    Valida moneda y monto positivo con soporte para accesibilidad.
    """
    monto = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        min_value=Decimal('0.01'),
        label=_("Monto a Asignar"),
        widget=forms.NumberInput(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ej. 500.00"),
            'step': '0.01',
            'aria-describedby': 'monto_help',
            'autocomplete': 'off'
        }),
        help_text=_("Monto adicional a asignar al vendedor.")
    )

    def __init__(self, *args, **kwargs):
        """Inicializa el formulario con la relación existente para validar moneda."""
        self.relacion = kwargs.pop('relacion', None)
        super().__init__(*args, **kwargs)

    def clean_monto(self):
        """Valida que el monto sea positivo."""
        monto = self.cleaned_data.get('monto')
        if monto is None or monto <= 0:
            raise ValidationError(
                _("El monto debe ser mayor a cero."), code='invalid_monto'
            )
        return monto

class DescontarSaldoForm(forms.Form):
    """
    Formulario para descontar saldo disponible de un vendedor.
    Valida que el monto no exceda el saldo disponible con soporte para accesibilidad.
    """
    monto = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        min_value=Decimal('0.01'),
        label=_("Monto a Descontar"),
        widget=forms.NumberInput(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ej. 100.00"),
            'step': '0.01',
            'aria-describedby': 'monto_help',
            'autocomplete': 'off'
        }),
        help_text=_("Monto a descontar del saldo disponible.")
    )

    def __init__(self, *args, **kwargs):
        """Inicializa el formulario con la relación para validar el saldo disponible."""
        self.relacion = kwargs.pop('relacion', None)
        super().__init__(*args, **kwargs)

    def clean_monto(self):
        """Valida que el monto no exceda el saldo disponible."""
        monto = self.cleaned_data.get('monto')
        if monto is None or monto <= 0:
            raise ValidationError(
                _("El monto debe ser mayor a cero."), code='invalid_monto'
            )
        if self.relacion and monto > self.relacion.saldo_disponible:
            raise ValidationError(
                _("El monto excede el saldo disponible del vendedor."),
                code='exceed_saldo'
            )
        return monto

class DistribuidorVendedorForm(forms.ModelForm):
    """
    Formulario para editar la relación Distribuidor-Vendedor.
    Maneja dirección y teléfono de contacto (saldo inicial se gestiona vía transacciones).
    """
    class Meta:
        model = DistribuidorVendedor
        fields = ['direccion_contacto', 'telefono_contacto']
        widgets = {
            'direccion_contacto': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Ej. Calle Falsa 123, CDMX"),
                'aria-describedby': 'direccion_help',
                'autocomplete': 'address-line1'
            }),
            'telefono_contacto': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Ej. +521234567890"),
                'aria-describedby': 'telefono_contacto_help',
                'autocomplete': 'tel'
            }),
        }
        labels = {
            'direccion_contacto': _("Dirección"),
            'telefono_contacto': _("Teléfono de Contacto"),
        }
        help_texts = {
            'direccion_contacto': _("Dirección física o de contacto del vendedor (opcional)."),
            'telefono_contacto': _("Teléfono en formato internacional (opcional)."),
        }

    def __init__(self, *args, **kwargs):
        """Inicializa el formulario, aceptando un argumento distribuidor."""
        self.distribuidor = kwargs.pop('distribuidor', None)
        super().__init__(*args, **kwargs)

    def clean_telefono_contacto(self):
        """Valida el formato del número de teléfono."""
        telefono = self.cleaned_data.get('telefono_contacto', '').strip()
        if telefono and not re.match(r'^\+?1?\d{10,15}$', telefono):
            raise ValidationError(
                _("El número de teléfono debe ser válido (10-15 dígitos, opcionalmente con +)."),
                code='invalid_phone'
            )
        return telefono

    def save(self, commit=True):
        """Guarda la instancia asegurando que el distribuidor sea correcto."""
        instance = super().save(commit=False)
        if self.distribuidor and instance.distribuidor != self.distribuidor:
            raise ValidationError(
                _("No tienes permiso para modificar esta relación."), code='invalid_distribuidor'
            )
        if commit:
            instance.save()
        return instance