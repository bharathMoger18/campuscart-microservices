import os
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv

# ─────────────────────────────────────────────
# Load .env file (only active in development)
# In Docker/K8s, env vars are injected directly
# ─────────────────────────────────────────────
load_dotenv()

# ─────────────────────────────────────────────
# BASE DIRECTORY
# ─────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

# ─────────────────────────────────────────────
# SECURITY
# ─────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "fallback-dev-key-change-in-production")
DEBUG = os.getenv("DEBUG", "True") == "True"

# ── KEY PATTERN ──────────────────────────────────────────────────────────────
# Container name "order-service" MUST be here.
# When Docker routes requests to this container, Host header = "order-service"
# Django rejects requests whose Host is not in ALLOWED_HOSTS → 400 Bad Request
# ─────────────────────────────────────────────────────────────────────────────
ALLOWED_HOSTS = os.getenv(
    "ALLOWED_HOSTS",
    "localhost,127.0.0.1,order-service"
).split(",")

# ─────────────────────────────────────────────
# INSTALLED APPS
# ─────────────────────────────────────────────
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "drf_spectacular",
    "django_prometheus",
    "django_filters",
]

LOCAL_APPS = [
    "cart",
    "orders",
    "payments",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ─────────────────────────────────────────────
# MIDDLEWARE
# ─────────────────────────────────────────────
# NOTE: django_prometheus middlewares MUST be first and last
# They wrap every request to count metrics
MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",   # ← FIRST
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",                     # ← before CommonMiddleware
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",    # ← LAST
]

# ─────────────────────────────────────────────
# URL CONFIGURATION
# ─────────────────────────────────────────────
ROOT_URLCONF = "order_service.urls"

# ─────────────────────────────────────────────
# TEMPLATES
# ─────────────────────────────────────────────
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ─────────────────────────────────────────────
# WSGI / ASGI
# ─────────────────────────────────────────────
WSGI_APPLICATION = "order_service.wsgi.application"
ASGI_APPLICATION = "order_service.asgi.application"

# ─────────────────────────────────────────────
# DATABASE
# ── KEY DECISION ─────────────────────────────
# order-service gets its OWN PostgreSQL database.
# Host port: 5435 (so it doesn't clash with system postgres on 5432,
#            auth-service on 5433, product-service on 5434)
# Inside Docker network: order-db:5432
# This DB has ONLY: cart, cartitem, order, orderitem, payment tables
# NO users table, NO products table — those live in other services
# ─────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django_prometheus.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "order_db"),
        "USER": os.getenv("DB_USER", "order_user"),
        "PASSWORD": os.getenv("DB_PASSWORD", "order_password"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5435"),
    }
}

# ─────────────────────────────────────────────
# PASSWORD VALIDATION
# ─────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ─────────────────────────────────────────────
# INTERNATIONALIZATION
# ─────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ─────────────────────────────────────────────
# STATIC FILES
# ─────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ─────────────────────────────────────────────
# DEFAULT PRIMARY KEY
# ─────────────────────────────────────────────
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─────────────────────────────────────────────
# DJANGO REST FRAMEWORK
# ─────────────────────────────────────────────
REST_FRAMEWORK = {
    # ── KEY DECISION ──────────────────────────────────────────────────────
    # Default authentication = our custom MicroserviceJWTAuthentication
    # Standard JWTAuthentication from simplejwt LOOKS UP User in local DB
    # We have NO users table → it would crash every request
    # Our custom class decodes the token WITHOUT touching the database
    # ──────────────────────────────────────────────────────────────────────
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "order_service.authentication.MicroserviceJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
}

# ─────────────────────────────────────────────
# JWT SETTINGS
# ── KEY DECISION ─────────────────────────────
# We use auth-service's SECRET_KEY to VERIFY tokens.
# auth-service CREATED and SIGNED the tokens with this key.
# We only need to VERIFY — same key, read-only use.
# Access token lifetime must match auth-service (60 min).
# ─────────────────────────────────────────────
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ALGORITHM": "HS256",
    "SIGNING_KEY": os.getenv("SECRET_KEY", "fallback-dev-key-change-in-production"),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# ─────────────────────────────────────────────
# CORS
# ─────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = os.getenv(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:8080"
).split(",")
CORS_ALLOW_CREDENTIALS = True

# ─────────────────────────────────────────────
# DRF SPECTACULAR (API DOCS)
# ─────────────────────────────────────────────
SPECTACULAR_SETTINGS = {
    "TITLE": "CampusCart Order Service API",
    "DESCRIPTION": "Handles cart, orders, and payments for CampusCart",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ─────────────────────────────────────────────
# STRIPE
# ─────────────────────────────────────────────
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# ─────────────────────────────────────────────
# INTER-SERVICE URLs
# ─────────────────────────────────────────────
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8000")
PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "http://product-service:8000")

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
# CI/CD test - Tuesday 12 May 2026 10:03:12 AM IST
