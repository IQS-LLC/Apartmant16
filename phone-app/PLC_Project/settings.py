"""
Lumina PLC Backend — Django Settings
Production-hardened with structured logging, rate limiting, and security controls.
All secrets are read from environment variables.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Security ──────────────────────────────────────────────────────────────────

# In production: set SECRET_KEY env var to a long random string.
SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "django-insecure-change-me-in-production-use-env-var",
)

DEBUG = os.getenv("DEBUG", "True").lower() == "true"

ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "192.168.0.158",   # LAN server IP (Django host)
    "192.168.0.161",   # TwinCAT/PLC machine IP (Apartment 16)
    *[h.strip() for h in os.getenv("EXTRA_ALLOWED_HOSTS", "").split(",") if h.strip()],
]

# ── Application ───────────────────────────────────────────────────────────────

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "find_device",
]

MIDDLEWARE = [
    # CORS must be first
    "corsheaders.middleware.CorsMiddleware",
    # Lumina middlewares
    "find_device.middleware.RateLimitMiddleware",
    "find_device.middleware.APIKeyMiddleware",
    "find_device.middleware.RequestLoggingMiddleware",
    # Django built-ins
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "PLC_Project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "PLC_Project.wsgi.application"

# ── Database ──────────────────────────────────────────────────────────────────

DATABASES = {
    "default": {
        "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME":   os.getenv("DB_NAME",   str(BASE_DIR / "db.sqlite3")),
        "USER":   os.getenv("DB_USER",   ""),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST":   os.getenv("DB_HOST",   ""),
        "PORT":   os.getenv("DB_PORT",   ""),
        # Connection pooling and resilience
        "OPTIONS": {},
        "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
    }
}

# ── Auth ──────────────────────────────────────────────────────────────────────

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ── Internationalisation ──────────────────────────────────────────────────────

LANGUAGE_CODE = "en-us"
TIME_ZONE     = os.getenv("TIME_ZONE", "UTC")
USE_I18N      = True
USE_TZ        = True

# ── Static files ──────────────────────────────────────────────────────────────

STATIC_URL   = "/static/"
STATIC_ROOT  = BASE_DIR / "static"
MEDIA_URL    = "/media/"
MEDIA_ROOT   = BASE_DIR / "media"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ── CORS ──────────────────────────────────────────────────────────────────────
# For a local-network app we allow all origins.
# In a public deployment restrict to specific origins via CORS_ALLOWED_ORIGINS.

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_METHODS     = ["GET", "POST", "OPTIONS"]
CORS_ALLOW_HEADERS     = ["content-type", "x-api-key", "accept"]

# ── Rate limiting (used by RateLimitMiddleware) ───────────────────────────────

RATE_LIMIT_REQUESTS       = int(os.getenv("RATE_LIMIT_REQUESTS", "200"))
RATE_LIMIT_WRITE_REQUESTS = int(os.getenv("RATE_LIMIT_WRITE_REQUESTS", "60"))
RATE_LIMIT_WINDOW         = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

# ── Production security headers (HTTPS only) ──────────────────────────────────

if not DEBUG and os.getenv("HTTPS_ENABLED", "False").lower() == "true":
    SECURE_BROWSER_XSS_FILTER        = True
    SECURE_CONTENT_TYPE_NOSNIFF       = True
    SECURE_HSTS_INCLUDE_SUBDOMAINS    = True
    SECURE_HSTS_PRELOAD               = True
    SECURE_HSTS_SECONDS               = 31_536_000  # 1 year
    SESSION_COOKIE_SECURE             = True
    CSRF_COOKIE_SECURE                = True
    SECURE_SSL_REDIRECT               = True

# ── Structured logging ────────────────────────────────────────────────────────

LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG" if DEBUG else "INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "django.utils.log.ServerFormatter",
            "format": "{levelname} {asctime} {name} {message}",
            "style":  "{",
        },
        "verbose": {
            "format": "{levelname} {asctime} [{name}] {message}",
            "style":  "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style":  "{",
        },
    },
    "filters": {
        "require_debug_false": {"()": "django.utils.log.RequireDebugFalse"},
    },
    "handlers": {
        "console": {
            "class":     "logging.StreamHandler",
            "formatter": "verbose",
        },
        "error_file": {
            "class":     "logging.handlers.RotatingFileHandler",
            "filename":  str(BASE_DIR / "logs" / "errors.log"),
            "maxBytes":  10 * 1024 * 1024,  # 10 MB
            "backupCount": 5,
            "formatter": "verbose",
            "level":     "ERROR",
        },
    },
    "root": {
        "handlers": ["console"],
        "level":    LOG_LEVEL,
    },
    "loggers": {
        "lumina": {
            "handlers":  ["console"],
            "level":     LOG_LEVEL,
            "propagate": False,
        },
        "lumina.http": {
            "handlers":  ["console"],
            "level":     "INFO",
            "propagate": False,
        },
        "django.server": {
            "handlers":  ["console"],
            "level":     "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers":  ["console"],
            "level":     "WARNING",
            "propagate": False,
        },
        "pyads": {
            "handlers":  ["console"],
            "level":     "WARNING",
            "propagate": False,
        },
    },
}

# Create logs directory if it doesn't exist
_logs_dir = BASE_DIR / "logs"
_logs_dir.mkdir(exist_ok=True)

# ── Django REST Framework ─────────────────────────────────────────────────────

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_THROTTLE_CLASSES": [],  # handled by our own middleware
    "EXCEPTION_HANDLER": "find_device.auth_views.drf_exception_handler",
}

# ── JWT ───────────────────────────────────────────────────────────────────────

from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME":  timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS":  True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_OBTAIN_SERIALIZER": "find_device.auth_views.LuminaTokenObtainSerializer",
}

# ── Authentication ────────────────────────────────────────────────────────────
# Set to True to require JWT on all /plc/ endpoints.
# Leave False during development / migration to keep existing integrations working.

PLC_REQUIRE_AUTH = os.getenv("PLC_REQUIRE_AUTH", "False").lower() == "true"
