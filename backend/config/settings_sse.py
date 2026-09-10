"""Explicit local SSE profile: filesystem HXML only, without changing DB overrides."""

from . import settings as base

globals().update({key: value for key, value in vars(base).items() if key.isupper()})
HYPERVIEW = {
    **base.HYPERVIEW,
    "SOURCES": [{"BACKEND": "dj_hyperview.sources.FileSystemSource"}],
    "REALTIME": {
        "REDIS_URL": "redis://127.0.0.1:6379/15",
        "NAMESPACE": "hypertodo-development",
    },
}
