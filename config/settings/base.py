"""
Configuración base para MexaRed.
Este archivo contiene las configuraciones compartidas para todos los entornos (dev, prod).
Optimizado para rendimiento, seguridad y escalabilidad internacional.
"""

import os
from pathlib import Path
from django.utils.translation import gettext_lazy as _
from datetime import timedelta
import environ
import sys

# 🔹 1. INICIALIZACIÓN DE ENTORNO
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    CORS_ALLOWED_ORIGINS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
    REDIS_URL=(str, 'redis://127.0.0.1:6379/1'),
)

# 🔹 2. DIRECTORIOS Y PATHS
BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(exist_ok=True)
MEDIA_ROOT = BASE_DIR / 'media'
MEDIA_ROOT.mkdir(exist_ok=True)
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATIC_ROOT.mkdir(exist_ok=True)

# 🔹 3. SEGURIDAD GENERAL
SECRET_KEY = env('DJANGO_SECRET_KEY', default=None)
if not SECRET_KEY or SECRET_KEY == 'insecure-dev-key-for-testing-only':
    if 'prod' in env('DJANGO_SETTINGS_MODULE', default='config.settings.base'):
        raise ValueError("SECRET_KEY debe configurarse en .env para producción")
    SECRET_KEY = 'insecure-dev-key-for-testing-only'  # Solo para desarrollo local

DEBUG = env('DEBUG')
ALLOWED_HOSTS = env('ALLOWED_HOSTS')
CSRF_TRUSTED_ORIGINS = env('CSRF_TRUSTED_ORIGINS')
CORS_ALLOWED_ORIGINS = env('CORS_ALLOWED_ORIGINS')

# 🔹 4. APLICACIONES INSTALADAS
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'dal',  # Autocompletado en admin
    'dal_select2',
    'import_export',  # Exportación de datos
    'rangefilter',  # Filtros de rango en admin
    'widget_tweaks',  # Personalización de formularios
    'rest_framework',  # APIs REST
    'corsheaders',  # Soporte CORS
    'django_filters',  # Filtros en APIs
    'django_redis',  # Caché con Redis
    'apps.users.apps.UsersConfig',
    'apps.vendedores',
    'apps.transacciones',
    'apps.wallet',
    'apps.lineas',
    'apps.ofertas',
    'apps.activaciones',
]

# 🔹 5. MIDDLEWARE
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Servir archivos estáticos
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.middleware.RequestLoggingMiddleware',  # Log de solicitudes
]

# 🔹 6. URLs Y APLICACIÓN
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# 🔹 7. TEMPLATES
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.i18n',
            ],
        },
    },
]

# 🔹 8. BASE DE DATOS
DATABASES = {
    'default': env.db(
        'DATABASE_URL',
        default='postgres://postgres:Campo@localhost:5432/mexared_db'
    )
}

# 🔹 9. AUTENTICACIÓN
AUTH_USER_MODEL = 'users.User'

# 🔹 10. INTERNACIONALIZACIÓN
LANGUAGE_CODE = 'es-mx'
TIME_ZONE = 'America/Mexico_City'  # Ajustado para México
USE_I18N = True
USE_L10N = True
USE_TZ = True
LANGUAGES = [
    ('es-mx', _('Español (México)')),
    ('en', _('English')),
    ('pt-br', _('Português (Brasil)')),
    # Preparado para expansión a otros mercados (e.g., es-co, es-ar)
]
LOCALE_PATHS = [BASE_DIR / 'locale']

# 🔹 11. ARCHIVOS ESTÁTICOS Y MEDIA
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# 🔹 12. CAMPO AUTOMÁTICO
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 🔹 13. REST FRAMEWORK
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 100,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '500/hour',  # Aumentado para tráfico esperado
        'user': '5000/hour',
    },
}

# 🔹 14. JWT CONFIGURACIÓN
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# 🔹 15. CORS
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = env('CORS_ALLOWED_ORIGINS')
CSRF_TRUSTED_ORIGINS = env('CSRF_TRUSTED_ORIGINS')

# 🔹 16. LOGGING OPTIMIZADO Y ROBUSTO
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {name} {module} {funcName} {lineno} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(levelname)s %(asctime)s %(name)s %(module)s %(funcName)s %(lineno)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG' if DEBUG else 'WARNING',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'mexared.log',
            'maxBytes': 10 * 1024 * 1024,  # 10MB
            'backupCount': 5,
            'formatter': 'json',  # JSON para observability
        },
        'security': {
            'level': 'WARNING',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'security.log',
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'json',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console', 'file'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['security'],
            'level': 'WARNING',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG' if DEBUG else 'WARNING',
            'propagate': False,
        },
    },
}

# 🔹 17. SEGURIDAD AVANZADA
SECURE_SSL_REDIRECT = True  # Forzar HTTPS en producción
CSRF_COOKIE_SECURE = True  # Cookies CSRF solo por HTTPS
SESSION_COOKIE_SECURE = True  # Cookies de sesión solo por HTTPS
SECURE_HSTS_SECONDS = 31536000  # 1 año para HSTS
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'

# 🔹 18. EMAIL
EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='MexaRed <no-reply@mexared.com.mx>')

# 🔹 19. CACHE
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': env('REDIS_URL'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# 🔹 20. ADDINTELI API CONFIGURACIÓN
ADDINTELI_API_MODE = env('ADDINTELI_API_MODE', default='sandbox')
ADDINTELI_API_URL = {
    'sandbox': env('ADDINTELI_API_URL_SANDBOX', default='https://addinteli-dev-api.com.mx'),
    'prod': env('ADDINTELI_API_URL_PROD', default='https://addinteli-prod-api.com.mx'),
}
ADDINTELI_API_TOKEN = {
    'sandbox': env('ADDINTELI_API_TOKEN_SANDBOX', default=''),  # Reemplazar con token real
    'prod': env('ADDINTELI_API_TOKEN_PROD', default=''),  # Reemplazar con token real
}
ADDINTELI_DISTRIBUTOR_ID = env('ADDINTELI_DISTRIBUTOR_ID', default='4b61cf5c-7199-462f-a946-464234e9e318')
ADDINTELI_WALLET_ID = env('ADDINTELI_WALLET_ID', default='fb1f922e-5cf8-4235-926a-06525fd20239')
ADDINTELI_RETRY_TOTAL = env.int('ADDINTELI_RETRY_TOTAL', default=3)