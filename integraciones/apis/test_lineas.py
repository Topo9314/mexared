"""
integraciones.apis.tests.test_lineas
-----------------------------------
Unit tests for line operations in addinteli_lineas.
"""

import json
import pytest
import responses
from decimal import Decimal
from django.core.exceptions import ValidationError
from rest_framework.exceptions import APIException
from django.conf import settings
from integraciones.apis.addinteli_lineas import activar_linea
from integraciones.apis.constants import ENDPOINTS
from integraciones.apis.schemas import ActivarPayload

class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder for Decimal."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)

@pytest.fixture(scope="session")
def base_url():
    """Fixture for Addinteli API base URL."""
    return settings.ADDINTELI_API_URL["prod"]

@responses.activate
def test_activar_linea_success(base_url):
    """Test successful line activation."""
    payload = {
        "msisdn": "1234567890",
        "plan_name": "MEXA FLASH 500 MB",
        "name": "Test User",
        "email": "test@example.com",
        "address": "123 Test St",
    }
    mock_response = {
        "result": {
            "response": "Successful activation",
            "reference_id": "API.1234567890.TEST",
            "msisdn": "1234567890",
            "altan_id": "123456789",
        }
    }
    responses.add(
        responses.POST,
        f"{base_url}{ENDPOINTS['ACTIVATION']}",
        json=mock_response,
        status=200,
        json_params={"cls": DecimalEncoder}
    )
    
    result = activar_linea(payload)
    assert result == mock_response
    assert len(responses.calls) == 1

@responses.activate
def test_activar_linea_insufficient_balance(base_url):
    """Test activation failure due to insufficient balance (error 1009)."""
    payload = {
        "msisdn": "1234567890",
        "plan_name": "MEXA FLASH 500 MB",
        "name": "Test User",
        "email": "test@example.com",
        "address": "123 Test St",
    }
    responses.add(
        responses.POST,
        f"{base_url}{ENDPOINTS['ACTIVATION']}",
        json={"error_code": 1009, "message": "No se cuenta con saldo suficiente"},
        status=400,
        json_params={"cls": DecimalEncoder}
    )
    
    with pytest.raises(APIException, match="No se cuenta con saldo suficiente"):
        activar_linea(payload)

@responses.activate
def test_activar_linea_timeout(base_url):
    """Test activation failure due to timeout."""
    payload = {
        "msisdn": "1234567890",
        "plan_name": "MEXA FLASH 500 MB",
        "name": "Test User",
        "email": "test@example.com",
        "address": "123 Test St",
    }
    responses.add(
        responses.POST,
        f"{base_url}{ENDPOINTS['ACTIVATION']}",
        body=TimeoutError("Request timed out")
    )
    
    with pytest.raises(APIException, match="Addinteli API error: Request timed out"):
        activar_linea(payload)

def test_activar_linea_invalid_payload():
    """Test activation with invalid payload."""
    payload = {
        "msisdn": "12345",  # Invalid: too short
        "plan_name": "MEXA FLASH 500 MB",
        "name": "Test User",
        "email": "test@example.com",
        "address": "123 Test St",
    }
    with pytest.raises(ValidationError, match="Invalid payload"):
        activar_linea(payload)