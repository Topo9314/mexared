"""
integraciones.apis.schemas
-------------------------
Pydantic models for validating Addinteli API payloads.
"""

from decimal import Decimal
from typing import Optional
from typing import Literal
from pydantic import BaseModel, Field, constr, validator
import re

class Config:
    """Pydantic configuration to reject extra fields."""
    extra = "forbid"

class LineaPayloadBase(BaseModel):
    """Base payload for operations requiring MSISDN and distributor credentials."""
    msisdn: constr(regex=r"^\d{10}$") = Field(..., description="10-digit phone number")
    distributor_id: constr(regex=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$") = Field(..., description="Distributor UUID")
    wallet_id: constr(regex=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$") = Field(..., description="Wallet UUID")

    class Config:
        extra = "forbid"

class ImeiSchema(BaseModel):
    """Payload for IMEI-related operations."""
    imei: constr(regex=r"^\d{14,15}$") = Field(..., description="14-15 digit IMEI")
    msisdn: constr(regex=r"^\d{10}$") = Field(..., description="10-digit phone number")
    distributor_id: constr(regex=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$") = Field(..., description="Distributor UUID")
    wallet_id: constr(regex=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$") = Field(..., description="Wallet UUID")

    class Config:
        extra = "forbid"

class ActivarPayload(LineaPayloadBase):
    """Payload for line activation."""
    plan_name: Literal[
        "MEXA FLASH 500 MB",
        "MEXA SEMANA 2GB",
        "MEXA QUINCENA 5 GB",
        "MEXA BASICO 2GB - 30 DIAS",
        "MEXA LITE 4GB - 30 DIAS",
        "MEXA PLUS 12 GB - 30 DIAS",
        "MEXA EPICO 24 GB - 30 DIAS",
        "MEXA ANTIGUO 40 GB - NO COMPARTE",
        "MEXA TITAN 35 GB - 30 DIAS",
        "MEXA INMORTAL 50 GB - 30 DIAS",
        "MEXA MINI 3 GB - ANUAL",
        "MEXA LEGADO 24 GB - 6 MESES",
        "MEXA SLIM 5 GB - ANUAL",
        "MEXA ETERNO 24 GB - ANUAL",
        "MIFI SHARE 5GB",
        "MIFI SHARE 10GB",
        "MIFI SHARE 20GB",
        "MIFI SHARE 30GB",
        "MIFI SHARE 50GB",
    ] = Field(..., description="Name of the plan to activate")
    name: str = Field(..., description="User's full name")
    email: str = Field(..., description="User's email or 'no_email'")
    address: str = Field(..., description="User's address")
    coordinates: Optional[str] = Field(None, description="Coordinates for HBB, if applicable")

    @validator("email")
    def validate_email(cls, v):
        """Ensure email is valid or 'no_email'."""
        if v != "no_email" and not re.match(r"[^@]+@[^@]+\.[^@]+", v):
            raise ValueError("Invalid email format")
        return v

    class Config:
        extra = "forbid"

class SuspenderPayload(LineaPayloadBase):
    """Payload for suspending a line."""
    class Config:
        extra = "forbid"

class CambiarPlanPayload(LineaPayloadBase):
    """Payload for changing a line's primary plan."""
    plan_name: Literal[
        "MEXA FLASH 500 MB",
        "MEXA SEMANA 2GB",
        "MEXA QUINCENA 5 GB",
        "MEXA BASICO 2GB - 30 DIAS",
        "MEXA LITE 4GB - 30 DIAS",
        "MEXA PLUS 12 GB - 30 DIAS",
        "MEXA EPICO 24 GB - 30 DIAS",
        "MEXA ANTIGUO 40 GB - NO COMPARTE",
        "MEXA TITAN 35 GB - 30 DIAS",
        "MEXA INMORTAL 50 GB - 30 DIAS",
        "MEXA MINI 3 GB - ANUAL",
        "MEXA LEGADO 24 GB - 6 MESES",
        "MEXA SLIM 5 GB - ANUAL",
        "MEXA ETERNO 24 GB - ANUAL",
        "MIFI SHARE 5GB",
        "MIFI SHARE 10GB",
        "MIFI SHARE 20GB",
        "MIFI SHARE 30GB",
        "MIFI SHARE 50GB",
    ] = Field(..., description="New plan name")

    class Config:
        extra = "forbid"

class RecargaPayload(LineaPayloadBase):
    """Payload for recharging a line."""
    monto: Decimal = Field(..., gt=0, description="Recharge amount in MXN")

    class Config:
        extra = "forbid"