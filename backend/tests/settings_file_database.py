"""The project's own settings with its default SQLite database moved to a temp file.

Only the database NAME changes, from the HYPERTODO_RACE_DATABASE environment variable,
so the OPTIONS the project configures (transaction mode, lock timeout) are the ones
under test. The ordinary test settings use an in-memory database whose shared-cache
locking behaves nothing like a file, which is why the concurrency test runs a child
interpreter on this module instead.

Realtime and the template cache are switched off and the cache is in memory, as in
tests/settings_schema.py: the project settings point all three at the development
Redis, and 240 race writes would otherwise publish hints to its channels.
"""

import os

from config import settings as base

globals().update({key: value for key, value in vars(base).items() if key.isupper()})
DATABASES = {
    "default": {
        **base.DATABASES["default"],
        "NAME": os.environ["HYPERTODO_RACE_DATABASE"],
    }
}
HYPERVIEW = {**base.HYPERVIEW, "REALTIME": None}
HYPERVIEW.pop("CACHE", None)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "sqlite-race-tests",
    }
}
