"""Isolated resources for testing the ordinary consumer validation contract."""

from config import settings as base

# Keep the actual application configuration, but never its database or cache.
globals().update({key: value for key, value in vars(base).items() if key.isupper()})
HYPERVIEW = {**base.HYPERVIEW, "REALTIME": None}
HYPERVIEW.pop("CACHE", None)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "TEST": {"NAME": ":memory:"},
    }
}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "schema-corpus-tests",
    }
}

MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
