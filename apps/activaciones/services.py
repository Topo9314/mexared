"""
services.py - Lógica de negocio para el módulo de activaciones en MexaRed.
Centraliza la validación, procesamiento y comunicación con la API de Addinteli.
Soporta activaciones de nuevas líneas, portabilidades y productos específicos.
Diseñado para ser robusto, seguro, escalable y con trazabilidad completa.
"""

import logging
import uuid
import requests
from typing import Dict, Any
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from retry import retry
from decimal import Decimal
from .models import Activacion, HistorialActivacion, ActivacionErrorLog
from apps.users.models import User, ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR
from apps.wallet.models import Wallet
from apps.transacciones.models import Transaccion
from apps.ofertas.models import Oferta
# from integraciones.apis.addinteli import AddinteliAPI
from django.conf import settings

# Configuración de logging para auditoría
logger = logging.getLogger(__name__)

class ActivacionService:
    """
    Servicio principal para procesar activaciones.
    Encapsula validaciones, interacción con Addinteli y manejo financiero.
    """
    def __init__(self):
        self.addinteli_api = AddinteliAPI()

    @transaction.atomic
    def procesar_activacion(self, activacion: Activacion) -> Dict[str, Any]:
        """
        Procesa una activación completa:
        - Valida ICCID contra Addinteli.
        - Verifica y descuenta saldo del wallet.
        - Llama a la API de Addinteli.
        - Registra respuesta y actualiza estado.
        - Crea historial y transacciones financieras.

        Args:
            activacion: Instancia de Activacion a procesar.

        Returns:
            Dict con resultado de la operación y datos de Addinteli.

        Raises:
            ValidationError: Si falla alguna validación o procesamiento.
        """
        try:
            # Validar tipo de activación
            self._validar_tipo_activacion(activacion)

            # Validar usuario solicitante
            self._validar_usuario(activacion)

            # Validar duplicados
            self._validar_iccid_duplicado(activacion)

            # Validar ICCID
            self.validar_iccid_con_addinteli(activacion.iccid)

            # Validar y descontar saldo
            self.validar_saldo_y_descontar(activacion)

            # Llama a API de Addinteli
            response = self.llamar_api_addinteli(activacion)

            # Actualizar activación
            activacion.respuesta_addinteli = response.get('result', {})  # Guardar solo el result
            activacion.estado = 'exitosa'
            activacion.numero_asignado = response.get('result', {}).get('msisdn')
            activacion.fecha_activacion = timezone.now()
            activacion.save()

            # Registrar historial
            HistorialActivacion.objects.create(
                activacion=activacion,
                accion='procesar_activacion',
                mensaje=_("Activación procesada exitosamente"),
                usuario=activacion.usuario_solicita,
                details={'api_response': response.get('result', {})}
            )

            logger.info(
                f"Activación {activacion.id} procesada por {activacion.usuario_solicita.username} "
                f"como {activacion.tipo_activacion}: ICCID={activacion.iccid}, "
                f"MSISDN={activacion.numero_asignado}"
            )

            return {
                'status': 'success',
                'activacion': activacion,
                'addinteli_response': response
            }

        except Exception as e:
            # Registrar error
            ActivacionErrorLog.objects.create(
                iccid=activacion.iccid,
                error_tipo=type(e).__name__,
                detalle=str(e),
                activacion=activacion
            )
            activacion.estado = 'fallida'
            activacion.save()

            # Registrar historial de fallo
            HistorialActivacion.objects.create(
                activacion=activacion,
                accion='procesar_activacion_fallida',
                mensaje=_("Fallo en procesamiento de activación: %(error)s") % {'error': str(e)},
                usuario=activacion.usuario_solicita,
                details={'error': str(e)}
            )

            logger.error(
                f"Error procesando activación {activacion.id} (ICCID={activacion.iccid}): {str(e)}",
                exc_info=True
            )

            raise ValidationError(str(e))

    def _validar_tipo_activacion(self, activacion: Activacion) -> None:
        """
        Valida que el tipo de activación sea permitido.

        Args:
            activacion: Instancia de Activacion.

        Raises:
            ValidationError: Si el tipo de activación no es válido.
        """
        valid_types = ['nueva', 'portabilidad', 'especifica']
        if activacion.tipo_activacion not in valid_types:
            raise ValidationError(
                _("Tipo de activación inválido: %(tipo)s") % {'tipo': activacion.tipo_activacion},
                code='invalid_activacion_type'
            )

    def _validar_usuario(self, activacion: Activacion) -> None:
        """
        Valida que el usuario solicitante tenga un rol permitido.

        Args:
            activacion: Instancia de Activacion.

        Raises:
            ValidationError: Si el rol no es válido.
        """
        if not activacion.usuario_solicita:
            raise ValidationError(_("El usuario solicitante es obligatorio."))
        if activacion.usuario_solicita.rol not in [ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR]:
            raise ValidationError(
                _("El usuario solicitante debe ser Admin, Distribuidor o Vendedor."),
                code='invalid_role'
            )

    def _validar_iccid_duplicado(self, activacion: Activacion) -> None:
        """
        Valida que el ICCID no esté duplicado en otras activaciones.

        Args:
            activacion: Instancia de Activacion.

        Raises:
            ValidationError: Si el ICCID ya está registrado.
        """
        if Activacion.objects.filter(iccid=activacion.iccid).exclude(id=activacion.id).exists():
            raise ValidationError(
                _("El ICCID ya está registrado en otra activación."),
                code='duplicate_iccid'
            )

    @retry(tries=3, delay=2, exceptions=(requests.Timeout, requests.ConnectionError))
    def validar_iccid_con_addinteli(self, iccid: str) -> Dict[str, Any]:
        """
        Valida el ICCID contra la API de Addinteli.

        Args:
            iccid: Identificador del chip.

        Returns:
            Dict con datos de validación.

        Raises:
            ValidationError: Si el ICCID no es válido o no pertenece a MexaRed.
        """
        try:
            response = self.addinteli_api.validate_iccid(iccid)
            if not response.get('result', {}).get('valid', False):
                raise ValidationError(
                    _("El ICCID no es válido o no pertenece a MexaRed."),
                    code='invalid_iccid'
                )
            return response
        except Exception as e:
            logger.error(f"Error validando ICCID {iccid}: {str(e)}")
            raise ValidationError(str(e))

    @transaction.atomic
    def validar_saldo_y_descontar(self, activacion: Activacion) -> None:
        """
        Verifica saldo suficiente en el wallet y registra transacción de débito.

        Args:
            activacion: Instancia de Activacion.

        Raises:
            ValidationError: Si el saldo es insuficiente.
        """
        usuario = activacion.usuario_solicita
        costo = Decimal(str(activacion.precio_costo))

        # Bloquear wallet para evitar condiciones de carrera
        wallet = Wallet.objects.select_for_update().get(user=usuario)
        if wallet.balance < costo:
            raise ValidationError(
                _("Saldo insuficiente: %(disponible)s MXN disponible, se requieren %(requerido)s MXN"),
                params={'disponible': wallet.balance, 'requerido': costo},
                code='insufficient_balance'
            )

        # Descontar saldo
        wallet.balance -= costo
        wallet.save()

        # Registrar transacción
        Transaccion.objects.create(
            wallet=wallet,
            tipo='DEBITO',
            monto=costo,
            referencia=str(activacion.id),
            operacion_id=uuid.uuid4(),
            fecha=timezone.now(),
            creado_por=usuario,
            conciliado=False,
            descripcion=_("Débito por activación ICCID %(iccid)s") % {'iccid': activacion.iccid}
        )

        logger.info(
            f"Activación {activacion.id}: Saldo descontado para ICCID={activacion.iccid}, "
            f"Monto={costo}, Usuario={usuario.username}, Nuevo saldo={wallet.balance}"
        )

    def llamar_api_addinteli(self, activacion: Activacion) -> Dict[str, Any]:
        """
        Llama a la API de Addinteli para realizar la activación.

        Args:
            activacion: Instancia de Activacion.

        Returns:
            Dict con la respuesta de Addinteli.

        Raises:
            ValidationError: Si la llamada falla.
        """
        try:
            # Buscar oferta disponible para el usuario
            usuario = activacion.usuario_solicita
            oferta = Oferta.objects.filter(
                activo=True,
                # Placeholder para relación con usuarios visibles
                # Ejemplo: usuarios_visibles=usuario o distribuidor=activacion.distribuidor_asignado
            ).first()
            if not oferta:
                raise ValidationError(_("No hay ofertas disponibles para este usuario."), code='no_oferta')

            logger.info(
                f"Activación {activacion.id}: Usando oferta {oferta.nombre} - {oferta.codigo_addinteli}"
            )

            payload = {
                'msisdn_iccid': activacion.iccid,
                'plan_name': oferta.codigo_addinteli,
                'name': activacion.cliente_nombre,
                'email': getattr(activacion, 'cliente_email', 'no_email'),
                'address': 'N/A',
                'contact_phone': activacion.telefono_contacto,
                'imei': activacion.imei or None
            }

            # Soporte para campos personalizados
            extra_payload = getattr(activacion, 'extra_payload', {})
            payload.update(extra_payload)

            if activacion.tipo_activacion == 'portabilidad':
                port = activacion.portabilidad_detalle
                payload.update({
                    'msisdn_to_port': port.numero_actual,
                    'nip': port.nip_portabilidad,
                    'curp': port.curp or None,
                    'compania_origen': port.compañia_origen
                })
                response = self.addinteli_api.portability_request(
                    activacion.iccid, port.numero_actual, port.nip_portabilidad,
                    oferta.codigo_addinteli, payload
                )
            else:
                response = self.addinteli_api.activate_line(
                    activacion.iccid, oferta.codigo_addinteli, payload
                )

            if response.get('result', {}).get('response') not in ['Successful activation', 'Successful portability']:
                raise ValidationError(
                    _("Error en Addinteli: %(mensaje)s") % {
                        'mensaje': response.get('result', {}).get('message', 'Unknown error')
                    },
                    code='addinteli_error'
                )

            return response

        except Exception as e:
            logger.error(f"Error en llamada a Addinteli para ICCID {activacion.iccid}: {str(e)}")
            raise ValidationError(str(e))