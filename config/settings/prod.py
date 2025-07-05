from pathlib import Path
from .base import *                     # noqa: F403
from dotenv import load_dotenv
from decouple import config, Csv
from corsheaders.defaults import default_headers
import dj_database_url                  # type: ignore
import logging

load_dotenv()                           # Carga las variables del .env

# ─────────────── 1. DEBUG & HOSTS ───────────────
DEBUG: bool = False
ALLOWED_HOSTS: list[str] = config(
    "ALLOWED_HOSTS",
    cast=Csv(),
    default="www.mexared.com.mx,mexared.com.mx,127.0.0.1,localhost",
)
CSRF_TRUSTED_ORIGINS: list[str] = [f"https://{h}" for h in ALLOWED_HOSTS]

# ─────────────── 2. DATABASE ───────────────
DATABASES = {
    "default": dj_database_url.parse(
        config(
            "DATABASE_URL",
            default=(
                "postgresql://{user}:{pwd}@{host}:{port}/{db}".format(
                    user=config("POSTGRES_USER", default="postgres"),
                    pwd=config("POSTGRES_PASSWORD", default=""),
                    host=config("POSTGRES_HOST", default="localhost"),
                    port=config("POSTGRES_PORT", default="5432"),
                    db=config("POSTGRES_DB", default="postgres"),
                )
            ),
        ),
        conn_max_age=600,
        ssl_require=not DEBUG,
    )
}

# ─────────────── 3. CORS ───────────────
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS: list[str] = config(
    "CORS_ALLOWED_ORIGINS",
    cast=Csv(),
    default="https://www.mexared.com.mx,https://mexared.com.mx",
)
CORS_ALLOW_HEADERS = list(default_headers) + ["X-CSRFToken", "Authorization"]

# ─────────────── 4. SECURITY ───────────────
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
CSRF_COOKIE_HTTPONLY = True








# ─────────────── 5. EMAIL ───────────────
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = config("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = config("EMAIL_PORT", cast=int, default=587)
EMAIL_USE_TLS = True
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL", default="MexaRed <noreply@mexared.com.mx>"
)
SERVER_EMAIL = DEFAULT_FROM_EMAIL
if not EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# ─────────────── 6. STATIC & MEDIA ───────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"      # noqa: F405
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"            # noqa: F405

# ─────────────── 7. LOGGING ───────────────
LOGGING["loggers"]["django"]["level"] = "WARNING"        # noqa: F405
LOGGING["loggers"]["apps"]["level"] = "INFO"             # noqa: F405
LOGGING["handlers"]["file"]["filename"] = BASE_DIR / "logs/production.log"  # noqa: F405

# ─────────────── 8. ADMINS ───────────────
ADMINS = [
    (config("ADMIN_NAME", default="Administrador"),
     config("ADMIN_EMAIL", default="admin@mexared.com.mx"))
]
MANAGERS = ADMINS

# ─────────────── 9. SESSIONS ───────────────
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"

# ─────────────── 10. VALIDACIÓN FINAL ───────────────
logger = logging.getLogger(__name__)
logger.info("✅ Settings de producción cargados correctamente · DEBUG=%s", DEBUG)
