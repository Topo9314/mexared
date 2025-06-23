"""
⚡ ASGI ENTRYPOINT - MexaRed

Soporte para WebSockets, HTTP2 y otros protocolos asíncronos.
Ideal para despliegue con Daphne, Uvicorn o plataformas como Render o Railway.
"""

import os
from django.core.asgi import get_asgi_application
from decouple import config

# Configuración dinámica del entorno (desarrollo o producción)
os.environ.setdefault(
    'DJANGO_SETTINGS_MODULE',
    config('DJANGO_SETTINGS_MODULE', default='config.settings.prod')
)

application = get_asgi_application()
