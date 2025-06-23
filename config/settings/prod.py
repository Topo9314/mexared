# config/settings/prod.py

"""
Configuración para el entorno de producción de MexaRed.
Optimizaciones para despliegue seguro y eficiente en Render.com, Railway, Heroku o VPS.
"""

from .base import *
from decouple import config, Csv
from corsheaders.defaults import default_headers

# 🔹 1. DEBUG Y HOSTS
DEBUG = False
ALLOWED_HOSTS = config('ALLOWED_HOSTS', cast=Csv(), default='mexared.com,www.mexared.com,.onrender.com')

# 🔹 2. BASE DE DATOS (PostgreSQL en la nube)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('POSTGRES_DB', default='mexared'),
        'USER': config('POSTGRES_USER', default='mexared_user'),
        'PASSWORD': config('POSTGRES_PASSWORD'),
        'HOST': config('POSTGRES_HOST', default='localhost'),
        'PORT': config('POSTGRES_PORT', default='5432'),
        'CONN_MAX_AGE': 600,
    }
}

# 🔹 3. CORS
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = config('CORS_ALLOWED_ORIGINS', cast=Csv(), default='https://mexared.com,https://www.mexared.com')

CORS_ALLOW_HEADERS = list(default_headers) + [
    'X-CSRFToken',
    'Authorization',
]

# 🔹 4. SEGURIDAD AVANZADA
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
X_FRAME_OPTIONS = 'DENY'
CSRF_COOKIE_HTTPONLY = True

# 🔹 5. EMAIL (Producción)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('EMAIL_HOST', default='smtp.sendgrid.net')
EMAIL_PORT = config('EMAIL_PORT', cast=int, default=587)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='apikey')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD')
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='notificaciones@mexared.com')
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# 🔹 6. ARCHIVOS ESTÁTICOS Y MEDIA
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# 🔹 7. LOGGING
LOGGING['loggers']['django']['level'] = 'WARNING'
LOGGING['loggers']['apps']['level'] = 'INFO'
LOGGING['handlers']['file']['filename'] = BASE_DIR / 'logs/production.log'

# 🔹 8. ADMINISTRADORES DEL SISTEMA
ADMINS = [(config('ADMIN_NAME', default='Administrador'), config('ADMIN_EMAIL', default='admin@mexared.com'))]
MANAGERS = ADMINS

# 🔹 9. SESIONES
SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'

# 🔹 10. ALMACENAMIENTO EN LA NUBE (opcional: Amazon S3)
"""
INSTALLED_APPS += ['storages']
AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY')
AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME')
AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'
AWS_S3_FILE_OVERWRITE = False
STATICFILES_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
"""

# 🔹 11. SENTRY PARA MONITOREO DE ERRORES (opcional)
"""
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

sentry_sdk.init(
    dsn=config('SENTRY_DSN', default=''),
    integrations=[DjangoIntegration()],
    traces_sample_rate=0.2,
    send_default_pii=False,
    environment='production',
)
"""

# 🔹 12. CACHE REDIS (opcional)
"""
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': config('REDIS_URL', default='redis://127.0.0.1:6379/1'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}
"""
