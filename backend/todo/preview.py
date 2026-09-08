"""Synthetic contexts for database-backed HXML template previews."""

from importlib.metadata import version
from typing import Any

from dj_hyperview import HYPERVIEW_SCHEMA_VERSION
from django.http import HttpRequest
from django.utils import timezone

from .theme import palette


def _about_context(theme_name: str) -> dict[str, Any]:
    return {
        "theme": palette(theme_name),
        "app_version": "Admin preview",
        "django_version": version("Django"),
        "dj_hyperview_version": version("dj-hyperview"),
        "hyperview_version": HYPERVIEW_SCHEMA_VERSION,
        "copyright_year": timezone.now().year,
    }


def about_light(request: HttpRequest, template_name: str) -> dict[str, Any]:
    """Return representative About data using the light palette.

    Args:
        request: Authenticated Admin preview request.
        template_name: Name currently present in the template editor.

    Returns:
        Synthetic About context for a light-theme preview.
    """
    del request, template_name
    return _about_context("light")


def about_dark(request: HttpRequest, template_name: str) -> dict[str, Any]:
    """Return representative About data using the dark palette.

    Args:
        request: Authenticated Admin preview request.
        template_name: Name currently present in the template editor.

    Returns:
        Synthetic About context for a dark-theme preview.
    """
    del request, template_name
    return _about_context("dark")
