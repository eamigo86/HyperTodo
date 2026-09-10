"""App session policy around the central, immutable package configuration."""

from dj_hyperview.conf import RealtimeSettings as RealtimeConfig
from dj_hyperview.conf import get_settings
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


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
