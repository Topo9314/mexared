"""
Serializadores para el módulo de Líneas en MexaRed.
Proporcionan serialización/deserialización segura y optimizada para el modelo Linea.
Diseñados para integrarse con Django REST Framework (DRF) y la API de Addinteli.
Soportan operaciones de lectura (consultas/auditoría) y escritura (creación/integración).
Cumplen con estándares internacionales (PCI DSS, SOC2, ISO 27001) para entornos SaaS multinivel.
"""

import logging
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
from .models import Linea

# Configuración de logging para auditoría en producción
logger = logging.getLogger(__name__)

class LineaReadSerializer(serializers.ModelSerializer):
    """
    Serializador de solo lectura para el modelo Linea.
    Exponde datos completos de líneas para consultas y auditorías vía API REST.
    Incluye campos legibles para front-end y optimizaciones para alto volumen.
    Preparado para integración con Addinteli API.
    """
    estado_display = serializers.SerializerMethodField()
    portability_display = serializers.SerializerMethodField()
    distribuidor_username = serializers.CharField(source='distribuidor.username', read_only=True, allow_null=True)
    vendedor_username = serializers.CharField(source='vendedor.username', read_only=True, allow_null=True)

    class Meta:
        model = Linea
        fields = [
            'uuid', 'msisdn', 'iccid',
            'tipo_sim', 'categoria_servicio',
            'estado', 'estado_display',
            'distribuidor', 'distribuidor_username',
            'vendedor', 'vendedor_username',
            'fecha_activacion', 'fecha_suspension', 'fecha_baja',
            'portability_status', 'portability_display', 'port_in_date', 'port_out_date',
            'fecha_ultima_recarga', 'fecha_vencimiento_plan', 'dias_disponibles',
            'datos_consumidos', 'datos_disponibles',
            'minutos_consumidos', 'minutos_disponibles',
            'sms_consumidos', 'sms_disponibles',
            'fecha_registro', 'fecha_actualizacion',
        ]
        read_only_fields = fields

    def get_estado_display(self, obj):
        """
        Devuelve la representación legible del estado de la línea.
        """
        return obj.get_estado_display()

    def get_portability_display(self, obj):
        """
        Devuelve la representación legible del estado de portabilidad, si existe.
        """
        return obj.get_portability_status_display() if obj.portability_status else None

    def to_representation(self, instance):
        """
        Optimiza la representación de datos para evitar consultas innecesarias.
        """
        ret = super().to_representation(instance)
        # Normalizar valores nulos para consistencia en la API
        for field in ['distribuidor_username', 'vendedor_username', 'portability_display']:
            if ret[field] is None:
                ret[field] = ''
        return ret

class LineaCreateSerializer(serializers.ModelSerializer):
    """
    Serializador para la creación de nuevas líneas.
    Permite registrar líneas iniciales (e.g., vía Addinteli o carga interna).
    Valida integridad de datos y asegura consistencia jerárquica.
    Campos de consumo y fechas derivadas se gestionan vía sincronización posterior.
    """
    class Meta:
        model = Linea
        fields = [
            'msisdn', 'iccid',
            'tipo_sim', 'categoria_servicio',
            'estado',
            'distribuidor', 'vendedor',
            'fecha_activacion', 'fecha_suspension',
            'portability_status',
        ]

    def validate(self, data):
        """
        Valida la integridad de los datos antes de crear una línea.
        Asegura consistencia con jerarquías y reglas de negocio.
        """
        distribuidor = data.get('distribuidor')
        vendedor = data.get('vendedor')
        estado = data.get('estado')
        portability_status = data.get('portability_status')

        # Validar relación distribuidor-vendedor
        if vendedor and distribuidor:
            from apps.vendedores.models import DistribuidorVendedor
            if not DistribuidorVendedor.objects.filter(
                distribuidor=distribuidor,
                vendedor=vendedor,
                activo=True
            ).exists():
                logger.warning(
                    f"Intento de crear línea con vendedor {vendedor.username} "
                    f"no asignado a distribuidor {distribuidor.username}"
                )
                raise serializers.ValidationError(
                    _("El vendedor no está asignado al distribuidor especificado."),
                    code='invalid_distribuidor_vendedor'
                )

        # Validar estado y portability_status
        if estado == 'processing' and not portability_status:
            raise serializers.ValidationError(
                _("Una línea en estado 'processing' debe tener un estado de portabilidad definido."),
                code='missing_portability_status'
            )

        # Validar fechas
        fecha_activacion = data.get('fecha_activacion')
        fecha_suspension = data.get('fecha_suspension')
        if fecha_suspension and fecha_activacion and fecha_suspension < fecha_activacion:
            raise serializers.ValidationError(
                _("La fecha de suspensión no puede ser anterior a la fecha de activación."),
                code='invalid_suspension_date'
            )

        return data

    def create(self, validated_data):
        """
        Crea una nueva línea con auditoría y manejo de excepciones.
        """
        try:
            instance = super().create(validated_data)
            logger.info(
                f"Línea creada vía API: MSISDN {instance.msisdn}, ICCID {instance.iccid}, "
                f"estado {instance.estado}"
            )
            return instance
        except Exception as e:
            logger.error(f"Error al crear línea vía API: {str(e)}", exc_info=True)
            raise serializers.ValidationError(
                _("Error al crear la línea: ") + str(e),
                code='create_error'
            )