"""The project's own settings with its default SQLite database moved to a temp file.

Only the database NAME changes, from the HYPERTODO_RACE_DATABASE environment variable,
so the OPTIONS the project configures (transaction mode, lock timeout) are the ones
under test. The ordinary test settings use an in-memory database whose shared-cache
locking behaves nothing like a file, which is why the concurrency test runs a child
interpreter on this module instead.
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
