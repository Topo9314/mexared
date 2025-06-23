"""
Configuración para el entorno de desarrollo de MexaRed.
Extiende base.py con ajustes específicos para pruebas y desarrollo.
"""

from .base import *
from decouple import config

# 🔹 1. DEBUG Y HOSTS
DEBUG = True
ALLOWED_HOSTS = ['*']  # Desarrollo: permite todos los hosts para máxima flexibilidad

# 🔹 2. BASE DE DATOS (SQLite para pruebas locales rápidas)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# 🔹 OPCIONAL: PostgreSQL (descomentar si lo usas en desarrollo)
"""
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('POSTGRES_DB', default='mexared_dev'),
        'USER': config('POSTGRES_USER', default='postgres'),
        'PASSWORD': config('POSTGRES_PASSWORD', default='password'),
        'HOST': config('POSTGRES_HOST', default='localhost'),
        'PORT': config('POSTGRES_PORT', default='5432'),
    }
}
"""

# 🔹 3. EMAIL (usa consola para evitar envío real)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# 🔹 4. CORS CONFIGURATION
# Solo permite orígenes válidos con esquema http:// o https://
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",  # ⚠️ Asegúrate de que este sea tu frontend
    # Agrega más si trabajas con varios entornos locales
]

# 🔹 5. CONFIGURACIÓN DE SEGURIDAD (reducida en desarrollo)
SECURE_SSL_REDIRECT = False
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False

# 🔹 6. STATICFILES CONFIGURATION
# Asegúrate de que la carpeta "static" exista en la raíz del proyecto
STATICFILES_DIRS = [
    BASE_DIR / "static",
]

# 🔹 7. LOGGING (nivel detallado para desarrollo)
LOGGING['loggers']['django']['level'] = 'DEBUG'
LOGGING['loggers']['apps']['level'] = 'DEBUG'

# 🔹 8. HERRAMIENTAS DE DESARROLLO (Debug Toolbar)
INSTALLED_APPS += [
    'debug_toolbar',
]

MIDDLEWARE += [
    'debug_toolbar.middleware.DebugToolbarMiddleware',
]

INTERNAL_IPS = ['127.0.0.1', 'localhost']

# 🔹 9. CACHE LOCAL (opcional, mejora el rendimiento durante desarrollo)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'mexared-dev-cache',
    }
}

# 🔹 10. MEDIA (útil si se suben archivos durante desarrollo)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
