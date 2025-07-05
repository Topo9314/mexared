"""
integraciones.apis.tests.test_recargas
-------------------------------------
Unit tests for recharge operations in addinteli_recargas.
"""

import json
import pytest
import responses
from decimal import Decimal
from django.core.exceptions import ValidationError
from rest_framework.exceptions import APIException
from django.conf import settings
from integraciones.apis.addinteli_recargas import realizar_recarga, activar_paquete
from integraciones.apis.constants import ENDPOINTS
from integraciones.apis.schemas import RecargaPayload

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
def test_realizar_recarga_success(base_url):
    """Test successful recharge."""
    payload = {
        "msisdn": "1234567890",
        "monto": Decimal("100.00"),
    }
    mock_response = {
        "result": {
            "response": "Successful recharge",
            "reference_id": "API.1234567890.TEST",
            "msisdn": "1234567890",
            "altan_id": "123456789"
        }
    }
    responses.add(
        responses.POST,
        f"{base_url}{ENDPOINTS['PURCHASE']}",
        json=mock_response,
        status=200,
        json_params={"cls": DecimalEncoder}
    )
    
    result = realizar_recarga(payload)
    assert result == mock_response
    assert len(responses.calls) == 1

@responses.activate
def test_activar_paquete_success(base_url):
    """Test successful extended plan activation."""
    payload = {
        "msisdn": "1234567890",
        "plan_name": "MEXA FLASH 500 MB",
    }
    mock_response = {
        "result": {
            "response": "Successful extended plan activation",
            "reference_id": "API.1234567890.TEST",
            "msisdn": "1234567890",
            "altan_id": "123456789"
        }
    }
    responses.add(
        responses.POST,
        f"{base_url}{ENDPOINTS['PURCHASE_EXTENDED']}",
        json=mock_response,
        status=200,
        json_params={"cls": DecimalEncoder}
    )
    
    result = activar_paquete(payload)
    assert result == mock_response
    assert len(responses.calls) == 1

@responses.activate
def test_realizar_recarga_insufficient_balance(base_url):
    """Test recharge failure due to insufficient balance (error 1009)."""
    payload = {
        "msisdn": "1234567890",
        "monto": Decimal("100.00"),
    }
    responses.add(
        responses.POST,
        f"{base_url}{ENDPOINTS['PURCHASE']}",
        json={"error_code": 1009, "message": "No se cuenta con saldo suficiente"},
        status=400,
        json_params={"cls": DecimalEncoder}
    )
    
    with pytest.raises(APIException, match="No se cuenta con saldo suficiente"):
        realizar_recarga(payload)

def test_realizar_recarga_invalid_amount():
    """Test recharge with invalid amount."""
    payload = {
        "msisdn": "1234567890",
        "monto": Decimal("-10.00"),  # Invalid: negative
    }
    with pytest.raises(ValidationError, match="Invalid payload"):
        realizar_recarga(payload)