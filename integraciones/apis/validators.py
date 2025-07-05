"""
integraciones.apis.validators
----------------------------
Validation utilities for Addinteli API payloads and error mapping.
"""

from typing import Dict, Type, Any
from pydantic import BaseModel, ValidationError
from django.core.exceptions import ValidationError as DjangoValidationError

from .constants import ERROR_CODES

def validate(payload: Dict, schema: Type[BaseModel]) -> BaseModel:
    """
    Validate a payload against a Pydantic schema and return the validated instance.

    Args:
        payload (Dict): Data to validate.
        schema (Type[BaseModel]): Pydantic schema class.

    Returns:
        BaseModel: Validated Pydantic model instance.

    Raises:
        DjangoValidationError: If validation fails, with a user-friendly message.
    """
    try:
        return schema(**payload)
    except ValidationError as e:
        error_messages = [str(err) for err in e.errors()]
        raise DjangoValidationError(f"Invalid payload: {', '.join(error_messages)}")

def map_error(error_code: int) -> str:
    """
    Map an Addinteli error code to its description.

    Args:
        error_code (int): Error code from API response.

    Returns:
        str: Human-readable error message in Spanish.
    """
    return ERROR_CODES.get(error_code, f"Error desconocido (código: {error_code})")