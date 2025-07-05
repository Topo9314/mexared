"""
integraciones.apis.addinteli_logs
--------------------------------
Structured logging utilities for Addinteli API interactions.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

def mask_msisdn(msisdn: Optional[str]) -> Optional[str]:
    """
    Mask MSISDN to show only the last 4 digits for security in logs.

    Args:
        msisdn (Optional[str]): Phone number to mask.

    Returns:
        Optional[str]: Masked MSISDN (e.g., 'XXXXXX1234') or None.
    """
    if not msisdn:
        return None
    return "XXXXXX" + msisdn[-4:]

def log_solicitud(
    endpoint: str,
    method: str,
    payload: Optional[Dict],
    status_code: int,
    response: Dict[str, Any],
    time_ms: int,
) -> None:
    """
    Log an API request with structured JSON format.

    Args:
        endpoint (str): API endpoint called.
        method (str): HTTP method used.
        payload (Optional[Dict]): Request payload (sensitive fields masked).
        status_code (int): HTTP status code.
        response (Dict[str, Any]): API response.
        time_ms (int): Request duration in milliseconds.
    """
    log_data = {
        "time_iso": datetime.utcnow().isoformat(),
        "endpoint": endpoint,
        "method": method,
        "status_code": status_code,
        "time_ms": time_ms,
        "payload": json.dumps(
            {
                k: mask_msisdn(v) if k == "msisdn" else v
                for k, v in (payload or {}).items()
            },
            ensure_ascii=False,
        )[:2048] + ("..." if len(json.dumps(payload or {}, ensure_ascii=False)) > 2048 else ""),
        "response": response,
    }
    logger.info(json.dumps(log_data, ensure_ascii=False))