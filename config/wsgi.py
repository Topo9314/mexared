"""
🌐 WSGI ENTRYPOINT - MexaRed

Punto de entrada para servidores WSGI compatibles (Gunicorn, uWSGI, etc.).
Carga el entorno configurado desde .env (dev o prod).
"""

import os
from django.core.wsgi import get_wsgi_application
from decouple import config

# Establece el módulo de configuración de Django según el entorno
os.environ.setdefault(
    'DJANGO_SETTINGS_MODULE',
    config('DJANGO_SETTINGS_MODULE', default='config.settings.prod')
)

application = get_wsgi_application()
