"""App session policy around the central, immutable package configuration."""

from functools import cache
from typing import TYPE_CHECKING

from dj_hyperview.conf import RealtimeSettings as RealtimeConfig
from dj_hyperview.conf import get_settings
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

if TYPE_CHECKING:
    from dj_hyperview.realtime import RedisBroker


def get_realtime_config() -> RealtimeConfig | None:
    """Read central settings and enforce HyperTodo's database-session policy.

    Returns:
        Immutable configuration, or None when realtime is disabled.

    Raises:
        ImproperlyConfigured: If legacy configuration, transport or sessions
            are invalid.
    """
    if hasattr(settings, "HYPERTODO_REALTIME"):
        raise ImproperlyConfigured(
            "HYPERTODO_REALTIME was removed; migrate to HYPERVIEW['REALTIME'] "
            "and remove the legacy setting even when None."
        )
    configured = get_settings().realtime
    if (
        configured is not None
        and settings.SESSION_ENGINE != "django.contrib.sessions.backends.db"
    ):
        raise ImproperlyConfigured(
            "HYPERVIEW['REALTIME'] requires database sessions in HyperTodo."
        )
    return configured


@cache
def get_broker(config: RealtimeConfig) -> RedisBroker:
    """Return the one broker that serves an immutable configuration.

    The broker only captures validated settings: it opens no connection when built,
    and every publish and every subscription opens and closes its own. Sharing one
    instance is therefore safe across threads and event loops, and it spares
    validating the same URL again on each publish and each stream.

    Args:
        config: Configuration returned by get_realtime_config. It is hashable, so
            an equal configuration read again finds the same broker.

    Returns:
        The package broker for that Redis endpoint and namespace.
    """
    from dj_hyperview.realtime import RedisBroker

    return RedisBroker(config.redis_url, namespace=config.namespace)
