"""Application configuration for the TODO domain."""

from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured


class TodoConfig(AppConfig):
    """Configure the TODO domain application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "todo"

    def ready(self) -> None:
        """Require automatic schema enforcement before serving the application.

        Raises:
            ImproperlyConfigured: If the installed package does not provide the
                required automatic validation contract.
        """
        import dj_hyperview

        if (
            getattr(dj_hyperview, "HYPERVIEW_VALIDATION_CONTRACT", None)
            != "automatic-xsd-v1"
        ):
            raise ImproperlyConfigured(
                "HyperTodo requires dj-hyperview contract automatic-xsd-v1. "
                "Adopt the approved package and consumer configuration together; "
                "validation cannot be disabled."
            )

        from .realtime_signals import connect_realtime_signals

        connect_realtime_signals()
