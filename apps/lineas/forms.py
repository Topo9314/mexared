"""
Formularios para el módulo de Líneas en MexaRed.
Proporcionan validaciones estrictas para la gestión de líneas en el panel administrativo de Django.
Diseñados para entornos SaaS Telco multinivel, con soporte para auditoría, internacionalización y escalabilidad.
Incluyen validaciones de negocio para proteger la integridad de datos y garantizar consistencia jerárquica.
Cumplen con estándares internacionales (PCI DSS, SOC2, ISO 27001) y están preparados para integración con Addinteli.
"""

import logging
from decimal import Decimal
from django import forms
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from apps.lineas.models import Linea, CATEGORIAS_SERVICIO
from apps.vendedores.models import DistribuidorVendedor
from apps.users.models import ROLE_DISTRIBUIDOR, ROLE_VENDEDOR
from apps.activaciones.models import Activacion

# Configuración de logging para auditoría en producción
logger = logging.getLogger(__name__)

class LineaForm(forms.ModelForm):
    """
    Formulario profesional para la gestión de líneas en el panel administrativo de Django.
    Incluye validaciones estrictas de negocio para proteger la integridad del sistema.
    Soporta auditoría automática, internacionalización y escalabilidad para entornos Telco multinivel.
    Diseñado para integrarse con admin.py y complementar serializers.py en operaciones API.
    """
    class Meta:
        model = Linea
        fields = [
            'msisdn', 'iccid', 'tipo_sim', 'categoria_servicio', 'estado',
            'distribuidor', 'vendedor', 'portability_status',
            'fecha_ultima_recarga', 'fecha_vencimiento_plan', 'dias_disponibles',
            'datos_consumidos', 'datos_disponibles',
            'minutos_consumidos', 'minutos_disponibles',
            'sms_consumidos', 'sms_disponibles',
        ]
        widgets = {
            'msisdn': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _('Ejemplo: +521234567890'),
                'aria-describedby': 'msisdn_help',
                'autocomplete': 'off'
            }),
            'iccid': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': _('Ejemplo: 8952112345678901234'),
                'aria-describedby': 'iccid_help',
                'autocomplete': 'off'
            }),
            'tipo_sim': forms.Select(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'aria-describedby': 'tipo_sim_help'
            }),
            'categoria_servicio': forms.Select(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'aria-describedby': 'categoria_servicio_help'
            }),
            'estado': forms.Select(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'aria-describedby': 'estado_help'
            }),
            'distribuidor': forms.Select(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'aria-describedby': 'distribuidor_help'
            }),
            'vendedor': forms.Select(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'aria-describedby': 'vendedor_help'
            }),
            'portability_status': forms.Select(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'aria-describedby': 'portability_status_help'
            }),
            'fecha_ultima_recarga': forms.DateTimeInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'type': 'datetime-local',
                'aria-describedby': 'fecha_ultima_recarga_help'
            }),
            'fecha_vencimiento_plan': forms.DateTimeInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'type': 'datetime-local',
                'aria-describedby': 'fecha_vencimiento_plan_help'
            }),
            'dias_disponibles': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'min': '0',
                'aria-describedby': 'dias_disponibles_help'
            }),
            'datos_consumidos': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'step': '0.01',
                'min': '0',
                'aria-describedby': 'datos_consumidos_help'
            }),
            'datos_disponibles': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'step': '0.01',
                'min': '0',
                'aria-describedby': 'datos_disponibles_help'
            }),
            'minutos_consumidos': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'step': '0.01',
                'min': '0',
                'aria-describedby': 'minutos_consumidos_help'
            }),
            'minutos_disponibles': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'step': '0.01',
                'min': '0',
                'aria-describedby': 'minutos_disponibles_help'
            }),
            'sms_consumidos': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'step': '0.01',
                'min': '0',
                'aria-describedby': 'sms_consumidos_help'
            }),
            'sms_disponibles': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
                'step': '0.01',
                'min': '0',
                'aria-describedby': 'sms_disponibles_help'
            }),
        }
        labels = {
            'msisdn': _("Número Telefónico (MSISDN)"),
            'iccid': _("ICCID"),
            'tipo_sim': _("Tipo de SIM"),
            'categoria_servicio': _("Categoría de Servicio"),
            'estado': _("Estado"),
            'distribuidor': _("Distribuidor"),
            'vendedor': _("Vendedor"),
            'portability_status': _("Estado de Portabilidad"),
            'fecha_ultima_recarga': _("Fecha de Última Recarga"),
            'fecha_vencimiento_plan': _("Fecha de Vencimiento del Plan"),
            'dias_disponibles': _("Días Disponibles"),
            'datos_consumidos': _("Datos Consumidos (MB)"),
            'datos_disponibles': _("Datos Disponibles (MB)"),
            'minutos_consumidos': _("Minutos Consumidos"),
            'minutos_disponibles': _("Minutos Disponibles"),
            'sms_consumidos': _("SMS Consumidos"),
            'sms_disponibles': _("SMS Disponibles"),
        }
        help_texts = {
            'msisdn': _("Número telefónico asociado a la SIM (e.g., +521234567890)."),
            'iccid': _("Identificador único de la SIM (19-22 dígitos)."),
            'tipo_sim': _("Indica si la SIM es física o eSIM."),
            'categoria_servicio': _("Categoría de servicio asociado (Movilidad, MiFi, IoT, HBB)."),
            'estado': _("Estado actual de la línea (e.g., asignada, suspendida, portada)."),
            'distribuidor': _("Usuario con rol de distribuidor asignado a la línea."),
            'vendedor': _("Usuario con rol de vendedor asignado a la línea (opcional)."),
            'portability_status': _("Estado del proceso de portabilidad (e.g., pendiente, procesando)."),
            'fecha_ultima_recarga': _("Fecha y hora de la última recarga registrada."),
            'fecha_vencimiento_plan': _("Fecha y hora de vencimiento del plan actual."),
            'dias_disponibles': _("Días restantes de vigencia del plan actual (mínimo 0)."),
            'datos_consumidos': _("Cantidad de datos consumidos en el plan actual (en MB)."),
            'datos_disponibles': _("Cantidad de datos disponibles en el plan actual (en MB)."),
            'minutos_consumidos': _("Minutos de voz consumidos en el plan actual."),
            'minutos_disponibles': _("Minutos de voz disponibles en el plan actual."),
            'sms_consumidos': _("Mensajes SMS consumidos en el plan actual."),
            'sms_disponibles': _("Mensajes SMS disponibles en el plan actual."),
        }

    def __init__(self, *args, **kwargs):
        """
        Inicializa el formulario, almacena el usuario actual y personaliza los campos.
        """
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        # Filtrar opciones de distribuidor y vendedor por rol
        self.fields['distribuidor'].queryset = self.fields['distribuidor'].queryset.filter(
            rol=ROLE_DISTRIBUIDOR, is_active=True
        )
        self.fields['vendedor'].queryset = self.fields['vendedor'].queryset.filter(
            rol=ROLE_VENDEDOR, is_active=True
        )

    def clean(self):
        """
        Validaciones centralizadas para garantizar integridad de datos.
        Protege relaciones jerárquicas, fechas, consumos y estados.
        """
        cleaned_data = super().clean()
        distribuidor = cleaned_data.get('distribuidor')
        vendedor = cleaned_data.get('vendedor')
        estado = cleaned_data.get('estado')
        iccid = cleaned_data.get('iccid')
        portability_status = cleaned_data.get('portability_status')
        fecha_ultima_recarga = cleaned_data.get('fecha_ultima_recarga')
        fecha_vencimiento_plan = cleaned_data.get('fecha_vencimiento_plan')
        datos_consumidos = cleaned_data.get('datos_consumidos', Decimal('0.00'))
        datos_disponibles = cleaned_data.get('datos_disponibles', Decimal('0.00'))
        minutos_consumidos = cleaned_data.get('minutos_consumidos', Decimal('0.00'))
        minutos_disponibles = cleaned_data.get('minutos_disponibles', Decimal('0.00'))
        sms_consumidos = cleaned_data.get('sms_consumidos', Decimal('0.00'))
        sms_disponibles = cleaned_data.get('sms_disponibles', Decimal('0.00'))
        dias_disponibles = cleaned_data.get('dias_disponibles', 0)

        # Validar relación distribuidor-vendedor
        if vendedor and distribuidor:
            if not DistribuidorVendedor.objects.filter(
                distribuidor=distribuidor,
                vendedor=vendedor,
                activo=True
            ).exists():
                logger.warning(
                    f"Intento de asignar vendedor {vendedor.username} "
                    f"no válido para distribuidor {distribuidor.username}"
                )
                raise ValidationError(
                    _("El vendedor no está asignado al distribuidor especificado."),
                    code='invalid_distribuidor_vendedor'
                )

        # Validar estado 'assigned' requiere activación exitosa
        if estado == 'assigned' and iccid:
            if not Activacion.objects.filter(
                iccid=iccid,
                estado='exitosa'
            ).exists():
                logger.warning(
                    f"Intento de asignar estado 'assigned' a línea con ICCID {iccid} sin activación exitosa"
                )
                raise ValidationError(
                    _("No se puede establecer el estado 'assigned' sin una activación exitosa registrada."),
                    code='invalid_assigned_state'
                )

        # Validar estado y portability_status
        if estado == 'processing' and not portability_status:
            raise ValidationError(
                _("Si el estado es 'processing', debe definirse el estado de portabilidad."),
                code='missing_portability_status'
            )
        if portability_status and estado != 'processing':
            raise ValidationError(
                _("El estado de portabilidad solo puede definirse si el estado es 'processing'."),
                code='invalid_portability_status'
            )

        # Validar fechas coherentes
        if fecha_ultima_recarga and fecha_vencimiento_plan and fecha_vencimiento_plan < fecha_ultima_recarga:
            raise ValidationError(
                _("La fecha de vencimiento del plan no puede ser anterior a la de última recarga."),
                code='invalid_vencimiento_date'
            )

        # Validar consumos
        if datos_consumidos > datos_disponibles:
            raise ValidationError(
                _("Los datos consumidos no pueden exceder los datos disponibles."),
                code='invalid_datos_consumidos'
            )
        if minutos_consumidos > minutos_disponibles:
            raise ValidationError(
                _("Los minutos consumidos no pueden exceder los minutos disponibles."),
                code='invalid_minutos_consumidos'
            )
        if sms_consumidos > sms_disponibles:
            raise ValidationError(
                _("Los SMS consumidos no pueden exceder los SMS disponibles."),
                code='invalid_sms_consumidos'
            )

        # Validar días disponibles
        if dias_disponibles < 0:
            raise ValidationError(
                _("Los días disponibles no pueden ser negativos."),
                code='invalid_dias_disponibles'
            )

        return cleaned_data

    def save(self, commit=True):
        """
        Sobrescribe save para registrar auditoría y asignar usuario actualizado.
        """
        from django.db import transaction
        with transaction.atomic():
            instance = super().save(commit=False)
            if self.user:
                instance.actualizado_por = self.user
            if commit:
                instance.save()
                self.save_m2m()
            logger.info(
                f"Línea {instance.msisdn} (ICCID: {instance.iccid}) "
                f"actualizada por {self.user.username if self.user else 'desconocido'}"
            )
            return instance