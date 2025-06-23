# apps/activaciones/forms.py
from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.core.validators import RegexValidator
from django.db import transaction
from apps.ofertas.models import Oferta, MargenDistribuidor
from apps.users.models import User, ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR
from apps.vendedores.models import DistribuidorVendedor
from .models import Activacion, PortabilidadDetalle
import logging

logger = logging.getLogger(__name__)

TIPO_ACTIVACION = [
    ("ACTIVACION", _("Solo Activación")),
    ("ACTIVACION_PORTABILIDAD", _("Activación + Portabilidad")),
]

TIPOS_OFERTA = [
    ("MOVILIDAD", _("Movilidad")),
    ("MIFI", _("MIFI")),
    ("HBB", _("HBB")),
]

class FormularioActivacion(forms.ModelForm):
    iccid = forms.CharField(
        label=_("ICCID"),
        max_length=22,
        required=True,
        validators=[
            RegexValidator(
                regex=r'^\d{19,22}$',
                message=_("El ICCID debe tener 19-22 dígitos numéricos.")
            )
        ],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Ingrese ICCID (19-22 dígitos)'),
            'autocomplete': 'off',
            'data-error': _('Este campo es obligatorio.')
        })
    )
    nombre_cliente = forms.CharField(
        label=_("Nombre del cliente"),
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Nombre completo del cliente'),
            'autocomplete': 'off',
            'data-error': _('Este campo es obligatorio.')
        })
    )
    telefono_contacto = forms.CharField(
        label=_("Teléfono de contacto (10 dígitos)"),
        max_length=10,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('1234567890'),
            'autocomplete': 'off',
            'data-error': _('El teléfono debe tener 10 dígitos.')
        })
    )
    correo_electronico = forms.EmailField(
        label=_("Correo electrónico"),
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': _('cliente@ejemplo.com'),
            'autocomplete': 'off'
        })
    )
    tipo_activacion = forms.ChoiceField(
        label=_("Tipo de activación"),
        choices=TIPO_ACTIVACION,
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-control select2',
            'data-placeholder': _('Seleccione tipo de activación'),
            'data-error': _('Este campo es obligatorio.')
        })
    )
    nip_portabilidad = forms.CharField(
        label=_("NIP de portabilidad"),
        max_length=4,
        required=False,
        validators=[
            RegexValidator(
                regex=r'^\d{4}$',
                message=_("El NIP debe tener exactamente 4 dígitos numéricos.")
            )
        ],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('1234'),
            'autocomplete': 'off',
            'data-error': _('El NIP debe tener 4 dígitos.')
        })
    )
    numero_a_portar = forms.CharField(
        label=_("Número a portar"),
        max_length=10,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('1234567890'),
            'autocomplete': 'off',
            'data-error': _('El número debe tener 10 dígitos.')
        })
    )
    numero_a_portar_confirmar = forms.CharField(
        label=_("Confirmar número a portar"),
        max_length=10,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Repita el número a portar'),
            'autocomplete': 'off',
            'data-error': _('Los números deben coincidir.')
        })
    )
    tipo_oferta = forms.ChoiceField(
        label=_("Tipo de oferta"),
        choices=TIPOS_OFERTA,
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-control select2',
            'data-placeholder': _('Seleccione tipo de oferta'),
            'data-ajax-update': 'plan',
            'data-error': _('Este campo es obligatorio.')
        })
    )
    plan = forms.ModelChoiceField(
        label=_("Oferta disponible"),
        queryset=Oferta.objects.none(),
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-control select2',
            'data-placeholder': _('Seleccione un plan'),
            'data-error': _('Este campo es obligatorio.')
        })
    )

    class Meta:
        model = Activacion
        fields = [
            'iccid',
            'nombre_cliente',
            'telefono_contacto',
            'correo_electronico',
            'tipo_activacion',
            'tipo_oferta',
            'plan',
            'numero_a_portar',
            'nip_portabilidad',
        ]

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        tipo_oferta = self.data.get('tipo_oferta') if self.data else None
        queryset = Oferta.objects.filter(activo=True).order_by('nombre')
        if tipo_oferta:
            queryset = queryset.filter(categoria_servicio=tipo_oferta.lower())
        if self.user and self.user.is_authenticated and self.user.rol != ROLE_ADMIN:
            distribuidor = self._get_distribuidor(self.user)
            if distribuidor:
                queryset = queryset.filter(
                    margenes_distribuidor__distribuidor=distribuidor,
                    margenes_distribuidor__activo=True
                ).distinct()
            else:
                queryset = Oferta.objects.none()
        self.fields['plan'].queryset = queryset

    def _get_distribuidor(self, user):
        try:
            if user.rol == ROLE_VENDEDOR:
                return DistribuidorVendedor.objects.get(vendedor=user).distribuidor
            elif user.rol == ROLE_DISTRIBUIDOR:
                return user
            return None
        except DistribuidorVendedor.DoesNotExist:
            logger.warning(f"Vendedor {user.username} no tiene distribuidor asignado.")
            return None

    def clean(self):
        cleaned_data = super().clean()
        tipo_activacion = cleaned_data.get('tipo_activacion')
        telefono = cleaned_data.get('telefono_contacto')
        nip = cleaned_data.get('nip_portabilidad')
        numero = cleaned_data.get('numero_a_portar')
        confirmacion = cleaned_data.get('numero_a_portar_confirmar')
        iccid = cleaned_data.get('iccid')
        plan = cleaned_data.get('plan')

        # Limpieza automática de campos
        if telefono:
            cleaned_data['telefono_contacto'] = telefono.strip()
        if iccid:
            cleaned_data['iccid'] = iccid.strip()
        if nip:
            cleaned_data['nip_portabilidad'] = nip.strip()
        if numero:
            cleaned_data['numero_a_portar'] = numero.strip()
        if confirmacion:
            cleaned_data['numero_a_portar_confirmar'] = confirmacion.strip()

        # Validar teléfono (10 dígitos, solo numérico)
        if telefono and (not telefono.isdigit() or len(telefono) != 10):
            self.add_error(
                'telefono_contacto',
                _("El teléfono debe tener exactamente 10 dígitos numéricos sin prefijo +52.")
            )

        # Validar ICCID (19-22 dígitos, solo numérico, único)
        if iccid and (not iccid.isdigit() or len(iccid) not in range(19, 23)):
            self.add_error('iccid', _("El ICCID debe tener entre 19 y 22 dígitos numéricos."))
        elif iccid and Activacion.objects.filter(iccid=iccid).exists():
            self.add_error('iccid', _("Ya existe una activación con este ICCID."))

        # Validaciones para portabilidad
        if tipo_activacion == 'ACTIVACION_PORTABILIDAD':
            required_fields = ['nip_portabilidad', 'numero_a_portar', 'numero_a_portar_confirmar']
            for field in required_fields:
                if not cleaned_data.get(field):
                    self.add_error(field, _("Este campo es obligatorio para portabilidad."))
            if nip and (not nip.isdigit() or len(nip) != 4):
                self.add_error('nip_portabilidad', _("El NIP debe tener exactamente 4 dígitos numéricos."))
            if numero and (not numero.isdigit() or len(numero) != 10):
                self.add_error('numero_a_portar', _("El número a portar debe tener exactamente 10 dígitos numéricos."))
            if numero and confirmacion and numero != confirmacion:
                self.add_error('numero_a_portar', _("Los números a portar no coinciden."))
            if numero and Activacion.objects.filter(
                portabilidad_detalle__numero_actual=numero
            ).exists():
                self.add_error('numero_a_portar', _("Este número ya está registrado en otra portabilidad."))
            if plan and plan.categoria_servicio != 'movilidad':
                self.add_error('plan', _("Las portabilidades solo son válidas para planes de Movilidad."))
        else:
            if any([nip, numero, confirmacion]):
                self.add_error(None, _("Los campos de portabilidad solo son válidos para activaciones de tipo portabilidad."))

        return cleaned_data

    def save(self, commit=True):
        from .services import ActivacionService
        with transaction.atomic():
            cleaned_data = self.cleaned_data
            tipo_activacion = cleaned_data['tipo_activacion']
            oferta = cleaned_data['plan']
            numero_contacto = f"+52{cleaned_data['telefono_contacto']}"
            distribuidor_asignado = self._get_distribuidor(self.user)

            # Crear instancia de Activacion
            activacion = self.instance
            activacion.iccid = cleaned_data['iccid']
            activacion.cliente_nombre = cleaned_data['nombre_cliente']
            activacion.cliente_email = cleaned_data.get('correo_electronico', '')
            activacion.telefono_contacto = numero_contacto
            activacion.tipo_activacion = 'portabilidad' if tipo_activacion == 'ACTIVACION_PORTABILIDAD' else 'nueva'
            activacion.tipo_producto = 'SIM' if oferta.categoria_servicio == 'movilidad' else oferta.categoria_servicio.upper()
            activacion.oferta = oferta
            activacion.usuario_solicita = self.user
            activacion.distribuidor_asignado = distribuidor_asignado
            activacion.estado = 'pendiente'

            # Asignar precios según MargenDistribuidor
            try:
                margen = oferta.margenes_distribuidor.get(
                    distribuidor=distribuidor_asignado or self.user,
                    activo=True
                )
                activacion.precio_costo = margen.precio_distribuidor
                activacion.precio_final = margen.precio_cliente
            except MargenDistribuidor.DoesNotExist:
                logger.error(f"No se encontraron márgenes para oferta {oferta.id} y distribuidor {distribuidor_asignado or self.user}.")
                raise ValidationError(_("No se encontraron márgenes válidos para esta oferta y distribuidor."))

            if commit:
                activacion.save()
                if tipo_activacion == 'ACTIVACION_PORTABILIDAD':
                    PortabilidadDetalle.objects.create(
                        activacion=activacion,
                        numero_actual=cleaned_data['numero_a_portar'],
                        nip_portabilidad=cleaned_data['nip_portabilidad']
                    )
                    logger.debug(f"Portabilidad creada para activación ID={activacion.id}")
                else:
                    PortabilidadDetalle.objects.filter(activacion=activacion).delete()
                    logger.debug(f"No se requiere portabilidad para activación ID={activacion.id}")

                # Procesar activación con el servicio
                try:
                    service = ActivacionService()
                    result = service.procesar_activacion(activacion)
                    logger.info(
                        f"Activación procesada: ID={activacion.id}, ICCID={activacion.iccid}, "
                        f"Usuario={self.user.username}, Rol={self.user.rol}"
                    )
                except Exception as e:
                    logger.error(
                        f"Error procesando activación ID={activacion.id}: {str(e)}",
                        exc_info=True
                    )
                    raise ValidationError(_("Error al procesar la activación: ") + str(e))

            return activacion


            