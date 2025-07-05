"""
integraciones.apis.addinteli_utils
---------------------------------
Utility functions for miscellaneous Addinteli API operations (device compatibility, IMEI, city catalog).
"""

from typing import Dict, Any
from django.conf import settings
from django.core.exceptions import ValidationError

from .base import AddinteliAPIClient
from .constants import ENDPOINTS
from .schemas import ImeiSchema, LineaPayloadBase
from .validators import validate

client = AddinteliAPIClient()

def validar_compatibilidad_equipo(imei: str) -> Dict[str, Any]:
    """
    Check device compatibility via Addinteli API.

    Args:
        imei (str): Device IMEI (14-15 digits).

    Returns:
        Dict[str, Any]: API response with compatibility details.

    Raises:
        ValidationError: If payload is invalid.
        APIException: If API call fails.
    """
    payload = {
        "imei": imei,
        "distributor_id": settings.ADDINTELI_DISTRIBUTOR_ID,
        "wallet_id": settings.ADDINTELI_WALLET_ID,
    }
    validate(payload, ImeiSchema)  # Minimal validation without msisdn
    return client.post(ENDPOINTS["CHECK_DEVICE"], payload)

def bloquear_imei(imei: str, msisdn: str) -> Dict[str, Any]:
    """
    Lock an IMEI via Addinteli API.

    Args:
        imei (str): Device IMEI (14-15 digits).
        msisdn (str): Phone number.

    Returns:
        Dict[str, Any]: API response with result, reference_id, msisdn, altan_id.

    Raises:
        ValidationError: If payload is invalid.
        APIException: If API call fails.
    """
    payload = {
        "imei": imei,
        "msisdn": msisdn,
        "distributor_id": settings.ADDINTELI_DISTRIBUTOR_ID,
        "wallet_id": settings.ADDINTELI_WALLET_ID,
    }
    validate(payload, ImeiSchema)
    return client.post(ENDPOINTS["LOCK_IMEI"], payload)

def desbloquear_imei(imei: str, msisdn: str) -> Dict[str, Any]:
    """
    Unlock an IMEI via Addinteli API.

    Args:
        imei (str): Device IMEI (14-15 digits).
        msisdn (str): Phone number.

    Returns:
        Dict[str, Any]: API response with result, reference_id, msisdn, altan_id.

    Raises:
        ValidationError: If payload is invalid.
        APIException: If API call fails.
    """
    payload = {
        "imei": imei,
        "msisdn": msisdn,
        "distributor_id": settings.ADDINTELI_DISTRIBUTOR_ID,
        "wallet_id": settings.ADDINTELI_WALLET_ID,
    }
    validate(payload, ImeiSchema)
    return client.post(ENDPOINTS["UNLOCK_IMEI"], payload)

def consultar_planes_disponibles() -> Dict[str, Any]:
    """
    Query available plans via Addinteli API.

    Returns:
        Dict[str, Any]: API response with plan details.

    Raises:
        APIException: If API call fails.
    """
    payload = {
        "distributor_id": settings.ADDINTELI_DISTRIBUTOR_ID,
        "wallet_id": settings.ADDINTELI_WALLET_ID,
    }
    validate(payload, LineaPayloadBase)  # Minimal validation
    return client.post(ENDPOINTS["PLANES_DISPONIBLES"], payload)

def consultar_catalogo_ciudades() -> Dict[str, Any]:
    """
    Query city catalog for region changes via Addinteli API.

    Returns:
        Dict[str, Any]: API response with city catalog.

    Raises:
        APIException: If API call fails.
    """
    payload = {
        "distributor_id": settings.ADDINTELI_DISTRIBUTOR_ID,
        "wallet_id": settings.ADDINTELI_WALLET_ID,
    }
    validate(payload, LineaPayloadBase)  # Minimal validation
    return client.post(ENDPOINTS["CHANGE_REGION"], payload)