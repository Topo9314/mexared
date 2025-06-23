"""
Formularios para la app transacciones en MexaRed.
Proporciona formularios profesionales, seguros y escalables para gestionar transacciones financieras,
filtros avanzados y motivos de transacción. Diseñado con validaciones robustas, soporte multilenguaje
y optimización para entornos empresariales de alto volumen.
"""

from django import forms
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from decimal import Decimal, InvalidOperation
import logging

from apps.transacciones.models import Transaccion, MotivoTransaccion, Moneda, ESTADO_TRANSACCION_CHOICES
from apps.users.models import User
from apps.vendedores.models import DistribuidorVendedor

# Configuración de logging para monitoreo
logger = logging.getLogger(__name__)

# ============================
# 🔹 FORMULARIO DE TRANSACCIÓN
# ============================

class TransaccionForm(forms.ModelForm):
    """
    Formulario profesional para crear transacciones internas de forma controlada.
    Incluye validaciones financieras avanzadas y soporte para multi-moneda, incluyendo transacciones de tipo REVERSO
    con comentarios obligatorios para auditoría.
    Preselecciona MXN como moneda por defecto si está disponible.
    """
    class Meta:
        model = Transaccion
        fields = [
            'tipo',
            'monto',
            'moneda',
            'tasa_cambio',
            'emisor',
            'receptor',
            'motivo',
            'referencia_externa',
            'descripcion',
            'comentario_reverso',
        ]
        widgets = {
            'tipo': forms.Select(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'data-testid': 'tipo-select',
            }),
            'monto': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'step': '0.01',
                'placeholder': _("Ej. 1000.00"),
                'autocomplete': 'off',
                'data-testid': 'monto-input',
            }),
            'moneda': forms.Select(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'data-testid': 'moneda-select',
            }),
            'tasa_cambio': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'step': '0.0001',
                'placeholder': _("Ej. 1.0000"),
                'autocomplete': 'off',
                'data-testid': 'tasa-cambio-input',
            }),
            'emisor': forms.Select(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'data-testid': 'emisor-select',
            }),
            'receptor': forms.Select(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'data-testid': 'receptor-select',
            }),
            'motivo': forms.Select(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'data-testid': 'motivo-select',
            }),
            'referencia_externa': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Ej. TX123456"),
                'autocomplete': 'off',
                'data-testid': 'referencia-externa-input',
            }),
            'descripcion': forms.Textarea(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'rows': 3,
                'placeholder': _("Detalles de la transacción"),
                'autocomplete': 'off',
                'data-testid': 'descripcion-textarea',
            }),
            'comentario_reverso': forms.Textarea(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-red-500',
                'rows': 2,
                'placeholder': _("Explica por qué se está realizando esta reversión de saldo."),
                'autocomplete': 'off',
                'data-testid': 'comentario-reverso-textarea',
            }),
        }
        labels = {
            'tipo': _("Tipo de Transacción"),
            'monto': _("Monto"),
            'moneda': _("Moneda"),
            'tasa_cambio': _("Tasa de Cambio"),
            'emisor': _("Usuario Emisor"),
            'receptor': _("Usuario Receptor"),
            'motivo': _("Motivo"),
            'referencia_externa': _("Referencia Externa"),
            'descripcion': _("Descripción"),
            'comentario_reverso': _("Comentario de Reverso"),
        }
        help_texts = {
            'monto': _("Monto positivo con dos decimales (e.g., 1000.00)."),
            'tasa_cambio': _("Tasa de cambio si la moneda no es la base (e.g., 1.0000). Opcional."),
            'referencia_externa': _("Identificador para sistemas externos, si aplica."),
            'descripcion': _("Detalles adicionales sobre la transacción."),
            'comentario_reverso': _("Justificación obligatoria para transacciones de reverso, ej. inactividad del vendedor."),
        }

    def __init__(self, *args, **kwargs):
        """Inicializa el formulario con querysets optimizados, restricciones dinámicas y MXN como moneda por defecto."""
        self.user = kwargs.pop('user', None)  # Guardar usuario autenticado como atributo de instancia
        super().__init__(*args, **kwargs)  # Inicializar campos del formulario primero

        # Verificar que el campo comentario_reverso esté definido
        if 'comentario_reverso' not in self.fields:
            logger.error("El campo 'comentario_reverso' no está definido en el formulario.")
            self.fields['comentario_reverso'] = forms.CharField(
                widget=forms.Textarea(attrs={
                    'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-red-500',
                    'rows': 2,
                    'placeholder': _("Explica por qué se está realizando esta reversión de saldo."),
                    'autocomplete': 'off',
                    'data-testid': 'comentario-reverso-textarea',
                }),
                required=False,
                label=_("Comentario de Reverso")
            )

        # Configurar queryset para emisor
        self.fields['emisor'].queryset = User.objects.filter(
            rol__in=['admin', 'distribuidor']
        ).select_related('saldo').order_by('username')

        # Configurar queryset para receptor basado en el usuario autenticado
        if self.user and self.user.rol == 'distribuidor':
            vendedores_ids = DistribuidorVendedor.objects.filter(
                distribuidor=self.user
            ).values_list('vendedor_id', flat=True)  # Permitir vendedores activos e inactivos para REVERSO
            self.fields['receptor'].queryset = User.objects.filter(
                id__in=vendedores_ids,
                rol='vendedor'
            ).select_related('saldo').order_by('username')
        else:
            # Para administradores, permitir seleccionar distribuidores o vendedores
            self.fields['receptor'].queryset = User.objects.filter(
                rol__in=['distribuidor', 'vendedor']
            ).select_related('saldo').order_by('username')

        # Configurar querysets para motivo y moneda
        self.fields['motivo'].queryset = MotivoTransaccion.objects.filter(
            activo=True
        ).order_by('codigo')
        self.fields['moneda'].queryset = Moneda.objects.all().order_by('codigo')

        # Establecer MXN como moneda por defecto si existe
        try:
            mxn = Moneda.objects.get(codigo='MXN')
            self.fields['moneda'].initial = mxn.id
        except Moneda.DoesNotExist:
            logger.warning("Moneda MXN no encontrada; no se establece valor por defecto.")

        # Si el usuario es distribuidor, fijar y ocultar emisor
        if self.user and self.user.rol == 'distribuidor':
            self.fields['emisor'].initial = self.user
            self.fields['emisor'].widget = forms.HiddenInput()
            self.fields['emisor'].required = False

        # Oculta comentario_reverso a menos que el tipo sea REVERSO
        tipo = self.data.get('tipo') if self.data else self.initial.get('tipo', None)
        if tipo != 'REVERSO' and 'comentario_reverso' in self.fields:
            self.fields['comentario_reverso'].widget = forms.HiddenInput()

    def clean_monto(self):
        """Valida que el monto sea positivo y decimal válido."""
        monto = self.cleaned_data.get('monto')
        try:
            monto = Decimal(str(monto))
            if monto <= Decimal('0'):
                logger.error(f"Monto inválido: {monto}")
                raise ValidationError(_("El monto debe ser mayor a cero."))
        except (InvalidOperation, TypeError):
            logger.error(f"Monto no decimal: {monto}")
            raise ValidationError(_("El monto debe ser un número decimal válido."))
        return monto

    def clean_tasa_cambio(self):
        """Valida que la tasa de cambio sea positiva, si se proporciona."""
        tasa = self.cleaned_data.get('tasa_cambio')
        if tasa is not None:
            try:
                tasa = Decimal(str(tasa))
                if tasa <= Decimal('0'):
                    logger.error(f"Tasa de cambio inválida: {tasa}")
                    raise ValidationError(_("La tasa de cambio debe ser mayor a cero."))
            except (InvalidOperation, TypeError):
                logger.error(f"Tasa de cambio no decimal: {tasa}")
                raise ValidationError(_("La tasa de cambio debe ser un número decimal válido."))
        return tasa

    def clean_emisor(self):
        """Valida que el emisor sea el usuario autenticado si es distribuidor."""
        emisor = self.cleaned_data.get('emisor')
        if self.user and self.user.rol == 'distribuidor' and emisor != self.user:
            logger.error(f"Emisor {emisor.username if emisor else 'None'} no coincide con usuario autenticado {self.user.username}")
            raise ValidationError(_("El emisor debe ser el usuario autenticado."))
        return emisor

    def clean_comentario_reverso(self):
        """Valida que el comentario de reverso sea obligatorio y válido para transacciones de tipo REVERSO."""
        comentario_reverso = self.cleaned_data.get('comentario_reverso', '').strip()
        tipo = self.cleaned_data.get('tipo')
        if tipo == 'REVERSO' and (not comentario_reverso or len(comentario_reverso) < 5):
            logger.error(f"Comentario de reverso inválido: {comentario_reverso}")
            raise ValidationError(
                _("El comentario de reverso es obligatorio y debe tener al menos 5 caracteres.")
            )
        return comentario_reverso

    def clean(self):
        """Valida la consistencia general del formulario."""
        cleaned_data = super().clean()
        emisor = cleaned_data.get('emisor')
        receptor = cleaned_data.get('receptor')
        tipo = cleaned_data.get('tipo')
        moneda = cleaned_data.get('moneda')
        monto = cleaned_data.get('monto', Decimal('0'))

        # Validar que emisor y receptor no sean el mismo usuario
        if emisor and receptor and emisor == receptor:
            logger.error(f"Emisor y receptor no pueden ser el mismo: {emisor.username}")
            raise ValidationError(_("El emisor y el receptor no pueden ser el mismo usuario."))

        # Validaciones por tipo de transacción
        if tipo in ['ASIGNACION', 'DEVOLUCION', 'CARGA'] and not receptor:
            logger.error(f"Receptor requerido para tipo {tipo}")
            raise ValidationError(
                _("Se requiere un receptor para transacciones de tipo {}.").format(
                    dict(Transaccion.TIPO_CHOICES).get(tipo, tipo)
                )
            )

        if tipo == 'RETIRO' and not emisor:
            logger.error("Emisor requerido para RETIRO")
            raise ValidationError(_("Se requiere un emisor para transacciones de tipo Retiro."))

        if tipo == 'REVERSO':
            # Validar permisos y roles para REVERSO
            if not self.user or self.user.rol != 'distribuidor':
                logger.error(f"Usuario {self.user.username if self.user else 'None'} no es distribuidor")
                raise ValidationError(_("Solo los distribuidores pueden realizar transacciones de reverso."))
            if not receptor:
                logger.error("Receptor requerido para REVERSO")
                raise ValidationError(_("Debe seleccionar un receptor para reversar saldo."))
            if receptor.rol != 'vendedor':
                logger.error(f"Receptor {receptor.username} no es vendedor")
                raise ValidationError(_("El receptor del reverso debe ser un vendedor."))
            if emisor != self.user:
                logger.error(f"Emisor {emisor.username if emisor else 'None'} no es el usuario autenticado {self.user.username}")
                raise ValidationError(_("El emisor del reverso debe ser el usuario autenticado."))

            # Validar relación distribuidor-vendedor
            try:
                relacion = DistribuidorVendedor.objects.get(distribuidor=self.user, vendedor=receptor)
            except DistribuidorVendedor.DoesNotExist:
                logger.error(f"No existe relación entre distribuidor {self.user.username} y vendedor {receptor.username}")
                raise ValidationError(_("No existe una relación válida entre el distribuidor y el vendedor."))

            # Validar saldo suficiente del receptor (vendedor)
            try:
                if relacion.saldo_disponible < monto:
                    logger.error(f"Vendedor {receptor.username} tiene saldo insuficiente: {relacion.saldo_disponible} < {monto}")
                    raise ValidationError(_("El vendedor no tiene saldo suficiente para el reverso."))
                if moneda and moneda.codigo != relacion.moneda:
                    logger.error(f"Moneda {moneda.codigo} no coincide con {relacion.moneda}")
                    raise ValidationError(
                        _("La moneda seleccionada no coincide con la moneda del perfil del receptor.")
                    )
            except AttributeError:
                logger.error(f"Vendedor {receptor.username} no tiene relación válida")
                raise ValidationError(_("El receptor no tiene una relación válida asociada."))

        # Validar saldo disponible para egresos (excepto REVERSO, que valida al receptor)
        if tipo in ['ASIGNACION', 'RETIRO', 'CONSUMO_API'] and emisor:
            try:
                profile = emisor.saldo  # Usar la relación OneToOneField 'saldo'
                if profile.cantidad < monto:
                    logger.error(f"Emisor {emisor.username} tiene saldo insuficiente: {profile.cantidad} < {monto}")
                    raise ValidationError(_("Saldo insuficiente para realizar esta transacción."))
                if moneda and moneda.codigo != profile.moneda:
                    logger.error(f"Moneda {moneda.codigo} no coincide con {profile.moneda}")
                    raise ValidationError(
                        _("La moneda seleccionada no coincide con la moneda del perfil del emisor.")
                    )
            except AttributeError:
                logger.error(f"Emisor {emisor.username} no tiene perfil de saldo asociado")
                raise ValidationError(_("El emisor no tiene un perfil de saldo asociado."))

        # Validar receptor para CARGA
        if tipo == 'CARGA' and receptor and receptor.rol != 'distribuidor':
            logger.error(f"Receptor {receptor.username} no es distribuidor para CARGA")
            raise ValidationError(
                _("El receptor debe ser un distribuidor para transacciones de tipo CARGA.")
            )

        return cleaned_data

# ============================
# 🔹 FORMULARIO DE FILTRO DE TRANSACCIONES
# ============================

class FiltroTransaccionForm(forms.Form):
    """
    Formulario para filtrar transacciones por fechas, estado, tipo, moneda y usuario.
    Ideal para herramientas de dashboard o reportes financieros en admin o frontend.
    """
    fecha_inicio = forms.DateField(
        label=_("Desde"),
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'autocomplete': 'off',
            'data-testid': 'fecha-inicio-input',
        })
    )
    fecha_final = forms.DateField(
        label=_("Hasta"),
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'autocomplete': 'off',
            'data-testid': 'fecha-fin-input',
        })
    )
    tipo = forms.ChoiceField(
        label=_("Tipo"),
        required=False,
        choices=[('', _('Todos'))] + Transaccion.TIPO_CHOICES,
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'data-testid': 'tipo-filtro-select',
        })
    )
    estado = forms.ChoiceField(
        label=_("Estado"),
        required=False,
        choices=[('', _('Todos'))] + ESTADO_TRANSACCION_CHOICES,
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'data-testid': 'estado-filtro-select',
        })
    )
    moneda = forms.ModelChoiceField(
        label=_("Moneda"),
        queryset=Moneda.objects.all().order_by('codigo'),
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'data-testid': 'moneda-filtro-select',
        })
    )
    usuario = forms.ModelChoiceField(
        label=_("Usuario"),
        queryset=User.objects.none(),
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'data-testid': 'usuario-filtro-select',
        })
    )

    def __init__(self, *args, **kwargs):
        """Inicializa el formulario con querysets dinámicos basados en el usuario autenticado."""
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Configurar queryset para usuario basado en el rol del usuario autenticado
        if self.user and self.user.rol == 'distribuidor':
            vendedores_ids = DistribuidorVendedor.objects.filter(
                distribuidor=self.user,
                activo=True
            ).values_list('vendedor_id', flat=True)
            self.fields['usuario'].queryset = User.objects.filter(
                id__in=vendedores_ids,
                rol='vendedor'
            ).select_related('saldo').order_by('username')
        elif self.user and self.user.rol == 'admin':
            self.fields['usuario'].queryset = User.objects.filter(
                rol__in=['admin', 'distribuidor', 'vendedor']
            ).select_related('saldo').order_by('username')
        else:
            self.fields['usuario'].queryset = User.objects.none()

    def clean(self):
        """Valida que la fecha de inicio no sea posterior a la fecha de fin."""
        cleaned_data = super().clean()
        fecha_inicio = cleaned_data.get('fecha_inicio')
        fecha_final = cleaned_data.get('fecha_final')

        if fecha_inicio and fecha_final and fecha_inicio > fecha_final:
            logger.error(f"Fecha inicio {fecha_inicio} posterior a fecha final {fecha_final}")
            raise ValidationError(
                _("La fecha de inicio no puede ser posterior a la fecha de fin.")
            )
        return cleaned_data

# ============================
# 🔹 FORMULARIO DE MOTIVO DE TRANSACCIÓN
# ============================

class MotivoTransaccionForm(forms.ModelForm):
    """
    Formulario para gestionar motivos contables de transacciones.
    Asegura códigos únicos y descripciones claras.
    """
    class Meta:
        model = MotivoTransaccion
        fields = ['codigo', 'descripcion', 'activo']
        widgets = {
            'codigo': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Ej. ERROR_SISTEMA"),
                'autocomplete': 'off',
                'data-testid': 'codigo-motivo-input',
            }),
            'descripcion': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _("Ej. Error en procesamiento de pago"),
                'autocomplete': 'off',
                'data-testid': 'descripcion-motivo-input',
            }),
            'activo': forms.CheckboxInput(attrs={
                'class': 'form-checkbox h-5 w-5 text-blue-600',
                'data-testid': 'activo-checkbox',
            }),
        }
        labels = {
            'codigo': _("Código Interno"),
            'descripcion': _("Descripción del Motivo"),
            'activo': _("¿Activo?"),
        }
        help_texts = {
            'codigo': _("Código único en mayúsculas (e.g., ERROR_SISTEMA, ASIGNACION_SEMANAL)."),
            'descripcion': _("Descripción clara del motivo de la transacción."),
            'activo': _("Indica si el motivo está disponible para nuevas transacciones.")
        }

    def clean_codigo(self):
        """Valida que el código sea único y cumpla con el formato."""
        codigo = self.cleaned_data.get('codigo', '').strip().upper()
        if not codigo:
            logger.error("Código de motivo vacío")
            raise ValidationError(_("El código es obligatorio."))
        if not all(c.isalnum() or c == '_' for c in codigo):
            logger.error(f"Código de motivo inválido: {codigo}")
            raise ValidationError(
                _("El código solo puede contener letras mayúsculas, números y guiones bajos.")
            )
        if MotivoTransaccion.objects.filter(codigo=codigo).exclude(pk=self.instance.pk).exists():
            logger.error(f"Código de motivo duplicado: {codigo}")
            raise ValidationError(_("El código ya está en uso."))
        return codigo