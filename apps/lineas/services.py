import os
import httpx
from django.conf import settings

def get_api_url():
    mode = os.getenv("API_MODE", "sandbox")
    return os.getenv("API_URL_PROD") if mode == "prod" else os.getenv("API_URL_SANDBOX")

def get_api_token():
    mode = os.getenv("API_MODE", "sandbox")
    return os.getenv("API_TOKEN_PROD") if mode == "prod" else os.getenv("API_TOKEN_SANDBOX")

def get_headers():
    return {
        "Authorization": f"Bearer {get_api_token()}",
        "Content-Type": "application/json",
    }

def consultar_lineas_iccid():
    url = f"{get_api_url()}lines"
    response = httpx.get(url, headers=get_headers(), timeout=10)
    response.raise_for_status()
    return response.json()

def suspender_linea(iccid):
    url = f"{get_api_url()}lines/suspend"
    response = httpx.post(url, headers=get_headers(), json={"iccid": iccid}, timeout=10)
    response.raise_for_status()
    return response.json()

def cancelar_linea(iccid):
    url = f"{get_api_url()}lines/cancel"
    response = httpx.post(url, headers=get_headers(), json={"iccid": iccid}, timeout=10)
    response.raise_for_status()
    return response.json()
