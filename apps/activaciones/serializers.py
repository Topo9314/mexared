"""
serializers.py - Serializadores para el módulo de activaciones en MexaRed.
Valida y transforma datos de entrada para activaciones (nuevas, portabilidades, productos específicos).
Prepara modelos para services.py y maneja respuestas API.
Diseñado para ser seguro, escalable y compatible con estándares internacionales.
"""

import logging
from decimal import Decimal
from django.utils.translation import gettext_lazy as _
from django.core.validators import RegexValidator
from rest_framework import serializers
from apps.users.models import User, ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR
from apps.ofertas.models import Oferta
from apps.vendedores.models import DistribuidorVendedor
from .models import Activacion, PortabilidadDetalle

# Configuración de logging para auditoría
logger = logging.getLogger(__name__)

class PortabilidadDetalleSerializer(serializers.ModelSerializer):
    """
    Serializador para los detalles de portabilidad.
    Valida datos específicos requeridos para activaciones de tipo portabilidad.
    """
    numero_actual = serializers.CharField(
        max_length=20,
        validators=[
            RegexValidator(
                regex=r'^\+?\d{10,15}$',
                message=_("El número debe tener 10-15 dígitos, opcionalmente con +.")
            )
        ],
        help_text=_("Número telefónico que será portado.")
    )
    nip_portabilidad = serializers.CharField(
        max_length=10,
        validators=[
            RegexValidator(
                regex=r'^\d{4}$',
                message=_("El NIP debe ser un código de 4 dígitos.")
            )
        ],
        help_text=_("Código NIP para validar la portabilidad.")
    )
    curp = serializers.CharField(
        max_length=18,
        required=False,
        allow_blank=True,
        validators=[
            RegexValidator(
                regex=r'^[A-Z]{4}\d{6}[A-Z]{6}[A-Z0-9]{2}$',
                message=_("El CURP debe tener un formato válido.")
            )
        ],
        help_text=_("CURP del titular, opcional según regulación.")
    )
    compañia_origen = serializers.CharField(
        max_length=50,
        help_text=_("Nombre del operador actual del número.")
    )

    class Meta:
        model = PortabilidadDetalle
        fields = ['numero_actual', 'nip_portabilidad', 'curp', 'compañia_origen']

    def validate(self, attrs):
        """Valida que los campos obligatorios estén presentes."""
        if not attrs.get('numero_actual') or not attrs.get('nip_portabilidad'):
            logger.warning("Faltan campos obligatorios en portabilidad: numero_actual o nip_portabilidad")
            raise serializers.ValidationError(
                _("Número actual y NIP son obligatorios para portabilidad."),
                code='required_fields'
            )
        return attrs

class ActivacionSerializer(serializers.ModelSerializer):
    """
    Serializador principal para activaciones.
    Maneja creación y validación de activaciones, incluyendo portabilidades.
    """
    portabilidad_detalle = PortabilidadDetalleSerializer(required=False, allow_null=True)
    cliente_email = serializers.EmailField(
        required=False,
        allow_blank=True,
        help_text=_("Correo electrónico del cliente final, opcional.")
    )
    iccid = serializers.CharField(
        max_length=22,
        validators=[
            RegexValidator(
                regex=r'^\d{19,22}$',
                message=_("El ICCID debe tener 19-22 dígitos.")
            )
        ],
        help_text=_("Identificador único de la SIM.")
    )
    imei = serializers.CharField(
        max_length=15,
        required=False,
        allow_blank=True,
        validators=[
            RegexValidator(
                regex=r'^\d{15}$',
                message=_("El IMEI debe tener 15 dígitos.")
            )
        ],
        help_text=_("Identificador del dispositivo, opcional.")
    )
    telefono_contacto = serializers.CharField(
        max_length=20,
        validators=[
            RegexValidator(
                regex=r'^\+?\d{10,15}$',
                message=_("El número debe tener 10-15 dígitos, opcionalmente con +.")
            )
        ],
        help_text=_("Número de contacto del cliente.")
    )
    usuario_solicita = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(rol__in=[ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR]),
        write_only=True,
        help_text=_("Usuario que realiza la activación.")
    )
    distribuidor_asignado = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(rol=ROLE_DISTRIBUIDOR),
        required=False,
        allow_null=True,
        help_text=_("Distribuidor asignado a la activación, opcional para Admin.")
    )
    oferta_id = serializers.PrimaryKeyRelatedField(
        queryset=Oferta.objects.filter(activo=True),
        required=True,
        help_text=_("Oferta asociada a la activación.")
    )

    class Meta:
        model = Activacion
        fields = [
            'id',
            'iccid',
            'cliente_nombre',
            'cliente_email',
            'telefono_contacto',
            'imei',
            'tipo_activacion',
            'tipo_producto',
            'precio_costo',
            'precio_final',
            'usuario_solicita',
            'distribuidor_asignado',
            'portabilidad_detalle',
            'oferta_id',
            'estado',
            'numero_asignado',
            'fecha_solicitud',
            'fecha_activacion',
        ]
        read_only_fields = [
            'id',
            'respuesta_addinteli',
            'estado',
            'numero_asignado',
            'fecha_solicitud',
            'fecha_activacion',
            'precio_costo',
            'precio_final',
            'ganancia_calculada',
        ]

    def validate_tipo_activacion(self, value):
        """Valida que el tipo de activación sea permitido."""
        valid_types = [choice[0] for choice in Activacion.TIPOS_ACTIVACION]
        if value not in valid_types:
            logger.warning(f"Tipo de activación inválido recibido: {value}")
            raise serializers.ValidationError(
                _("Tipo de activación inválido: %(tipo)s") % {'tipo': value},
                code='invalid_activacion_type'
            )
        return value

    def validate_tipo_producto(self, value):
        """Valida que el tipo de producto sea permitido."""
        valid_products = [choice[0] for choice in Activacion.PRODUCTOS]
        if value not in valid_products:
            logger.warning(f"Tipo de producto inválido recibido: {value}")
            raise serializers.ValidationError(
                _("Tipo de producto inválido: %(tipo)s") % {'tipo': value},
                code='invalid_producto_type'
            )
        return value

    def validate(self, attrs):
        """Valida la lógica general de la activación."""
        tipo_activacion = attrs.get('tipo_activacion')
        portabilidad_detalle = attrs.get('portabilidad_detalle')
        tipo_producto = attrs.get('tipo_producto')
        usuario = attrs.get('usuario_solicita')
        oferta = attrs.get('oferta_id')
        distribuidor = attrs.get('distribuidor_asignado')

        # Validar portabilidad
        if tipo_activacion == 'portabilidad':
            if not portabilidad_detalle:
                raise serializers.ValidationError({
                    'portabilidad_detalle': _("Debe proporcionar los datos de portabilidad para activaciones de tipo portabilidad.")
                })
            if tipo_producto not in ['SIM', 'ESIM']:
                raise serializers.ValidationError({
                    'tipo_producto': _("Las portabilidades solo son válidas para SIM o eSIM.")
                })
        elif portabilidad_detalle:
            raise serializers.ValidationError({
                'portabilidad_detalle': _("Los datos de portabilidad solo son válidos para activaciones de tipo portabilidad.")
            })

        # Validar oferta visible para el usuario
        if not self._is_oferta_visible(oferta, usuario):
            logger.warning(f"Oferta {oferta.id} no visible para usuario {usuario.id}")
            raise serializers.ValidationError({
                'oferta_id': _("La oferta seleccionada no está disponible para este usuario.")
            })

        # Validar ICCID duplicado
        if Activacion.objects.filter(iccid=attrs.get('iccid')).exists():
            logger.warning(f"Intento de crear activación con ICCID duplicado: {attrs.get('iccid')}")
            raise serializers.ValidationError({
                'iccid': _("El ICCID ya está registrado en otra activación.")
            })

        # Validar distribuidor_asignado según rol
        if usuario.rol == ROLE_DISTRIBUIDOR:
            if distribuidor and distribuidor != usuario:
                logger.warning(f"Distribuidor {usuario.id} intentó asignar activación a otro distribuidor {distribuidor.id}")
                raise serializers.ValidationError({
                    'distribuidor_asignado': _("Un distribuidor solo puede asignarse a sí mismo como distribuidor asignado.")
                })
            attrs['distribuidor_asignado'] = usuario
        elif usuario.rol == ROLE_VENDEDOR:
            expected_distribuidor = self._get_distribuidor_asignado(usuario)
            if distribuidor and distribuidor != expected_distribuidor:
                logger.warning(f"Vendedor {usuario.id} intentó asignar activación a distribuidor no asociado {distribuidor.id}")
                raise serializers.ValidationError({
                    'distribuidor_asignado': _("El distribuidor asignado no coincide con el distribuidor del vendedor.")
                })
            attrs['distribuidor_asignado'] = expected_distribuidor
        # Admin puede especificar cualquier distribuidor o dejar nulo

        return attrs

    def _is_oferta_visible(self, oferta: Oferta, usuario: User) -> bool:
        """
        Verifica si la oferta es visible para el usuario solicitante.
        """
        # Implementar lógica real según modelo Oferta
        # Ejemplo: oferta.distribuidor == usuario o oferta.usuarios_visibles.contains(usuario)
        return oferta.activo  # Simplificado para ejemplo

    def create(self, validated_data):
        """
        Crea una activación y su detalle de portabilidad si aplica.
        Asigna automáticamente distribuidor_asignado según rol del usuario.
        """
        portabilidad_data = validated_data.pop('portabilidad_detalle', None)
        oferta = validated_data.pop('oferta_id')
        usuario = validated_data['usuario_solicita']

        # Asignar tipo de producto según oferta
        validated_data['tipo_producto'] = self._infer_tipo_producto(oferta)

        # Asignar precios según oferta y usuario
        validated_data['precio_costo'] = oferta.client_price or Decimal('0.00')
        validated_data['precio_final'] = oferta.eu_price or Decimal('0.00')
        validated_data['ganancia_calculada'] = validated_data['precio_final'] - validated_data['precio_costo']

        try:
            activacion = Activacion.objects.create(**validated_data)
            logger.info(
                f"Activación creada: ID={activacion.id}, ICCID={activacion.iccid}, "
                f"Usuario={usuario.username}, Rol={usuario.rol}"
            )

            if portabilidad_data:
                PortabilidadDetalle.objects.create(activacion=activacion, **portabilidad_data)
                logger.debug(f"Detalle de portabilidad creado para activación {activacion.id}")

            return activacion

        except Exception as e:
            logger.error(
                f"Error creando activación para usuario {usuario.username}: {str(e)}",
                exc_info=True
            )
            raise

    def _infer_tipo_producto(self, oferta: Oferta) -> str:
        """
        Infiere el tipo de producto según la oferta.
        """
        product_type_map = {
            'mobility': 'SIM',
            'mifi': 'MIFI',
            'internet_hogar': 'HBB',
            'iot': 'IOT',
            'esim': 'ESIM'
        }
        inferred_type = product_type_map.get(oferta.product_type, 'SIM')
        if inferred_type not in [choice[0] for choice in Activacion.PRODUCTOS]:
            logger.warning(f"Tipo de producto desconocido en oferta {oferta.id}: {oferta.product_type}")
            raise serializers.ValidationError(
                _("Tipo de producto desconocido para la oferta seleccionada."),
                code='invalid_oferta_product_type'
            )
        return inferred_type

    def _get_distribuidor_asignado(self, vendedor: User) -> User:
        """
        Obtiene el distribuidor asignado a un vendedor.
        """
        try:
            relacion = DistribuidorVendedor.objects.get(vendedor=vendedor)
            if relacion.distribuidor.rol != ROLE_DISTRIBUIDOR:
                logger.error(f"Distribuidor asignado a vendedor {vendedor.id} no tiene rol correcto")
                raise serializers.ValidationError(
                    _("El distribuidor asociado no tiene el rol correcto."),
                    code='invalid_distribuidor_role'
                )
            return relacion.distribuidor
        except DistribuidorVendedor.DoesNotExist:
            logger.error(f"Vendedor {vendedor.id} no está asignado a ningún distribuidor")
            raise serializers.ValidationError(
                _("El vendedor no está asignado a un distribuidor."),
                code='no_distribuidor'
            )

class ActivacionResponseSerializer(serializers.ModelSerializer):
    """
    Serializador para respuestas de activaciones.
    Personaliza la salida para incluir datos calculados o adicionales.
    """
    portabilidad_detalle = PortabilidadDetalleSerializer(read_only=True)
    oferta_nombre = serializers.CharField(source='oferta_id.nombre', read_only=True)
    usuario_solicita_nombre = serializers.CharField(source='usuario_solicita.username', read_only=True)
    distribuidor_asignado_nombre = serializers.CharField(
        source='distribuidor_asignado.username', read_only=True, allow_null=True
    )

    class Meta:
        model = Activacion
        fields = [
            'id',
            'iccid',
            'cliente_nombre',
            'cliente_email',
            'telefono_contacto',
            'tipo_activacion',
            'tipo_producto',
            'estado',
            'numero_asignado',
            'fecha_solicitud',
            'fecha_activacion',
            'precio_final',
            'oferta_nombre',
            'portabilidad_detalle',
            'usuario_solicita_nombre',
            'distribuidor_asignado_nombre',
        ]
        read_only_fields = fields