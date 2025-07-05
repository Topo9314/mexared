"""
integraciones.apis.addinteli_recargas
------------------------------------
High-level services for recharge operations (recharge, plan purchase, history, portability) against Addinteli API v8.0.
"""

from typing import Dict, Any
from django.conf import settings
from django.core.exceptions import ValidationError

from .base import AddinteliAPIClient
from .constants import ENDPOINTS
from .schemas import RecargaPayload, CambiarPlanPayload
from .validators import validate

client = AddinteliAPIClient()

def realizar_recarga(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Perform a recharge on a line via Addinteli API.

    Args:
        payload (Dict[str, Any]): Recharge data (msisdn, monto).

    Returns:
        Dict[str, Any]: API response with result, reference_id, msisdn, altan_id.

    Raises:
        ValidationError: If payload is invalid.
        APIException: If API call fails.
    """
    payload = {
        **payload,
        "distributor_id": settings.ADDINTELI_DISTRIBUTOR_ID,
        "wallet_id": settings.ADDINTELI_WALLET_ID,
    }
    validate(payload, RecargaPayload)
    return client.post(ENDPOINTS["PURCHASE"], payload)

def activar_paquete(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Activate an extended plan package via Addinteli API.

    Args:
        payload (Dict[str, Any]): Package activation data (msisdn, plan_name).

    Returns:
        Dict[str, Any]: API response with result, reference_id, msisdn, altan_id.

    Raises:
        ValidationError: If payload is invalid.
        APIException: If API call fails.
    """
    payload = {
        **payload,
        "distributor_id": settings.ADDINTELI_DISTRIBUTOR_ID,
        "wallet_id": settings.ADDINTELI_WALLET_ID,
    }
    validate(payload, CambiarPlanPayload)  # Reuses plan_name validation
    return client.post(ENDPOINTS["PURCHASE_EXTENDED"], payload)

def consultar_paquetes(msisdn: str) -> Dict[str, Any]:
    """
    Query available plans for a line via Addinteli API.

    Args:
        msisdn (str): Phone number.

    Returns:
        Dict[str, Any]: API response with available plans.

    Raises:
        ValidationError: If payload is invalid.
        APIException: If API call fails.
    """
    payload = {
        "msisdn": msisdn,
        "distributor_id": settings.ADDINTELI_DISTRIBUTOR_ID,
        "wallet_id": settings.ADDINTELI_WALLET_ID,
    }
    validate(payload, CambiarPlanPayload)  # Reuses minimal payload
    return client.post(ENDPOINTS["PLANES_DISPONIBLES"], payload)

def historial_recargas(msisdn: str) -> Dict[str, Any]:
    """
    Query recharge history for a line via Addinteli API.

    Args:
        msisdn (str): Phone number.

    Returns:
        Dict[str, Any]: API response with recharge history.

    Raises:
        ValidationError: If payload is invalid.
        APIException: If API call fails.
    """
    payload = {
        "msisdn": msisdn,
        "distributor_id": settings.ADDINTELI_DISTRIBUTOR_ID,
        "wallet_id": settings.ADDINTELI_WALLET_ID,
    }
    validate(payload, CambiarPlanPayload)  # Reuses minimal payload
    return client.post(ENDPOINTS["PURCHASE_SEARCH"], payload)

def iniciar_portabilidad(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initiate portability for a line via Addinteli API.

    Args:
        payload (Dict[str, Any]): Portability data (msisdn, port_in, nip, curp).

    Returns:
        Dict[str, Any]: API response with result, reference_id, altan_id.

    Raises:
        ValidationError: If payload is invalid.
        APIException: If API call fails.
    """
    payload = {
        **payload,
        "distributor_id": settings.ADDINTELI_DISTRIBUTOR_ID,
        "wallet_id": settings.ADDINTELI_WALLET_ID,
    }
    validate(payload, CambiarPlanPayload)  # Extend with specific portability schema if needed
    return client.post(ENDPOINTS["PORTABILITY"], payload)