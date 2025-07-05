"""
integraciones.apis.base
----------------------
Core HTTP client for Addinteli API interactions, handling authentication, retries, and structured logging.
"""

import json
import logging
import time
from typing import Dict, Any, Optional
from urllib3.util.retry import Retry
import requests
from django.conf import settings
from rest_framework.exceptions import APIException

from .addinteli_logs import log_solicitud
from .validators import map_error

logger = logging.getLogger(__name__)

class AddinteliAPIClient:
    """Client for making authenticated HTTP requests to the Addinteli API."""
    
    DEFAULT_TIMEOUT = 10  # seconds
    RETRY_STRATEGY = Retry(
        total=getattr(settings, "ADDINTELI_RETRY_TOTAL", 3),
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT", "DELETE"],
    )

    def __init__(self):
        """
        Initialize the API client with environment-specific configuration.
        """
        self.mode = getattr(settings, "ADDINTELI_API_MODE", "sandbox")
        self.base_url = settings.ADDINTELI_API_URL.get(self.mode)
        self.token = settings.ADDINTELI_API_TOKEN.get(self.mode)
        
        if not self.base_url or not self.token:
            raise ValueError(f"Missing API configuration for mode '{self.mode}'")

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "mexared/1.0"})
        adapter = requests.adapters.HTTPAdapter(max_retries=self.RETRY_STRATEGY)
        self.session.mount("https://", adapter)

    def _headers(self) -> Dict[str, str]:
        """
        Generate headers for API requests.

        Returns:
            Dict[str, str]: Headers including Authorization, Content-Type, and User-Agent.
        """
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "mexared/1.0",
        }

    def _request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Generic HTTP request handler with logging and error handling.

        Args:
            method (str): HTTP method (GET, POST, PUT, DELETE).
            endpoint (str): API endpoint path (e.g., '/activations').
            data (Dict, optional): Request payload for POST/PUT.

        Returns:
            Dict[str, Any]: JSON response from the API.

        Raises:
            APIException: If the request fails or the response contains an error.
        """
        url = f"{self.base_url}{endpoint}"
        start_time = time.time()
        
        try:
            response = self.session.request(
                method=method,
                url=url,
                headers=self._headers(),
                json=data,
                timeout=self.DEFAULT_TIMEOUT,
            )
            response.raise_for_status()
            
            # Check Content-Type before parsing JSON
            content_type = response.headers.get("Content-Type", "")
            if "application/json" not in content_type:
                raise APIException(f"Unexpected response format: {content_type}")

            response_data = response.json()
            
            # Log successful request
            log_solicitud(
                endpoint=endpoint,
                method=method,
                payload=data,
                status_code=response.status_code,
                response=response_data,
                time_ms=int((time.time() - start_time) * 1000),
            )
            return response_data

        except requests.exceptions.RequestException as e:
            # Log error and raise APIException with mapped error message
            error_code = getattr(e.response, "status_code", None)
            error_data = {
                "endpoint": endpoint,
                "method": method,
                "status_code": error_code,
                "error": str(e),
            }
            if error_code and hasattr(e.response, "json"):
                try:
                    error_response = e.response.json()
                    error_code = error_response.get("error_code")
                    if error_code:
                        error_data["error"] = map_error(error_code)
                except ValueError:
                    pass
            logger.error(json.dumps(error_data, ensure_ascii=False))
            raise APIException(f"Addinteli API error: {error_data['error']}")

    def get(self, endpoint: str) -> Dict[str, Any]:
        """
        Perform a GET request to the Addinteli API.

        Args:
            endpoint (str): API endpoint path.

        Returns:
            Dict[str, Any]: JSON response.
        """
        return self._request("GET", endpoint)

    def post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform a POST request to the Addinteli API.

        Args:
            endpoint (str): API endpoint path.
            data (Dict): Request payload.

        Returns:
            Dict[str, Any]: JSON response.
        """
        return self._request("POST", endpoint, data)

    def put(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform a PUT request to the Addinteli API.

        Args:
            endpoint (str): API endpoint path.
            data (Dict): Request payload.

        Returns:
            Dict[str, Any]: JSON response.
        """
        return self._request("PUT", endpoint, data)

    def delete(self, endpoint: str) -> Dict[str, Any]:
        """
        Perform a DELETE request to the Addinteli API.

        Args:
            endpoint (str): API endpoint path.

        Returns:
            Dict[str, Any]: JSON response.
        """
        return self._request("DELETE", endpoint)