"""Django settings for the HyperTodo backend."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .environment import csv_setting
from .schema import schema_extensions

BASE_DIR = Path(__file__).resolve().parent.parent
# Public on purpose: the development flow and the test suite need a working key with
# no setup. That is also why DEBUG may not be switched off while it is in use.
_PUBLIC_SECRET_KEY = "development-only-secret-key"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", _PUBLIC_SECRET_KEY)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
if not DEBUG and SECRET_KEY == _PUBLIC_SECRET_KEY:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY when DJANGO_DEBUG=0")
ALLOWED_HOSTS = csv_setting(
    "DJANGO_ALLOWED_HOSTS",
    "127.0.0.1,localhost,10.0.2.2",
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_ace",
    "dj_hyperview",
    "dj_hyperview.contrib.database",
    "todo",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Response order reverses: finalize identity after Django saves its session.
    "todo.session_middleware.SessionBindingResponseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # Before CommonMiddleware because APPEND_SLASH redirects and any i18n URL
    # resolution need a language already active; it also owns Content-Language and
    # the Vary: Accept-Language patch, which is why we do not hand-roll it.
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    # Reject non-GET on the exact SSE path before CSRF; all GET guards remain.
    "todo.realtime_middleware.RealtimeMethodMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Before profile/theme queries and application writes; Django still owns auth.
    "todo.session_middleware.SessionContractMiddleware",
    # After AuthenticationMiddleware, because that is what puts request.user on the
    # request. Response middleware unwinds bottom-up, so the language this installs
    # is still active when LocaleMiddleware writes Content-Language.
    "todo.middleware.ProfileLanguageMiddleware",
    # Also after AuthenticationMiddleware, for the same reason: it resolves the
    # palette from request.user.profile. Response middleware unwinds bottom-up, so
    # this runs on a TemplateResponse Django has already rendered and the header it
    # writes can only ever name the palette that stylesheet was built from.
    "todo.middleware.ThemeHeaderMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # dj-hyperview copies this whole OPTIONS mapping into its own
                # engine, so the palette reaches every HXML screen document.
                "todo.context_processors.theme",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
}
# Django's four standard validators. They guard Admin and changepassword; seed_demo and
# create_user call set_password, which skips validation by design.
AUTH_PASSWORD_VALIDATORS: list[dict[str, str]] = [
    {"NAME": f"django.contrib.auth.password_validation.{name}"}
    for name in (
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    )
]
LANGUAGE_CODE = "en-us"
LANGUAGES = [("en", "English"), ("es", "Español")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = os.environ.get("TIME_ZONE", "America/New_York")
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
# User uploads. Django normalises the missing leading slash exactly as it does
# for STATIC_URL above; the slash matters because <image source> resolves a
# relative url against the SCREEN url, so a bare "media/" would be fetched as
# /hv/media/... from every screen that shows an avatar.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CSRF_TRUSTED_ORIGINS = csv_setting(
    "CSRF_TRUSTED_ORIGINS",
    "http://127.0.0.1:8000,http://10.0.2.2:8000",
)
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SAMESITE = "Lax"
# Development talks plain http:// to a simulator or a LAN phone; anything else is HTTPS.
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = not DEBUG
# Opt-in for a TLS-terminating reverse proxy: the META name of the header it sets
# (for example HTTP_X_FORWARDED_PROTO). Only behind a proxy that also strips any
# client-supplied copy, otherwise a client could claim HTTPS for itself.
if _proxy_ssl_header := os.environ.get("DJANGO_SECURE_PROXY_SSL_HEADER"):
    SECURE_PROXY_SSL_HEADER = (_proxy_ssl_header, "https")

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/15")
ENABLE_REDIS_CACHE = os.environ.get("ENABLE_REDIS_CACHE", "0") == "1"
if ENABLE_REDIS_CACHE:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
            "KEY_PREFIX": "dj-hyperview-test-dev",
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "hypertodo",
        }
    }

HYPERVIEW = {
    "TEMPLATE_DIRS": [BASE_DIR / "hyperview"],
    "SOURCES": [
        {
            "BACKEND": "dj_hyperview.contrib.database.sources.DatabaseSource",
            "OPTIONS": {"using": "default"},
        },
        {"BACKEND": "dj_hyperview.sources.FileSystemSource"},
    ],
    "ADMIN": {"EDITOR": True},
    "EXTRA_SCHEMAS": [BASE_DIR / "schema" / "hypertodo.xsd"],
    "SCHEMA_EXTENSIONS": schema_extensions(),
    # All HTTP workers and template writers share this transport configuration.
    # Redis must already be running; cache remains independently optional.
    "REALTIME": {
        "REDIS_URL": REDIS_URL,
        "NAMESPACE": os.environ.get(
            "HYPERTODO_REALTIME_NAMESPACE", "hypertodo-development"
        ),
    },
}
if ENABLE_REDIS_CACHE:
    HYPERVIEW["CACHE"] = {
        "ALIAS": "default",
        "NAMESPACE": "dj-hyperview-test-dev",
        "TTL": 300,
        "NEGATIVE_TTL": 5,
        "FAILURE_MODE": "bypass",
    }
CSRF_FAILURE_VIEW = "todo.views.csrf_failure"
# The source-precedence acceptance fixture (/hv/source-probe/) answers without a
# session, so it follows DEBUG, which only a development machine has on, unless the
# environment says otherwise: HYPERTODO_SOURCE_PROBE=1 routes it, =0 never does.
HYPERTODO_SOURCE_PROBE = (
    os.environ.get("HYPERTODO_SOURCE_PROBE", "1" if DEBUG else "0") == "1"
)
