"""Django settings for the HyperTodo backend."""

import os
from pathlib import Path

from .environment import csv_setting
from .schema import schema_extensions

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "development-only-secret-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
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
AUTH_PASSWORD_VALIDATORS: list[dict[str, str]] = []
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
    # Opt-in transport, independent of cache and automatic schema validation.
    # Enable with explicit REDIS_URL and an app/environment-specific NAMESPACE.
    "REALTIME": None,
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
