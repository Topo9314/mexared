"""
integraciones.apis.addinteli_lineas
----------------------------------
High-level services for line operations (activation, suspension, reactivation, plan change) against Addinteli API v8.0.
"""

from typing import Dict, Any
from django.conf import settings
from django.core.exceptions import ValidationError
from rest_framework.exceptions import APIException

from .base import AddinteliAPIClient
from .constants import ENDPOINTS
from .schemas import ActivarPayload, SuspenderPayload, CambiarPlanPayload
from .validators import validate

client = AddinteliAPIClient()

def activar_linea(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Activate a line via Addinteli API.

    Args:
        payload (Dict[str, Any]): Activation data (msisdn, plan_name, name, email, address, coordinates).

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
    validate(payload, ActivarPayload)
    return client.post(ENDPOINTS["ACTIVATION"], payload)

def suspender_linea(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Suspend a line via Addinteli API.

    Args:
        payload (Dict[str, Any]): Suspension data (msisdn).

    Returns:
        Dict[str, Any]: API response with result, reference_id, msisdn, altan_id.

    Raises:
        ValidationError: If payload is invalid.
        APIException: If API call fails, maps error 1027 to HTTP 409 Conflict.
    """
    payload = {
        **payload,
        "distributor_id": settings.ADDINTELI_DISTRIBUTOR_ID,
        "wallet_id": settings.ADDINTELI_WALLET_ID,
    }
    validated = validate(payload, SuspenderPayload)
    try:
        return client.post(ENDPOINTS["SUSPEND"], validated.dict())
    except APIException as e:
        if "1027" in str(e):  # Line already suspended
            raise APIException("Línea ya suspendida", code=409)
        raise

def reactivar_linea(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reactivate a suspended line via Addinteli API.

    Args:
        payload (Dict[str, Any]): Reactivation data (msisdn).

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
    validate(payload, SuspenderPayload)
    return client.post(ENDPOINTS["RESUME"], payload)

def cambiar_plan(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Change a line's primary plan via Addinteli API.

    Args:
        payload (Dict[str, Any]): Plan change data (msisdn, plan_name).

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
    validate(payload, CambiarPlanPayload)
    return client.post(ENDPOINTS["CHANGE_OFFER"], payload)

def consultar_bolsas(msisdn: str) -> Dict[str, Any]:
    """
    Query benefits (data, SMS, voice) for a line via Addinteli API.

    Args:
        msisdn (str): Phone number.

    Returns:
        Dict[str, Any]: API response with benefits details.

    Raises:
        ValidationError: If payload is invalid.
        APIException: If API call fails.
    """
    payload = {
        "msisdn": msisdn,
        "distributor_id": settings.ADDINTELI_DISTRIBUTOR_ID,
        "wallet_id": settings.ADDINTELI_WALLET_ID,
    }
    validate(payload, SuspenderPayload)  # Reuses SuspenderPayload as it only needs msisdn
    return client.post(ENDPOINTS["GET_BENEFITS_V3"], payload)