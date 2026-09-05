"""Application configuration for the TODO domain."""

from django.apps import AppConfig


class TodoConfig(AppConfig):
    """Configure the TODO domain application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "todo"
