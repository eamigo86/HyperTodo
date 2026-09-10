"""Two independent in-memory databases for realtime signal alias regression."""

from . import settings_schema as base

globals().update({key: value for key, value in vars(base).items() if key.isupper()})
DATABASES = {
    alias: {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
    for alias in ("default", "other")
}
HYPERVIEW = {
    **base.HYPERVIEW,
    "REALTIME": {
        "REDIS_URL": "redis://127.0.0.1:6379/14",
        "NAMESPACE": "alias-test",
    },
}
