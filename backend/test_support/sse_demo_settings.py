"""Explicit disposable normal-App SSE settings; never deployment defaults."""

from . import native_app_settings as base
from .native_app_fixture import load_fixture

globals().update({key: value for key, value in vars(base).items() if key.isupper()})
HYPERVIEW = {
    **base.HYPERVIEW,
    "REALTIME": {
        "REDIS_URL": "redis://127.0.0.1:6379/14",
        "NAMESPACE": "hypertodo-demo-" + load_fixture().run_id,
    },
}
